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


class OptionalPinASGIWrapper:
    """
    Ha a .env-ben be van állítva APP_ACCESS_PIN, akkor az /mcp (és /mcp/<PIN>) végpont megköveteli:
    - path paraméterként: /mcp/<PIN>  (ajánlott Claude Remote MCP / mobil appokhoz!)
    - VAGY Authorization: Bearer <PIN>
    - VAGY X-App-Pin: <PIN>
    - VAGY ?pin=<PIN>
    Ha nincs APP_ACCESS_PIN (pl. zárt Tailscale/LAN hálózaton), szabadon hívható.
    """

    def __init__(self, app: ASGIApp, expected_pin: str) -> None:
        self.app = app
        self.expected_pin = expected_pin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path_params = scope.get("path_params") or {}
            path_pin = str(path_params.get("pin", "")).strip("/")

            if self.expected_pin:
                req = Request(scope)
                auth_hdr = req.headers.get("authorization", "")
                bearer = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
                supplied = (
                    path_pin
                    or bearer
                    or req.headers.get("x-app-pin", "").strip()
                    or req.query_params.get("pin", "").strip()
                )
                if not supplied or not hmac.compare_digest(supplied, self.expected_pin):
                    resp = JSONResponse(
                        {"error": "Unauthorized: missing or invalid APP_ACCESS_PIN"}, status_code=401
                    )
                    await resp(scope, receive, send)
                    return

            # Ha /mcp/<PIN> útvonalon jött, normalizáljuk /mcp-re a belső MCP handler számára
            if path_pin:
                scope = dict(scope)
                scope["path"] = "/mcp"

        await self.app(scope, receive, send)


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
    ) -> dict[str, Any]:
        return db.create_or_update_recipe(
            title=title,
            categories=categories,
            ingredients=ingredients,
            servings=servings,
            instructions=instructions,
            source_url=source_url,
            recipe_id=recipe_id,
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
