from __future__ import annotations

import hmac
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.db import DAYS_HU, Database
from app.media import download_and_save_recipe_image, save_recipe_image_base64


class OptionalPinASGIWrapper:
    """
    Claude Remote MCP & Streamable HTTP kompatibilitási + biztonsági réteg:
    1. Külön MCP_ACCESS_TOKEN ellenőrzés (path: /mcp/<TOKEN>, Bearer, X-App-Pin vagy ?pin=),
       így a belső LAN Web UI nem kér PIN-t, ha csak MCP_ACCESS_TOKEN van beállítva.
    2. OPTIONS (CORS preflight) -> azonnali 204 No Content.
    3. GET / DELETE -> azonnali 405 Method Not Allowed (stateless módban a mcp SDK GET-re
       végtelen üres SSE streamet nyitna, amin a Claude Remote MCP időtúllépéssel elhasal!).
    4. POST Accept fejléc normalizálás -> akkor is azonnali 200 OK application/json választ ad,
       ha a kliens csak `Accept: */*` vagy `Accept: application/json` fejlécet küld.
    """

    CORS_HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Accept, Authorization, X-App-Pin, Mcp-Session-Id, MCP-Protocol-Version",
        "Access-Control-Expose-Headers": "Mcp-Session-Id",
    }

    def __init__(self, app: ASGIApp, expected_token: str) -> None:
        self.app = app
        self.expected_token = expected_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()

        # 1. CORS preflight azonnal
        if method == "OPTIONS":
            resp = JSONResponse({}, status_code=204, headers=self.CORS_HEADERS)
            await resp(scope, receive, send)
            return

        # 2. Token ellenőrzés (ha MCP_ACCESS_TOKEN be van állítva)
        path_params = scope.get("path_params") or {}
        path_token = str(path_params.get("pin", "")).strip("/")

        if self.expected_token:
            req = Request(scope)
            auth_hdr = req.headers.get("authorization", "")
            bearer = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
            supplied = (
                path_token
                or bearer
                or req.headers.get("x-app-pin", "").strip()
                or req.query_params.get("pin", "").strip()
            )
            if not supplied or not hmac.compare_digest(supplied, self.expected_token):
                resp = JSONResponse(
                    {"error": "Unauthorized: missing or invalid MCP_ACCESS_TOKEN"},
                    status_code=401,
                    headers=self.CORS_HEADERS,
                )
                await resp(scope, receive, send)
                return

        # 3. Stateless Streamable HTTP: GET/DELETE-re azonnali 405 (ahogy a hivatalos Kifli MCP is!)
        #    Különben a Claude Remote MCP GET SSE streamje 0 bájttal örökre lógna és timeoutolna.
        if method in ("GET", "DELETE", "HEAD"):
            resp = JSONResponse(
                {"error": "Method Not Allowed: use POST for stateless MCP Streamable HTTP"},
                status_code=405,
                headers={**self.CORS_HEADERS, "Allow": "POST, OPTIONS"},
            )
            await resp(scope, receive, send)
            return

        # 4. Path normalizálás (/mcp/<TOKEN> -> /mcp) + Accept fejléc normalizálás
        #    (hogy `Accept: */*` vagy hiányzó Accept esetén se lógjon/dobjon 406-ot az MCP SDK!)
        new_scope = dict(scope)
        if path_token or str(scope.get("path", "")).rstrip("/") == "/mcp":
            new_scope["path"] = "/mcp"

        orig_headers = list(scope.get("headers") or [])
        filtered_headers = [(k, v) for (k, v) in orig_headers if k.lower() != b"accept"]
        filtered_headers.append((b"accept", b"application/json, text/event-stream"))
        new_scope["headers"] = filtered_headers

        async def _send_with_cors(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                hdrs = list(message.get("headers") or [])
                existing_keys = {k.lower() for k, _ in hdrs}
                for ck, cv in self.CORS_HEADERS.items():
                    if ck.lower().encode("latin-1") not in existing_keys:
                        hdrs.append((ck.lower().encode("latin-1"), cv.encode("latin-1")))
                message = {**message, "headers": hdrs}
            await send(message)

        await self.app(new_scope, receive, _send_with_cors)


def create_otthon_mcp_server(db: Database, settings: Settings) -> tuple[MCPServer, Any]:
    mcp = MCPServer(
        name="kifli-otthon",
        title="Kifli Otthon — Receptek, Heti Menü & Háztartási Lista MCP",
        instructions=(
            "Saját otthoni receptgyűjtemény (reggeli, ebed, vacsora), heti menütervező "
            "és anti-loop háztartási/tisztítószer bevásárlólista kezelő MCP szerver."
        ),
        version="2.0.0",
    )

    @mcp.tool(
        description="Kilistázza az elmentett saját recepteket hozzávalókkal. Opcionális category szűrő: 'reggeli', 'ebed' vagy 'vacsora'."
    )
    def list_recipes(category: str = "") -> list[dict[str, Any]]:
        cat = category.strip().lower() or None
        return db.list_recipes(category=cat)

    @mcp.tool(
        description=(
            "Új recept felvétele VAGY meglévő recept szerkesztése (ha megadod a recipe_id-t). "
            "categories: ['reggeli', 'ebed', 'vacsora'] részhalmaza. "
            "healthy_score: 1 (bűnözős/nehéz) .. 5 (szuper-egészséges), alapból 3. "
            "image_url: opcionális kép URL (vagy használd a set_recipe_image toolt base64/URL képfeltöltéshez). "
            "ingredients: [{'name': 'burgonya', 'quantity': 1.0, 'unit': 'kg', 'is_staple': false, 'brand_hint': ''}]"
        )
    )
    def upsert_recipe(
        title: str,
        categories: list[str],
        ingredients: list[dict[str, Any]],
        servings: int = 2,
        instructions: str = "",
        source_url: str = "",
        recipe_id: int | None = None,
        healthy_score: int = 3,
        image_url: str | None = None,
    ) -> dict[str, Any]:
        return db.create_or_update_recipe(
            title=title,
            categories=categories,
            ingredients=ingredients,
            servings=servings,
            instructions=instructions,
            source_url=source_url,
            recipe_id=recipe_id,
            healthy_score=healthy_score,
            image_url=image_url,
        )

    @mcp.tool(
        description=(
            "Kép feltöltése vagy beállítása egy meglévő recepthez (recipe_id alapján). "
            "Megadhatsz publikus image_url-t (letölti és lokálisan eltárolja a NAS-on!) VAGY közvetlen image_base64 képadatot."
        )
    )
    async def set_recipe_image(
        recipe_id: int,
        image_url: str = "",
        image_base64: str = "",
        mime_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        if image_base64.strip():
            saved_path = save_recipe_image_base64(
                settings.data_dir, image_base64, mime_type=mime_type
            )
            return db.set_recipe_image(recipe_id, saved_path)
        if image_url.strip():
            try:
                saved_path = await download_and_save_recipe_image(
                    settings.data_dir, image_url.strip()
                )
                return db.set_recipe_image(recipe_id, saved_path)
            except Exception:
                # Ha a külső szerver nem engedi letölteni, eltároljuk közvetlen URL-ként
                return db.set_recipe_image(recipe_id, image_url.strip())
        raise ValueError("Adj meg image_url vagy image_base64 értéket!")

    @mcp.tool(
        description="Recept egészségességi pontszámának (healthy_score) beállítása 1 (nehéz/bűnözős) és 5 (nagyon egészséges) között."
    )
    def set_recipe_healthy_score(recipe_id: int, healthy_score: int) -> dict[str, Any]:
        return db.set_recipe_healthy_score(recipe_id, healthy_score)

    @mcp.tool(description="Teljes aktuális heti menü visszaállítása üresre (reset).")
    def reset_weekly_menu() -> dict[str, Any]:
        return db.reset_weekly_plan()

    @mcp.tool(
        description="Lekéri az aktív heti tervező preferenciákat (heti büdzsé Ft, allergén tiltólista, Kifli sajátmárka előnyben, akció/Mentsd meg az ételt, min. Healthy Score)."
    )
    def get_planner_settings() -> dict[str, Any]:
        return db.get_planner_settings()

    @mcp.tool(
        description=(
            "Frissíti a heti tervező preferenciákat: weekly_budget_ft (0=nincs limit), "
            "allergens (pl. ['laktóz', 'glutén']), prefer_private_label (bool), "
            "prefer_discounts_and_save_food (bool), min_healthy_score (1.0..5.0)."
        )
    )
    def update_planner_settings(
        weekly_budget_ft: int | None = None,
        allergens: list[str] | None = None,
        prefer_private_label: bool | None = None,
        prefer_discounts_and_save_food: bool | None = None,
        min_healthy_score: float | None = None,
    ) -> dict[str, Any]:
        return db.update_planner_settings(
            {
                "weekly_budget_ft": weekly_budget_ft,
                "allergens": allergens,
                "prefer_private_label": prefer_private_label,
                "prefer_discounts_and_save_food": prefer_discounts_and_save_food,
                "min_healthy_score": min_healthy_score,
            }
        )

    @mcp.tool(description="Recept végleges törlése ID alapján.")
    def delete_recipe(recipe_id: int) -> dict[str, Any]:
        return {"deleted": db.delete_recipe(recipe_id), "recipe_id": recipe_id}

    @mcp.tool(
        description="Lekéri az aktuális heti menütervet (hetfo..vasarnap, reggeli/ebed/vacsora) és a függő háztartási tételeket."
    )
    def get_weekly_menu() -> dict[str, Any]:
        return {
            "weekly_plan": db.get_weekly_plan(),
            "household_items": db.list_general_items(include_ordered=False),
        }

    @mcp.tool(
        description=(
            "Beállít vagy töröl egy étkezést egyszerre egy vagy több napon! "
            "days: pl. ['hetfo', 'kedd'] (választható: hetfo, kedd, szerda, csutortok, pentek, szombat, vasarnap). "
            "meal_type: 'reggeli' | 'ebed' | 'vacsora'. "
            "Adj meg recipe_id-t (mentett receptből) VAGY custom_title-t, vagy clear=True-t a törléshez."
        )
    )
    def set_weekly_meals(
        days: list[str],
        meal_type: str,
        recipe_id: int | None = None,
        custom_title: str = "",
        clear: bool = False,
    ) -> dict[str, Any]:
        return db.set_weekly_meal_slots_manual(
            day_keys=days,
            meal_type=meal_type,
            recipe_id=recipe_id,
            custom_title=custom_title,
            clear=clear,
        )

    @mcp.tool(
        description=(
            "Teljes heti menüterv mentése egyszerre. "
            "slots elemei: {'day': 'hetfo', 'meal_type': 'ebed', 'title': '...', 'recipe_id': 1, 'is_recommendation': false, 'custom_ingredients': [...]}"
        )
    )
    def save_full_weekly_menu(
        slots: list[dict[str, Any]], recommendation_note: str = ""
    ) -> dict[str, Any]:
        days_struct: dict[str, dict[str, Any]] = {d[0]: {} for d in DAYS_HU}
        for slot in slots:
            dkey = str(slot.get("day", "")).strip().lower()
            mkey = str(slot.get("meal_type", "")).strip().lower()
            if dkey in days_struct:
                days_struct[dkey][mkey] = {
                    "title": slot["title"],
                    "recipe_id": slot.get("recipe_id"),
                    "is_recommendation": bool(slot.get("is_recommendation", False)),
                    "custom_ingredients": slot.get("custom_ingredients") or [],
                }
        return db.save_weekly_plan(days=days_struct, recommendation_note=recommendation_note)

    @mcp.tool(
        description="Egyszeri plusz élelmiszer hozzáadása az aktuális heti bevásárlólistához (pl. '+2 liter tej')."
    )
    def add_extra_weekly_item(
        name: str, quantity: float = 1.0, unit: str = "db", brand_hint: str = ""
    ) -> dict[str, Any]:
        return db.add_adhoc_item_to_week(
            name=name, quantity=quantity, unit=unit, brand_hint=brand_hint
        )

    @mcp.tool(
        description="Kilistázza az Általános / Háztartási (tisztítószer, papírzsepi stb.) egyszeri listát."
    )
    def list_household_items(include_ordered: bool = False) -> list[dict[str, Any]]:
        return db.list_general_items(include_ordered=include_ordered)

    @mcp.tool(
        description="Új tétel felvétele az Általános / Háztartási egyszeri listára (pl. papírzsepi, Domestos) opcionális pontos márkával."
    )
    def add_household_item(
        name: str, quantity: float = 1.0, unit: str = "db", brand_hint: str = ""
    ) -> dict[str, Any]:
        return db.add_general_item(
            name=name, quantity=quantity, unit=unit, brand_hint=brand_hint
        )

    @mcp.tool(
        description="Háztartási tétel törlése ID alapján."
    )
    def delete_household_item(item_id: int) -> dict[str, Any]:
        return {"deleted": db.delete_general_item(item_id), "item_id": item_id}

    @mcp.tool(
        description="Amikor a Kifli rendelés kiment: végleg lezárja/törli a kosárba helyezett (IN_CART) háztartási tételeket, hogy ne loopoljanak a következő héten."
    )
    def confirm_order_and_clear_household_items(include_pending: bool = False) -> dict[str, Any]:
        return db.finalize_order_and_clear_general_items(
            include_pending_if_forced=include_pending
        )

    @mcp.tool(
        description="Visszaadja a teljes heti menü összevont alapanyaglistáját + a függő háztartási tételeket + a kamrában feltételezett alapanyagokat."
    )
    def get_aggregated_shopping_list() -> dict[str, Any]:
        return db.aggregate_shopping_list()

    @mcp.tool(
        description="Kedvenc Kifli termék / márka rögzítése egy alapanyaghoz (pl. 'tej 2,8%' -> Kifli product_id + név)."
    )
    def save_preferred_kifli_product(
        ingredient_name: str, kifli_product_id: str, kifli_product_name: str
    ) -> dict[str, Any]:
        return db.save_product_preference(
            ingredient_name=ingredient_name,
            kifli_product_id=kifli_product_id,
            kifli_product_name=kifli_product_name,
        )

    starlette_mcp = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return mcp, starlette_mcp
