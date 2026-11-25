from __future__ import annotations

import contextvars
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

CURRENT_MCP_USER_ID: contextvars.ContextVar[int] = contextvars.ContextVar(
    "current_mcp_user_id", default=1
)


class OptionalPinASGIWrapper:
    """
    Claude Remote MCP & Streamable HTTP kompatibilitási + Multi-User biztonsági réteg:
    1. Token feloldása (path: /mcp/<TOKEN>, Bearer, X-App-Pin vagy ?pin=):
       - Ha egyezik egy regisztrált felhasználó személyes `mcp_token`-jével -> az ő `user_id`-ja!
       - Ha egyezik a globális `MCP_ACCESS_TOKEN`-nel -> `user_id = 1`.
       - Ha sem globális token nincs, sem AUTH_REQUIRED -> `user_id = 1`.
    2. OPTIONS (CORS preflight) -> azonnali 204 No Content.
    3. GET / DELETE -> azonnali 405 Method Not Allowed (nincs lógó üres SSE stream).
    4. POST Accept fejléc normalizálás -> azonnali 200 OK application/json válasz.
    """

    CORS_HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Accept, Authorization, X-App-Pin, Mcp-Session-Id, MCP-Protocol-Version",
        "Access-Control-Expose-Headers": "Mcp-Session-Id",
    }

    def __init__(
        self,
        app: ASGIApp,
        expected_token: str,
        db: Database | None = None,
        require_token_always: bool = False,
    ) -> None:
        self.app = app
        self.expected_token = expected_token
        self.db = db
        self.require_token_always = require_token_always

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()

        if method == "OPTIONS":
            resp = JSONResponse({}, status_code=204, headers=self.CORS_HEADERS)
            await resp(scope, receive, send)
            return

        path_params = scope.get("path_params") or {}
        path_token = str(path_params.get("pin", "")).strip("/")

        req = Request(scope)
        auth_hdr = req.headers.get("authorization", "")
        bearer = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
        supplied = (
            path_token
            or bearer
            or req.headers.get("x-app-pin", "").strip()
            or req.query_params.get("pin", "").strip()
        )

        resolved_user_id: int | None = None
        if supplied and self.db is not None:
            user = self.db.get_user_by_mcp_token(supplied)
            if user:
                resolved_user_id = int(user["id"])

        if resolved_user_id is None and self.expected_token:
            if supplied and hmac.compare_digest(supplied, self.expected_token):
                resolved_user_id = 1

        if resolved_user_id is None:
            if self.expected_token or self.require_token_always:
                resp = JSONResponse(
                    {"error": "Unauthorized: missing or invalid MCP_ACCESS_TOKEN"},
                    status_code=401,
                    headers=self.CORS_HEADERS,
                )
                await resp(scope, receive, send)
                return
            resolved_user_id = 1

        if method in ("GET", "DELETE", "HEAD"):
            resp = JSONResponse(
                {"error": "Method Not Allowed: use POST for stateless MCP Streamable HTTP"},
                status_code=405,
                headers={**self.CORS_HEADERS, "Allow": "POST, OPTIONS"},
            )
            await resp(scope, receive, send)
            return

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

        token_ctx = CURRENT_MCP_USER_ID.set(resolved_user_id)
        try:
            await self.app(new_scope, receive, _send_with_cors)
        finally:
            CURRENT_MCP_USER_ID.reset(token_ctx)


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

    def _uid() -> int:
        return CURRENT_MCP_USER_ID.get()

    @mcp.tool(
        description="Kilistázza az elmentett saját recepteket hozzávalókkal. Opcionális category szűrő: 'reggeli', 'ebed' vagy 'vacsora'."
    )
    def list_recipes(category: str = "") -> list[dict[str, Any]]:
        cat = category.strip().lower() or None
        return db.list_recipes(category=cat, user_id=_uid())

    @mcp.tool(
        description=(
            "Új recept felvétele VAGY meglévő recept szerkesztése (ha megadod a recipe_id-t). "
            "categories: ['reggeli', 'ebed', 'vacsora'] részhalmaza. "
            "healthy_score: 1..5, opcionálisan megadható kcal_per_serving, protein_g, carbs_g, fat_g (1 adagra) és image_url. "
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
        kcal_per_serving: int | None = None,
        protein_g: float | None = None,
        carbs_g: float | None = None,
        fat_g: float | None = None,
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
            kcal_per_serving=kcal_per_serving,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            user_id=_uid(),
        )

    @mcp.tool(
        description="Recept 1 adagra jutó kalóriájának és makróinak (kcal_per_serving, protein_g, carbs_g, fat_g) beállítása."
    )
    def set_recipe_macros(
        recipe_id: int,
        kcal_per_serving: int,
        protein_g: float,
        carbs_g: float,
        fat_g: float,
    ) -> dict[str, Any]:
        return db.set_recipe_macros(
            recipe_id=recipe_id,
            kcal_per_serving=kcal_per_serving,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            user_id=_uid(),
        )

    @mcp.tool(
        description=(
            "Kép feltöltése vagy beállítása egy meglévő recepthez (recipe_id alapján). "
            "Megadhatsz publikus image_url-t (letölti és lokálisan eltárolja) VAGY közvetlen image_base64 képadatot."
        )
    )
    async def set_recipe_image(
        recipe_id: int,
        image_url: str = "",
        image_base64: str = "",
        mime_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        uid = _uid()
        if image_base64.strip():
            saved_path = save_recipe_image_base64(
                settings.data_dir, image_base64, mime_type=mime_type
            )
            return db.set_recipe_image(recipe_id, saved_path, user_id=uid)
        if image_url.strip():
            try:
                saved_path = await download_and_save_recipe_image(
                    settings.data_dir, image_url.strip()
                )
                return db.set_recipe_image(recipe_id, saved_path, user_id=uid)
            except Exception:
                return db.set_recipe_image(recipe_id, image_url.strip(), user_id=uid)
        raise ValueError("Adj meg image_url vagy image_base64 értéket!")

    @mcp.tool(
        description="Recept egészségességi pontszámának (healthy_score) beállítása 1 (nehéz/bűnözős) és 5 (nagyon egészséges) között."
    )
    def set_recipe_healthy_score(recipe_id: int, healthy_score: int) -> dict[str, Any]:
        return db.set_recipe_healthy_score(recipe_id, healthy_score, user_id=_uid())

    @mcp.tool(description="Teljes aktuális heti menü visszaállítása üresre (reset).")
    def reset_weekly_menu() -> dict[str, Any]:
        return db.reset_weekly_plan(user_id=_uid())

    @mcp.tool(
        description="Lekéri az aktív heti tervező preferenciákat (heti büdzsé Ft, allergén tiltólista, Kifli sajátmárka előnyben, akció/Mentsd meg az ételt, min. Healthy Score)."
    )
    def get_planner_settings() -> dict[str, Any]:
        return db.get_planner_settings(user_id=_uid())

    @mcp.tool(
        description=(
            "Frissíti a heti tervező preferenciákat: household_size (1..12 fő), plan_days (1..7 nap), "
            "days_per_meal (1..4 napig ugyanaz a főtt étel), weekly_budget_ft (0=nincs limit), "
            "allergens (pl. ['laktóz', 'glutén']), prefer_private_label (bool), "
            "prefer_discounts_and_save_food (bool), min_healthy_score (1.0..5.0), "
            "ai_recommendations_enabled (bool), ai_recommendation_count (1..7), "
            "ai_recommendation_meals (['reggeli', 'ebed', 'vacsora'])."
        )
    )
    def update_planner_settings(
        household_size: int | None = None,
        plan_days: int | None = None,
        days_per_meal: int | None = None,
        weekly_budget_ft: int | None = None,
        allergens: list[str] | None = None,
        prefer_private_label: bool | None = None,
        prefer_discounts_and_save_food: bool | None = None,
        min_healthy_score: float | None = None,
        ai_recommendations_enabled: bool | None = None,
        ai_recommendation_count: int | None = None,
        ai_recommendation_meals: list[str] | None = None,
    ) -> dict[str, Any]:
        return db.update_planner_settings(
            {
                "household_size": household_size,
                "plan_days": plan_days,
                "days_per_meal": days_per_meal,
                "weekly_budget_ft": weekly_budget_ft,
                "allergens": allergens,
                "prefer_private_label": prefer_private_label,
                "prefer_discounts_and_save_food": prefer_discounts_and_save_food,
                "min_healthy_score": min_healthy_score,
                "ai_recommendations_enabled": ai_recommendations_enabled,
                "ai_recommendation_count": ai_recommendation_count,
                "ai_recommendation_meals": ai_recommendation_meals,
            },
            user_id=_uid(),
        )

    @mcp.tool(description="Recept végleges törlése ID alapján.")
    def delete_recipe(recipe_id: int) -> dict[str, Any]:
        return {"deleted": db.delete_recipe(recipe_id, user_id=_uid()), "recipe_id": recipe_id}

    @mcp.tool(
        description="Lekéri az aktuális heti menütervet (hetfo..vasarnap, reggeli/ebed/vacsora) és a függő háztartási tételeket."
    )
    def get_weekly_menu() -> dict[str, Any]:
        uid = _uid()
        return {
            "weekly_plan": db.get_weekly_plan(user_id=uid),
            "household_items": db.list_general_items(include_ordered=False, user_id=uid),
        }

    @mcp.tool(
        description=(
            "Beállít vagy töröl egy étkezést egyszerre egy vagy több napon! "
            "days: pl. ['hetfo', 'kedd']. meal_type: 'reggeli' | 'ebed' | 'vacsora'."
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
            user_id=_uid(),
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
        return db.save_weekly_plan(
            days=days_struct, recommendation_note=recommendation_note, user_id=_uid()
        )

    @mcp.tool(
        description="Egyszeri plusz élelmiszer hozzáadása az aktuális heti bevásárlólistához (pl. '+2 liter tej')."
    )
    def add_extra_weekly_item(
        name: str, quantity: float = 1.0, unit: str = "db", brand_hint: str = ""
    ) -> dict[str, Any]:
        return db.add_adhoc_item_to_week(
            name=name, quantity=quantity, unit=unit, brand_hint=brand_hint, user_id=_uid()
        )

    @mcp.tool(
        description="Kilistázza az Általános / Háztartási (tisztítószer, papírzsepi stb.) egyszeri listát."
    )
    def list_household_items(include_ordered: bool = False) -> list[dict[str, Any]]:
        return db.list_general_items(include_ordered=include_ordered, user_id=_uid())

    @mcp.tool(
        description="Új tétel felvétele az Általános / Háztartási egyszeri listára (pl. papírzsepi, Domestos) opcionális pontos márkával."
    )
    def add_household_item(
        name: str, quantity: float = 1.0, unit: str = "db", brand_hint: str = ""
    ) -> dict[str, Any]:
        return db.add_general_item(
            name=name, quantity=quantity, unit=unit, brand_hint=brand_hint, user_id=_uid()
        )

    @mcp.tool(description="Háztartási tétel törlése ID alapján.")
    def delete_household_item(item_id: int) -> dict[str, Any]:
        return {"deleted": db.delete_general_item(item_id, user_id=_uid()), "item_id": item_id}

    @mcp.tool(
        description="Amikor a Kifli rendelés kiment: végleg lezárja/törli a kosárba helyezett (IN_CART) háztartási tételeket."
    )
    def confirm_order_and_clear_household_items(include_pending: bool = False) -> dict[str, Any]:
        return db.finalize_order_and_clear_general_items(
            include_pending_if_forced=include_pending, user_id=_uid()
        )

    @mcp.tool(
        description="Visszaadja a teljes heti menü összevont alapanyaglistáját + a függő háztartási tételeket + a kamrában feltételezett alapanyagokat."
    )
    def get_aggregated_shopping_list() -> dict[str, Any]:
        return db.aggregate_shopping_list(user_id=_uid())

    @mcp.tool(
        description="Kedvenc Kifli termék / márka rögzítése egy alapanyaghoz."
    )
    def save_preferred_kifli_product(
        ingredient_name: str, kifli_product_id: str, kifli_product_name: str
    ) -> dict[str, Any]:
        return db.save_product_preference(
            ingredient_name=ingredient_name,
            kifli_product_id=kifli_product_id,
            kifli_product_name=kifli_product_name,
            user_id=_uid(),
        )

    starlette_mcp = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return mcp, starlette_mcp
