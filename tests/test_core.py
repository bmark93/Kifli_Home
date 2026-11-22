from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.kifli_mcp import KifliMCPManager, sanitize_json_schema_for_llm
from app.main import create_app


def _make_settings(tmp_path: Path, pin: str = "") -> Settings:
    return Settings(
        llm_provider="gemini",
        llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        llm_api_key="test-key",
        llm_model="gemini-2.5-flash",
        kifli_mcp_url="https://mcp.kifli.hu/mcp",
        kifli_oauth_redirect_uri="http://localhost:3334/oauth/callback",
        telegram_bot_token="",
        telegram_allowed_user_ids=(),
        timezone="Europe/Budapest",
        weekly_cron_day="mon",
        weekly_cron_hour=8,
        weekly_cron_minute=0,
        app_access_pin=pin,
        data_dir=tmp_path,
        port=8085,
    )


def test_general_items_anti_loop_lifecycle(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")

    zsepi = db.add_general_item("Papírzsebkendő", quantity=2, unit="csomag", brand_hint="Zewa Deluxe")
    domestos = db.add_general_item("Fertőtlenítő", quantity=1, unit="db", brand_hint="Domestos Pine")

    # Ugyanannak a PENDING tételnek az újbóli felvétele összeadja a mennyiséget
    zsepi_again = db.add_general_item("Papírzsebkendő", quantity=1, unit="csomag", brand_hint="Zewa Deluxe")
    assert zsepi_again["id"] == zsepi["id"]
    assert zsepi_again["quantity"] == 3.0

    # Csak a papírzsepit sikerült kosárba tenni, a Domestos készlethiányos maradt
    db.mark_general_items_in_cart(
        [{"id": zsepi["id"], "kifli_product_id": "991122", "kifli_product_name": "Zewa Deluxe 90db"}]
    )

    agg_before_order = db.aggregate_shopping_list()
    pending_ids = [g["general_item_id"] for g in agg_before_order["general_pending_items"]]
    assert domestos["id"] in pending_ids
    assert zsepi["id"] not in pending_ids
    assert len(agg_before_order["general_already_in_cart"]) == 1

    # Rendelés leadása után a kosárban lévő végleg ORDERED lesz (nem loopol!),
    # a készlethiányos Domestos viszont nem vész el (PENDING marad)
    res = db.finalize_order_and_clear_general_items(kifli_order_id="ORD-1001")
    assert res["cleared_count"] == 1
    assert res["already_processed"] is False

    # Ugyanarra a rendelésazonosítóra idempotens
    dup = db.finalize_order_and_clear_general_items(kifli_order_id="ORD-1001")
    assert dup["already_processed"] is True

    active_after = db.list_general_items(include_ordered=False)
    assert len(active_after) == 1
    assert active_after[0]["id"] == domestos["id"]
    assert active_after[0]["status"] == "PENDING"


def test_weekly_menu_swap_adhoc_aggregation_and_staples(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    recipes = db.list_recipes(category="reggeli")
    zabkasa = next(r for r in recipes if "Zabkása" in r["title"])

    db.save_product_preference("tej 2,8%", "774411", "Magyar ESL Tej 2,8% 1l")

    # Hétfő reggeli: mentett Zabkása (0.4 l tej 2,8%)
    db.update_weekly_meal_slot(
        day_key="hetfo",
        meal_type="reggeli",
        title=zabkasa["title"],
        recipe_id=zabkasa["id"],
    )

    # Kedd ebéd: menet közben megkívánt Krumplifőzelék (nincs mentett receptként)
    db.update_weekly_meal_slot(
        day_key="kedd",
        meal_type="ebed",
        title="Krumplifőzelék",
        custom_ingredients=[
            {"name": "burgonya", "quantity": 1.0, "unit": "kg", "is_staple": False},
            {"name": "babérlevél", "quantity": 2, "unit": "db", "is_staple": True},
        ],
    )

    # Menet közben kért "+2 l tej 2,8%"
    db.add_adhoc_item_to_week("tej 2,8%", quantity=2.0, unit="l")

    agg = db.aggregate_shopping_list()
    items_by_name = {i["name"].lower(): i for i in agg["recipe_and_adhoc_items"]}

    # 0.4 l + 2.0 l = 2.4 l összevonva + kedvenc Kifli termék hozzárendelve!
    assert items_by_name["tej 2,8%"]["quantity"] == 2.4
    assert items_by_name["tej 2,8%"]["preferred_kifli_product"]["id"] == "774411"
    assert items_by_name["burgonya"]["quantity"] == 1.0

    # A babérlevél kamra-alapanyag, ezért nem kerül a kosár-tételek közé
    assert "babérlevél" not in items_by_name
    assert "babérlevél" in agg["staples_assumed_at_home"]


def test_schema_sanitizer_and_checkout_guard(tmp_path: Path) -> None:
    raw_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"Item": {"type": "object", "additionalProperties": False, "properties": {"id": {"type": "string"}}}},
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": ""},
            "item": {"$ref": "#/$defs/Item"},
        },
    }
    cleaned = sanitize_json_schema_for_llm(raw_schema)
    assert "$schema" not in cleaned
    assert "$defs" not in cleaned
    assert "additionalProperties" not in cleaned
    assert cleaned["properties"]["query"]["type"] == "string"
    assert cleaned["properties"]["item"]["properties"]["id"]["type"] == "string"

    mgr = KifliMCPManager("https://mcp.kifli.hu/mcp", "http://localhost:3334/oauth/callback", tmp_path / "oauth")

    class DummyTool:
        def __init__(self, name: str) -> None:
            self.name = name
            self.description = name
            self.inputSchema = {"type": "object"}

    converted = mgr._convert_tools([DummyTool("search_products"), DummyTool("submit_order_checkout")])
    names = [t["mcp_name"] for t in converted]
    assert "search_products" in names
    assert "submit_order_checkout" not in names


def test_fastapi_endpoints_and_pin_protection(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, pin="4321")
    app = create_app(custom_settings=settings, enable_background=False)
    client = TestClient(app)

    # Health végpont nyitott a Docker healthcheck számára
    assert client.get("/api/health").status_code == 200

    # PIN nélkül 401
    assert client.get("/api/status").status_code == 401

    headers = {"X-App-Pin": "4321"}
    st = client.get("/api/status", headers=headers)
    assert st.status_code == 200
    assert st.json()["llm_model"] == "gemini-2.5-flash"

    # Általános tétel felvétele és lekérése API-n keresztül
    created = client.post(
        "/api/general-items",
        headers=headers,
        json={"name": "Papírtörlő", "quantity": 1, "unit": "csomag", "brand_hint": "Regina"},
    )
    assert created.status_code == 200
    items = client.get("/api/general-items", headers=headers).json()
    assert len(items) == 1
    assert items[0]["brand_hint"] == "Regina"


def test_recipe_editing_and_zero_token_manual_slot_swap(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    app = create_app(custom_settings=settings, enable_background=False)
    client = TestClient(app)

    # 1. Új recept felvétele, majd szerkesztése (PUT /api/recipes/{id})
    created = client.post(
        "/api/recipes",
        json={
            "title": "Paprikás krumpli",
            "categories": ["ebed"],
            "servings": 2,
            "ingredients": [{"name": "burgonya", "quantity": 0.8, "unit": "kg"}],
        },
    ).json()
    rid = created["id"]

    updated = client.put(
        f"/api/recipes/{rid}",
        json={
            "title": "Paprikás krumpli kolbásszal",
            "categories": ["ebed", "vacsora"],
            "servings": 4,
            "ingredients": [
                {"name": "burgonya", "quantity": 1.5, "unit": "kg"},
                {"name": "füstölt kolbász", "quantity": 200, "unit": "g", "brand_hint": "Gyulai"},
            ],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Paprikás krumpli kolbásszal"

    # 2. 0 AI-tokenes kézi csere egyszerre Hétfő + Kedd ebédre (PUT /api/weekly-plan/slot)
    swap_res = client.put(
        "/api/weekly-plan/slot",
        json={"days": ["hetfo", "kedd"], "meal_type": "ebed", "recipe_id": rid},
    )
    assert swap_res.status_code == 200
    body = swap_res.json()
    assert body["plan"]["days"]["hetfo"]["ebed"]["title"] == "Paprikás krumpli kolbásszal"
    assert body["plan"]["days"]["kedd"]["ebed"]["title"] == "Paprikás krumpli kolbásszal"

    # Összesített bevásárlólista 2 napra duplázza a szerkesztett mennyiségeket (2 x 1.5 kg = 3.0 kg)
    agg_by_name = {
        i["name"]: i for i in body["aggregated_shopping"]["recipe_and_adhoc_items"]
    }
    assert agg_by_name["burgonya"]["quantity"] == 3.0
    assert agg_by_name["füstölt kolbász"]["quantity"] == 400.0
    assert agg_by_name["füstölt kolbász"]["brand_hint"] == "Gyulai"

    # 3. Étkezés törlése/kihagyása Kedd ebédről
    cleared = client.put(
        "/api/weekly-plan/slot",
        json={"days": ["kedd"], "meal_type": "ebed", "clear": True},
    ).json()
    assert "ebed" not in cleared["plan"]["days"]["kedd"]
    agg_after = {
        i["name"]: i for i in cleared["aggregated_shopping"]["recipe_and_adhoc_items"]
    }
    assert agg_after["burgonya"]["quantity"] == 1.5


def test_otthon_mcp_server_tools(tmp_path: Path) -> None:
    import asyncio

    settings = _make_settings(tmp_path)
    app = create_app(custom_settings=settings, enable_background=False)
    mcp_srv = app.state.otthon_mcp

    async def _run() -> None:
        tools = await mcp_srv.list_tools()
        tool_names = {t.name for t in tools}
        assert "list_recipes" in tool_names
        assert "upsert_recipe" in tool_names
        assert "set_weekly_meals" in tool_names
        assert "add_household_item" in tool_names

        res = await mcp_srv.call_tool(
            "upsert_recipe",
            {
                "title": "Finomfőzelék",
                "categories": ["ebed"],
                "servings": 2,
                "ingredients": [
                    {"name": "zöldborsó", "quantity": 300, "unit": "g"},
                    {"name": "sárgarépa", "quantity": 200, "unit": "g"},
                ],
            },
        )
        assert res

    asyncio.run(_run())
    saved_titles = [r["title"] for r in app.state.db.list_recipes()]
    assert "Finomfőzelék" in saved_titles
