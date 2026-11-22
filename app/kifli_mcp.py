from __future__ import annotations

import asyncio
import copy
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

log = logging.getLogger("kifli_otthon.mcp")

# Biztonsági fék: az AI soha nem adhat le fizetős rendelést, nem mondhat le meglévő
# rendelést és nem adhat be ügyfélszolgálati reklamációt — kizárólag a kosarat kezelheti!
BLOCKED_TOOL_SUBSTRINGS = (
    "checkout",
    "place_order",
    "submit_order",
    "pay",
    "cancel_order",
    "remove_order_items",
    "repeat_order",
    "submit_claim",
    "submit_credit_compensation",
    "credit_customer_returnables",
)

# Csak a valóban szükséges Kifli.hu vásárlási/kosár/recept/akció eszközöket adjuk át az LLM-nek,
# így ~75%-kal kevesebb tokent (és pénzt!) fogyaszt minden egyes üzenet, és sokkal gyorsabb!
ESSENTIAL_KIFLI_TOOLS = {
    "batch_search_products",
    "search_products",
    "get_product_details",
    "get_discounted_items",
    "get_cart",
    "get_cart_content",
    "add_items_to_cart",
    "add_to_cart",
    "update_cart_item",
    "remove_cart_item",
    "remove_from_cart",
    "clear_cart",
    "get_all_user_favorites",
    "search_recipes_by_vector_similarity",
    "get_recipe_detail",
    "fetch_orders",
    "get_typical_order",
}


def sanitize_json_schema_for_llm(schema: dict[str, Any] | None) -> dict[str, Any]:
    """
    Normalizálja az MCP tool JSON sémákat úgy, hogy mind a Google Gemini 2.5 Flash
    OpenAI-kompatibilis végpontja, mind az OpenAI gpt-4.1-mini hiba nélkül elfogadja.
    """
    if not schema or not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    defs = schema.get("$defs") or schema.get("definitions") or {}

    def _clean(node: Any) -> Any:
        if isinstance(node, list):
            return [_clean(item) for item in node]
        if not isinstance(node, dict):
            return node

        if "$ref" in node and isinstance(node["$ref"], str):
            ref_name = node["$ref"].split("/")[-1]
            if ref_name in defs:
                return _clean(copy.deepcopy(defs[ref_name]))

        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in (
                "$schema",
                "$defs",
                "definitions",
                "additionalProperties",
                "title",
                "examples",
                "default",
            ):
                continue
            if k == "anyOf" and isinstance(v, list):
                non_null = [opt for opt in v if not (isinstance(opt, dict) and opt.get("type") == "null")]
                if non_null:
                    merged = _clean(non_null[0])
                    if isinstance(merged, dict):
                        out.update(merged)
                    continue
            out[k] = _clean(v)

        if isinstance(out.get("type"), list):
            non_null_types = [t for t in out["type"] if t != "null"]
            out["type"] = non_null_types[0] if non_null_types else "string"

        if out.get("type") == "object" and "properties" not in out:
            out["properties"] = {}
        return out

    cleaned = _clean(copy.deepcopy(schema))
    if not isinstance(cleaned, dict) or cleaned.get("type") != "object":
        cleaned = {"type": "object", "properties": {}}
    cleaned.setdefault("properties", {})
    return cleaned


class DiskOAuthStorage(TokenStorage):
    """Tartós OAuth 2.1 token + dinamikus kliens tároló a ./data/kifli_oauth mappában."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.tokens_file = self.directory / "tokens.json"
        self.client_file = self.directory / "client.json"

    async def get_tokens(self) -> OAuthToken | None:
        if not self.tokens_file.exists():
            return None
        try:
            data = json.loads(self.tokens_file.read_text(encoding="utf-8"))
            return OAuthToken.model_validate(data)
        except Exception as exc:
            log.warning("Nem sikerült beolvasni a Kifli OAuth tokent: %s", exc)
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens_file.write_text(
            tokens.model_dump_json(indent=2), encoding="utf-8"
        )

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if not self.client_file.exists():
            return None
        try:
            data = json.loads(self.client_file.read_text(encoding="utf-8"))
            return OAuthClientInformationFull.model_validate(data)
        except Exception as exc:
            log.warning("Nem sikerült beolvasni a Kifli OAuth client_info-t: %s", exc)
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_file.write_text(
            client_info.model_dump_json(indent=2), encoding="utf-8"
        )

    def clear(self) -> None:
        for f in (self.tokens_file, self.client_file):
            if f.exists():
                f.unlink()


class KifliMCPManager:
    """
    Kifli.hu hivatalos MCP kliens (https://mcp.kifli.hu/mcp).
    Támogatja a távoli Linux szerveres (böngésző nélküli) OAuth 2.1 PKCE belépést:
    1) start_login_flow() -> visszaadja az identity.kifli.hu belépési linket
    2) submit_callback_url(url) -> kinyeri a code + state paramétert a localhost redirect URL-ből,
       beváltja access + refresh tokenre, és onnantól automatikusan frissíti!
    """

    def __init__(self, mcp_url: str, redirect_uri: str, oauth_dir: Path) -> None:
        self.mcp_url = mcp_url
        self.redirect_uri = redirect_uri
        self.storage = DiskOAuthStorage(oauth_dir)
        self._pending_auth_url: str | None = None
        self._callback_future: asyncio.Future[AuthorizationCodeResult] | None = None
        self._login_task: asyncio.Task[Any] | None = None
        self._local_cb_server: asyncio.AbstractServer | None = None
        self._cached_tools: list[dict[str, Any]] | None = None
        self._last_error: str = ""

    async def _stop_local_callback_server(self) -> None:
        if self._local_cb_server is not None:
            self._local_cb_server.close()
            try:
                await self._local_cb_server.wait_closed()
            except Exception:
                pass
            self._local_cb_server = None

    async def _start_local_callback_server(self) -> None:
        await self._stop_local_callback_server()
        parsed_redirect = urlsplit(self.redirect_uri)
        cb_port = parsed_redirect.port or 3334

        async def _handle_http(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                req_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                parts = req_line.decode("utf-8", errors="ignore").split()
                path_and_query = parts[1] if len(parts) >= 2 else "/"
                while True:
                    hdr = await asyncio.wait_for(reader.readline(), timeout=5.0)
                    if not hdr or hdr in (b"\r\n", b"\n"):
                        break

                parsed = urlsplit(path_and_query)
                qs = parse_qs(parsed.query)
                code_list = qs.get("code")
                if code_list and self._callback_future and not self._callback_future.done():
                    self._callback_future.set_result(
                        AuthorizationCodeResult(
                            code=code_list[0],
                            state=qs.get("state", [None])[0],
                            iss=qs.get("iss", [None])[0],
                        )
                    )
                    html_body = (
                        "<!DOCTYPE html><html lang='hu'><head><meta charset='utf-8'>"
                        "<title>Kifli.hu Összekötve</title></head>"
                        "<body style='background:#0f172a;color:#f8fafc;font-family:sans-serif;text-align:center;padding:4rem;'>"
                        "<h1 style='color:#10b981;'>✅ Kifli.hu sikeresen összekötve!</h1>"
                        "<p>Az OAuth 2.1 token elmentve. Bezárhatod ezt az ablakot és visszatérhetsz a Kifli Otthon felületére.</p>"
                        "</body></html>"
                    )
                else:
                    html_body = (
                        "<!DOCTYPE html><html lang='hu'><head><meta charset='utf-8'></head>"
                        "<body>Hiányzó OAuth code paraméter.</body></html>"
                    )

                payload = html_body.encode("utf-8")
                resp = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/html; charset=utf-8\r\n"
                    b"Connection: close\r\n"
                    + f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
                    + payload
                )
                writer.write(resp)
                await writer.drain()
            except Exception as exc:
                log.debug("Local OAuth callback HTTP olvasási hiba: %s", exc)
            finally:
                writer.close()

        try:
            self._local_cb_server = await asyncio.start_server(
                _handle_http, host="127.0.0.1", port=cb_port
            )
            log.info("Automatikus OAuth callback figyelő elindítva: 127.0.0.1:%d", cb_port)
        except OSError as exc:
            log.info(
                "A localhost:%d port nem nyitható (távoli szervernél normális, marad a kézi URL bemásolás): %s",
                cb_port,
                exc,
            )

    async def get_status(self) -> dict[str, Any]:
        tokens = await self.storage.get_tokens()
        return {
            "mcp_url": self.mcp_url,
            "authenticated": tokens is not None and bool(tokens.access_token),
            "has_refresh_token": bool(tokens and tokens.refresh_token),
            "pending_login_url": self._pending_auth_url,
            "cached_tool_count": len(self._cached_tools) if self._cached_tools is not None else 0,
            "last_error": self._last_error,
        }

    def _build_oauth_provider(
        self,
        redirect_handler: Any,
        callback_handler: Any,
    ) -> OAuthClientProvider:
        metadata = OAuthClientMetadata(
            client_name="Kifli Otthon Menu Assistant",
            redirect_uris=[self.redirect_uri],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="openid email roles offline_access",
            token_endpoint_auth_method="none",
        )
        return OAuthClientProvider(
            server_url=self.mcp_url,
            client_metadata=metadata,
            storage=self.storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

    async def start_login_flow(self) -> str:
        if self._login_task and not self._login_task.done():
            self._login_task.cancel()

        loop = asyncio.get_running_loop()
        url_ready: asyncio.Future[str] = loop.create_future()
        self._callback_future = loop.create_future()
        self._last_error = ""
        await self._start_local_callback_server()

        async def _on_redirect(auth_url: str) -> None:
            self._pending_auth_url = auth_url
            if not url_ready.done():
                url_ready.set_result(auth_url)

        async def _on_callback() -> AuthorizationCodeResult:
            assert self._callback_future is not None
            return await asyncio.wait_for(self._callback_future, timeout=600.0)

        async def _runner() -> None:
            try:
                auth = self._build_oauth_provider(_on_redirect, _on_callback)
                async with create_mcp_http_client(auth=auth) as http_client:
                    async with streamable_http_client(
                        self.mcp_url,
                        http_client=http_client,
                        terminate_on_close=False,
                    ) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_resp = await session.list_tools()
                            self._cached_tools = self._convert_tools(tools_resp.tools)
                self._pending_auth_url = None
                self._last_error = ""
            except Exception as exc:
                self._last_error = str(exc)
                log.warning("Kifli OAuth belépési folyamat hiba: %s", exc)
                if not url_ready.done():
                    url_ready.set_exception(exc)
            finally:
                await self._stop_local_callback_server()

        self._login_task = asyncio.create_task(_runner())
        return await asyncio.wait_for(url_ready, timeout=20.0)

    async def submit_callback_url(self, callback_url_or_code: str) -> dict[str, Any]:
        if not self._callback_future or self._callback_future.done():
            raise RuntimeError("Nincs folyamatban lévő Kifli belépés. Kattints először a Belépés indítására!")

        raw = callback_url_or_code.strip()
        iss: str | None = None
        if "://" in raw or raw.startswith("?"):
            parsed = urlsplit(raw)
            qs = parse_qs(parsed.query)
            code_list = qs.get("code")
            if not code_list:
                raise ValueError("A bemásolt URL nem tartalmaz '?code=...' paramétert!")
            code = code_list[0]
            state = qs.get("state", [None])[0]
            iss = qs.get("iss", [None])[0]
        else:
            code = raw
            state = None

        self._callback_future.set_result(
            AuthorizationCodeResult(code=code, state=state, iss=iss)
        )
        if self._login_task:
            await asyncio.wait_for(self._login_task, timeout=25.0)
        return await self.get_status()

    async def logout(self) -> None:
        if self._login_task and not self._login_task.done():
            self._login_task.cancel()
        await self._stop_local_callback_server()
        self._pending_auth_url = None
        self._cached_tools = None
        self.storage.clear()

    def _convert_tools(self, raw_tools: list[Any]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for t in raw_tools:
            tname = str(t.name)
            if any(blocked in tname.lower() for blocked in BLOCKED_TOOL_SUBSTRINGS):
                continue
            if ESSENTIAL_KIFLI_TOOLS and tname not in ESSENTIAL_KIFLI_TOOLS:
                continue
            raw_schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)
            desc = (t.description or tname).strip()
            if len(desc) > 350:
                desc = desc[:350] + "..."
            converted.append(
                {
                    "mcp_name": tname,
                    "llm_name": f"kifli__{tname}",
                    "description": f"[Kifli.hu MCP] {desc}",
                    "parameters": sanitize_json_schema_for_llm(raw_schema),
                }
            )
        return converted

    async def _non_interactive_auth(self) -> OAuthClientProvider:
        tokens = await self.storage.get_tokens()
        if not tokens:
            raise RuntimeError(
                "A Kifli.hu fiók még nincs összekötve! Nyisd meg a webes felületen a 'Kifli MCP & Kamra' fület, és jelentkezz be egyszer."
            )

        async def _no_redirect(_url: str) -> None:
            raise RuntimeError("A Kifli OAuth token lejárt, kérlek jelentkezz be újra a Web UI-on!")

        async def _no_callback() -> AuthorizationCodeResult:
            raise RuntimeError("Interaktív OAuth callback nem elérhető háttérhívás közben.")

        return self._build_oauth_provider(_no_redirect, _no_callback)

    async def list_tools(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        tokens = await self.storage.get_tokens()
        if not tokens:
            return []
        if self._cached_tools is not None and not force_refresh:
            return self._cached_tools

        auth = await self._non_interactive_auth()
        async with create_mcp_http_client(auth=auth) as http_client:
            async with streamable_http_client(
                self.mcp_url,
                http_client=http_client,
                terminate_on_close=False,
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    resp = await session.list_tools()
                    self._cached_tools = self._convert_tools(resp.tools)
                    return self._cached_tools

    async def call_tool(self, mcp_tool_name: str, arguments: dict[str, Any]) -> str:
        if any(b in mcp_tool_name.lower() for b in BLOCKED_TOOL_SUBSTRINGS):
            return json.dumps(
                {"error": "Biztonsági szabály: automatikus fizetés/rendelés-leadás tiltva. Csak a kosárba helyezés engedélyezett!"},
                ensure_ascii=False,
            )
        auth = await self._non_interactive_auth()
        async with create_mcp_http_client(auth=auth) as http_client:
            async with streamable_http_client(
                self.mcp_url,
                http_client=http_client,
                terminate_on_close=False,
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(mcp_tool_name, arguments or {})
                chunks: list[str] = []
                for item in result.content:
                    text_val = getattr(item, "text", None)
                    if text_val:
                        chunks.append(text_val)
                    else:
                        chunks.append(str(item))
                output = "\n".join(chunks).strip()
                if len(output) > 28000:
                    output = output[:28000] + "\n...[csonkolva a token-takarékosság érdekében]"
                return output or json.dumps({"ok": True})

    async def call_tool_untruncated(self, mcp_tool_name: str, arguments: dict[str, Any]) -> str:
        """Közvetlen (0 LLM tokenes) backend API hívásokhoz csonkolás nélkül."""
        if any(b in mcp_tool_name.lower() for b in BLOCKED_TOOL_SUBSTRINGS):
            raise RuntimeError("Tiltott művelet.")
        auth = await self._non_interactive_auth()
        async with create_mcp_http_client(auth=auth) as http_client:
            async with streamable_http_client(
                self.mcp_url,
                http_client=http_client,
                terminate_on_close=False,
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(mcp_tool_name, arguments or {})
                    chunks = [getattr(item, "text", None) or str(item) for item in result.content]
                    return "\n".join(chunks).strip() or "{}"
