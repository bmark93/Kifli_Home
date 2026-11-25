from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.kifli_mcp import KifliMCPManager, sanitize_json_schema_for_llm
from app.main import create_app


def _make_settings(
    tmp_path: Path,
    pin: str = "",
    mcp_token: str = "",
    auth_required: bool = False,
    invite_code: str = "",
    google_client_id: str = "",
    google_client_secret: str = "",
) -> Settings:
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
        mcp_access_token=mcp_token or pin,
        app_secret_key="unit-test-secret-key",
        invite_code=invite_code,
        demo_mode_enabled=True,
        demo_daily_ai_limit=3,
        server_fallback_daily_ai_limit=5,
        auth_required=auth_required,
        google_client_id=google_client_id,
        google_client_secret=google_client_secret,
        google_redirect_uri="",
        allowed_google_emails=(),
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

    # 4 adagos recept Hétfő + Kedd egymást követő ebédre = 1 főzés (NEM duplázza 3.0 kg-ra!)
    agg_by_name = {
        i["name"]: i for i in body["aggregated_shopping"]["recipe_and_adhoc_items"]
    }
    assert agg_by_name["burgonya"]["quantity"] == 1.5
    assert agg_by_name["füstölt kolbász"]["quantity"] == 200.0
    assert agg_by_name["füstölt kolbász"]["brand_hint"] == "Gyulai"

    # 3. Étkezés törlése/kihagyása Kedd ebédről (Hétfő továbbra is 1 főzés marad)
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

    # Teljes Claude.ai Remote MCP handshake + szétválasztott MCP_ACCESS_TOKEN vs APP_ACCESS_PIN teszt
    # Csak MCP_ACCESS_TOKEN van beállítva, APP_ACCESS_PIN üres -> belső Web UI NEM kér PIN-t!
    mcp_only_settings = _make_settings(tmp_path, pin="", mcp_token="SecretToken999")
    mcp_only_app = create_app(custom_settings=mcp_only_settings, enable_background=False)
    with TestClient(mcp_only_app) as client:
        # 1. Belső Web UI szabadon elérhető PIN popup nélkül
        assert client.get("/api/status").status_code == 200

        # 2. Publikus /mcp token nélkül 401
        r_unauth = client.post(
            "/mcp",
            headers={"Accept": "*/*"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert r_unauth.status_code == 401

        # 3. GET és DELETE azonnali 405 (soha nem lóg üres SSE streamen!)
        assert client.get("/mcp/SecretToken999").status_code == 405
        assert client.delete("/mcp/SecretToken999").status_code == 405
        assert client.options("/mcp/SecretToken999").status_code == 204

        # 4. POST initialize akár `Accept: */*` fejléccel is azonnali 200 OK application/json!
        r_init = client.post(
            "/mcp/SecretToken999",
            headers={"Accept": "*/*"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "claude-ai", "version": "0.1.0"},
                },
            },
        )
        assert r_init.status_code == 200
        assert "application/json" in r_init.headers.get("content-type", "")
        assert r_init.json()["result"]["serverInfo"]["name"] == "kifli-otthon"

        # 5. POST tools/list -> 19 tool JSON-ban (új: set_recipe_macros)
        r_tools = client.post(
            "/mcp/SecretToken999",
            headers={"Accept": "application/json"},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert r_tools.status_code == 200
        assert len(r_tools.json()["result"]["tools"]) == 19


def test_recipe_image_healthy_score_and_weekly_reset(tmp_path: Path) -> None:
    import asyncio
    import base64

    settings = _make_settings(tmp_path)
    app = create_app(custom_settings=settings, enable_background=False)

    # Minimális 1x1 PNG bájtban
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

    with TestClient(app) as client:
        # 1. Recept felvétel healthy_score=5-tel
        rec = client.post(
            "/api/recipes",
            json={
                "title": "Avokádós pirítós",
                "categories": ["reggeli"],
                "servings": 2,
                "healthy_score": 5,
                "ingredients": [{"name": "avokádó", "quantity": 1, "unit": "db"}],
            },
        ).json()
        rid = rec["id"]
        assert rec["healthy_score"] == 5

        # 2. Képfeltöltés REST API-n keresztül (multipart) + visszatöltés /uploads alól
        up = client.post(
            f"/api/recipes/{rid}/image",
            files={"file": ("avo.png", tiny_png, "image/png")},
        )
        assert up.status_code == 200
        img_url = up.json()["image_url"]
        assert img_url.startswith("/uploads/recipes/")
        assert client.get(img_url).status_code == 200

        # 3. MCP set_recipe_healthy_score + set_recipe_macros + set_recipe_image (base64)
        async def _mcp_updates() -> None:
            mcp_srv = app.state.otthon_mcp
            await mcp_srv.call_tool("set_recipe_healthy_score", {"recipe_id": rid, "healthy_score": 4})
            await mcp_srv.call_tool(
                "set_recipe_macros",
                {
                    "recipe_id": rid,
                    "kcal_per_serving": 410,
                    "protein_g": 14.5,
                    "carbs_g": 32.0,
                    "fat_g": 24.0,
                },
            )
            await mcp_srv.call_tool(
                "set_recipe_image",
                {
                    "recipe_id": rid,
                    "image_base64": base64.b64encode(tiny_png).decode("ascii"),
                    "mime_type": "image/png",
                },
            )

        asyncio.run(_mcp_updates())
        updated_rec = [r for r in app.state.db.list_recipes() if r["id"] == rid][0]
        assert updated_rec["healthy_score"] == 4
        assert updated_rec["kcal_per_serving"] == 410
        assert updated_rec["protein_g"] == 14.5
        assert updated_rec["carbs_g"] == 32.0
        assert updated_rec["fat_g"] == 24.0
        assert updated_rec["image_url"].startswith("/uploads/recipes/")

        # 4. Heti menü beállítása, majd RESET 0 AI tokennel
        client.put(
            "/api/weekly-plan/slot",
            json={"days": ["hetfo", "kedd"], "meal_type": "reggeli", "recipe_id": rid},
        )
        assert app.state.db.get_weekly_plan()["days"]["hetfo"]["reggeli"]["title"] == "Avokádós pirítós"

        reset_resp = client.post("/api/weekly-plan/reset")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["plan"]["days"]["hetfo"] == {}
        assert reset_resp.json()["aggregated_shopping"]["recipe_and_adhoc_items"] == []


def test_couple_tinder_match_planner_settings_and_smart_restock(tmp_path: Path) -> None:
    import datetime as dt
    from app.smart_restock import compute_restock_predictions_from_events

    settings = _make_settings(tmp_path)
    app = create_app(custom_settings=settings, enable_background=False)

    with TestClient(app) as client:
        # 1. Planner Settings mentés & visszaolvasás (fő, nap, 1 kaja hány napig, AI ajánlás)
        upd = client.put(
            "/api/planner-settings",
            json={
                "household_size": 4,
                "plan_days": 5,
                "days_per_meal": 3,
                "weekly_budget_ft": 42000,
                "allergens": ["laktóz", "glutén"],
                "prefer_private_label": True,
                "prefer_discounts_and_save_food": True,
                "min_healthy_score": 4.0,
                "ai_recommendations_enabled": False,
                "ai_recommendation_count": 3,
                "ai_recommendation_meals": ["reggeli", "vacsora"],
            },
        )
        assert upd.status_code == 200
        ps = client.get("/api/planner-settings").json()
        assert ps["household_size"] == 4
        assert ps["plan_days"] == 5
        assert ps["days_per_meal"] == 3
        assert ps["weekly_budget_ft"] == 42000
        assert ps["allergens"] == ["laktóz", "glutén"]
        assert ps["min_healthy_score"] == 4.0
        assert ps["ai_recommendations_enabled"] is False
        assert ps["ai_recommendation_count"] == 3
        assert ps["ai_recommendation_meals"] == ["reggeli", "vacsora"]

        # 2. Páros Kaja Tinder Match szoba (p1 + p2 -> IT'S A MATCH!)
        recipes = client.get("/api/recipes?category=ebed").json()
        r1_id, r2_id = recipes[0]["id"], recipes[1]["id"]

        sess = client.post(
            "/api/tinder/sessions",
            json={"meal_type": "ebed", "target_days": ["hetfo", "kedd"]},
        ).json()
        code = sess["code"]
        assert len(code) == 4

        s1 = client.post(
            f"/api/tinder/sessions/{code}/swipe",
            json={"user_slot": "p1", "recipe_id": r1_id, "decision": "like"},
        ).json()
        assert s1["is_match"] is False

        s2 = client.post(
            f"/api/tinder/sessions/{code}/swipe",
            json={"user_slot": "p2", "recipe_id": r2_id, "decision": "pass"},
        ).json()
        assert s2["is_match"] is False

        s3 = client.post(
            f"/api/tinder/sessions/{code}/swipe",
            json={"user_slot": "p2", "recipe_id": r1_id, "decision": "like"},
        ).json()
        assert s3["is_match"] is True
        assert s3["matched_recipe"]["id"] == r1_id
        assert len(s3["session"]["matches"]) == 1
        assert len(s3["session"]["deck_recipes"]) >= 2

        # Közös kedvenc elfogadása /accept végponttal
        acc = client.post(
            f"/api/tinder/sessions/{code}/accept",
            json={"days": ["hetfo", "kedd"], "meal_type": "ebed", "recipe_id": r1_id},
        )
        assert acc.status_code == 200
        assert acc.json()["plan"]["days"]["hetfo"]["ebed"]["recipe_id"] == r1_id

    # 3. Smart Restock fogyás-előrejelző determinisztikus teszt
    now = dt.datetime(2026, 11, 25, 10, 0, tzinfo=dt.timezone.utc)
    events = [
        {"name": "Zewa papírzsebkendő", "ordered_at": "2026-10-15T10:00:00Z", "kifli_product_id": "97249"},
        {"name": "Zewa papírzsebkendő", "ordered_at": "2026-11-04T10:00:00Z", "kifli_product_id": "97249"},
        {"name": "Már listán lévő WC papír", "ordered_at": "2026-10-10T10:00:00Z", "kifli_product_id": "115386"},
        {"name": "Már listán lévő WC papír", "ordered_at": "2026-10-28T10:00:00Z", "kifli_product_id": "115386"},
    ]
    preds = compute_restock_predictions_from_events(
        events,
        active_general_keys={"már listán lévő wc papír"},
        now=now,
    )
    assert len(preds) == 1
    assert preds[0]["name"] == "Zewa papírzsebkendő"
    assert preds[0]["urgency"] == "overdue"
    assert preds[0]["avg_interval_days"] == 20.0


def test_private_label_auto_vs_favorite_split(tmp_path: Path) -> None:
    from app.private_label import (
        extract_favorite_product_ids,
        is_kifli_private_label,
        split_auto_vs_favorite_swaps,
    )

    assert is_kifli_private_label("Miil ESL Tej 2,8%", "Miil") is True
    assert is_kifli_private_label("Magyar Tej ESL 2,8%", "Magyar Tej") is False

    db = Database(tmp_path / "pl.db")
    db.save_product_preference("tej", "16321", "Magyar Tej ESL Tej 2,8%")

    fav_ids, fav_labels = extract_favorite_product_ids(
        db, '{"data": [{"productId": 97249, "productName": "Zewa Deluxe"}]}'
    )
    assert 16321 in fav_ids
    assert 97249 in fav_ids

    candidates = [
        {
            "old_product_id": 16321,
            "old_name": "Magyar Tej ESL Tej 2,8%",
            "new_product_id": 97506,
            "new_name": "Miil ESL tej",
            "savings_ft": 180,
        },
        {
            "old_product_id": 55555,
            "old_name": "Drága tészta 500g",
            "new_product_id": 88888,
            "new_name": "Kitchin spagetti 500g",
            "savings_ft": 350,
        },
        {
            "old_product_id": 97249,
            "old_name": "Zewa Deluxe",
            "new_product_id": 105944,
            "new_name": "Moddia papírzsebkendő",
            "savings_ft": 290,
        },
    ]
    auto_swaps, fav_proposals = split_auto_vs_favorite_swaps(candidates, fav_ids, fav_labels)
    assert [a["old_product_id"] for a in auto_swaps] == [55555]
    assert {f["old_product_id"] for f in fav_proposals} == {16321, 97249}


def test_lactose_and_gluten_diet_substitution_in_shopping_list(tmp_path: Path) -> None:
    db = Database(tmp_path / "diet.db")
    db.update_planner_settings({"allergens": ["laktóz", "glutén"]})

    # Kedvenc sima (laktózos) tej ne kerüljön erőltetésre laktózmentes módban!
    db.save_product_preference("tej 2,8%", "16321", "Magyar Tej ESL Tej 2,8%")

    recipes = db.list_recipes()
    zabkasa = next(r for r in recipes if "Zabkása" in r["title"])
    paprikas = next(r for r in recipes if "Csirkepaprikás" in r["title"])

    # Hétfő + Kedd reggeli (2 adag -> 2x), Hétfő + Kedd ebéd (4 adag -> 1x főzés!)
    db.set_weekly_meal_slots_manual(["hetfo", "kedd"], "reggeli", recipe_id=zabkasa["id"])
    db.set_weekly_meal_slots_manual(["hetfo", "kedd"], "ebed", recipe_id=paprikas["id"])

    agg = db.aggregate_shopping_list()
    by_name = {i["name"].lower(): i for i in agg["recipe_and_adhoc_items"]}

    # Mind a tej, mind a tejföl bent marad, laktózmentes címkével + search_hint-tel!
    assert "tej 2,8%" in by_name
    assert by_name["tej 2,8%"]["diet_tags"] == ["laktózmentes"]
    assert by_name["tej 2,8%"]["search_hint"] == "laktózmentes tej 2,8%"
    assert by_name["tej 2,8%"]["preferred_kifli_product"] is None  # nem erőlteti a laktózos kedvencet
    assert by_name["tej 2,8%"]["quantity"] == 0.8  # 2 nap * 0.4 l (mert 2 adagos reggeli)

    assert "tejföl 20%" in by_name
    assert by_name["tejföl 20%"]["diet_tags"] == ["laktózmentes"]
    assert by_name["tejföl 20%"]["search_hint"] == "laktózmentes tejföl 20%"
    assert by_name["tejföl 20%"]["quantity"] == 330.0  # 1 főzés 2 napra (mert 4 adagos ebéd!)

    # Nokedli gluténmentes címkét kap
    assert by_name["friss nokedli"]["diet_tags"] == ["gluténmentes"]


def test_multi_user_auth_isolation_byok_and_demo_sandbox(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, auth_required=True, invite_code="KIFLI2026")
    app = create_app(custom_settings=settings, enable_background=False)

    # Egyetlen TestClient lifespan, user-váltások között cookies.clear()-rel
    with TestClient(app) as client:
        # 1. Bejelentkezés nélkül 401
        assert client.get("/api/recipes").status_code == 401
        cfg = client.get("/api/auth/config").json()
        assert cfg["auth_required"] is True
        assert cfg["demo_mode_enabled"] is True

        # 2. Első user (tulajdonos) regisztráció meghívókód nélkül -> id=1 admin
        r1 = client.post(
            "/api/auth/register",
            json={
                "email": "mark@example.com",
                "password": "StrongPassword123",
                "display_name": "Márk",
            },
        )
        assert r1.status_code == 200
        u1 = r1.json()
        assert u1["id"] == 1
        assert u1["is_admin"] is True

        # Saját recept felvétele user 1-hez
        client.post(
            "/api/recipes",
            json={
                "title": "Márk Titkos Rakott Krumplija",
                "categories": ["ebed"],
                "ingredients": [{"name": "burgonya", "quantity": 1, "unit": "kg"}],
            },
        )

        # Saját BYOK AI kulcs mentése titkosítva (maszkolva jön vissza!)
        byok = client.put(
            "/api/auth/llm-settings",
            json={
                "llm_provider": "openai",
                "llm_model": "gpt-4.1-mini",
                "llm_api_key": "sk-proj-TestSecretKey9876",
            },
        )
        assert byok.status_code == 200
        assert byok.json()["llm"]["using_own_key"] is True
        assert "TestSecretKey" not in byok.json()["llm"]["masked_api_key"]

        # 3. Második user rossz meghívókóddal 403, jó kóddal 200 — és NEM látja Márk receptjét!
        client.cookies.clear()
        bad = client.post(
            "/api/auth/register",
            json={
                "email": "haver@example.com",
                "password": "OtherPassword123",
                "invite_code": "ROSSZ",
            },
        )
        assert bad.status_code == 403

        good = client.post(
            "/api/auth/register",
            json={
                "email": "haver@example.com",
                "password": "OtherPassword123",
                "display_name": "Haver",
                "invite_code": "KIFLI2026",
            },
        )
        assert good.status_code == 200
        assert good.json()["is_admin"] is False
        u2_recipes = [r["title"] for r in client.get("/api/recipes").json()]
        assert "Márk Titkos Rakott Krumplija" not in u2_recipes

        # 4. 1-kattintásos Demo Sandbox belépés + szimulált Kifli kosár + Sajátmárka popup + AI limit
        client.cookies.clear()
        d = client.post("/api/auth/demo")
        assert d.status_code == 200
        assert d.json()["is_demo"] is True

        demo_cart = client.get("/api/kifli/cart").json()
        assert demo_cart["is_demo_sandbox"] is True
        assert demo_cart["item_count"] >= 5

        opt = client.post("/api/kifli/cart/optimize-private-label").json()
        assert len(opt["auto_swapped"]) >= 2
        assert len(opt["favorite_proposals"]) >= 1  # Zewa Deluxe és Magyar Tej kedvenc!

        # Demo chat 0 AI költséggel statikus magyar tájékoztatót ad vissza
        demo_chat = client.post("/api/chat", json={"message": "Szia, mit főzzek?"})
        assert demo_chat.status_code == 200
        assert "Demo módban az AI séf" in demo_chat.json()["reply"]

        # Napi AI limit (demo_daily_ai_limit=3) tényleg leállítja a 4. hívást
        demo_uid = d.json()["id"]
        for _ in range(3):
            app.state.agent.check_and_consume_ai_quota(user_id=demo_uid)
        try:
            app.state.agent.check_and_consume_ai_quota(user_id=demo_uid)
            assert False, "Elvártuk a napi AI limit hibát!"
        except RuntimeError as exc:
            assert "napi 3" in str(exc).lower()


def test_google_oauth_login_redirect_and_csrf_state(tmp_path: Path) -> None:
    settings = _make_settings(
        tmp_path,
        auth_required=True,
        google_client_id="demo-google-client-id.apps.googleusercontent.com",
        google_client_secret="demo-google-secret",
    )
    app = create_app(custom_settings=settings, enable_background=False)
    with TestClient(app) as client:
        cfg = client.get("/api/auth/config").json()
        assert cfg["google_login_enabled"] is True

        # Redirect Google felé + CSRF state cookie beállítva
        r = client.get("/api/auth/google/login", follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["location"]
        assert "accounts.google.com/o/oauth2/v2/auth" in loc
        assert "demo-google-client-id.apps.googleusercontent.com" in loc
        assert "kifli_google_state" in r.cookies

        # Rossz state-tel visszairányít hibaüzenettel (CSRF védelem!)
        bad_cb = client.get(
            "/api/auth/google/callback?code=abc&state=ROSSZ", follow_redirects=False
        )
        assert bad_cb.status_code == 302
        assert "auth_error=" in bad_cb.headers["location"]
