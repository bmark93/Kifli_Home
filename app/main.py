from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings, load_settings
from app.db import Database
from app.kifli_mcp import KifliMCPManager
from app.llm_agent import ChefShoppingAgent
from app.media import save_recipe_image_bytes
from app.otthon_mcp_server import OptionalPinASGIWrapper, create_otthon_mcp_server
from app.scheduler_and_bot import BotAndSchedulerRuntime
from starlette.routing import Route

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

STATIC_DIR = Path(__file__).parent / "static"


class IngredientInput(BaseModel):
    name: str
    quantity: float = 1.0
    unit: str = "db"
    is_staple: bool = False
    brand_hint: str = ""


class RecipeInput(BaseModel):
    title: str
    categories: list[str] = Field(default_factory=lambda: ["ebed"])
    servings: int = 2
    instructions: str = ""
    source_url: str = ""
    image_url: str | None = None
    healthy_score: int = 3
    ingredients: list[IngredientInput] = Field(default_factory=list)


class RecipeImportInput(BaseModel):
    text_or_url: str


class GeneralItemInput(BaseModel):
    name: str
    quantity: float = 1.0
    unit: str = "db"
    brand_hint: str = ""


class ConfirmOrderInput(BaseModel):
    include_pending: bool = False


class StapleInput(BaseModel):
    name: str


class PreferenceInput(BaseModel):
    ingredient_name: str
    kifli_product_id: str
    kifli_product_name: str


class ChatInput(BaseModel):
    message: str


class KifliCallbackInput(BaseModel):
    callback_url: str


class CartItemUpdateInput(BaseModel):
    product_id: int
    quantity: int


class ManualSlotSwapInput(BaseModel):
    days: list[str] = Field(min_length=1)
    meal_type: str
    recipe_id: int | None = None
    custom_title: str = ""
    clear: bool = False


def create_app(custom_settings: Settings | None = None, enable_background: bool | None = None) -> FastAPI:
    settings = custom_settings or load_settings()
    db = Database(settings.db_path)
    kifli = KifliMCPManager(
        mcp_url=settings.kifli_mcp_url,
        redirect_uri=settings.kifli_oauth_redirect_uri,
        oauth_dir=settings.kifli_oauth_dir,
    )
    agent = ChefShoppingAgent(settings=settings, db=db, kifli=kifli)
    runtime = BotAndSchedulerRuntime(settings=settings, db=db, kifli=kifli, agent=agent)
    otthon_mcp, otthon_mcp_starlette = create_otthon_mcp_server(db=db, settings=settings)

    run_bg = (
        enable_background
        if enable_background is not None
        else (os.getenv("DISABLE_BACKGROUND", "0") != "1")
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with otthon_mcp_starlette.router.lifespan_context(otthon_mcp_starlette):
            if run_bg:
                await runtime.start()
            try:
                yield
            finally:
                if run_bg:
                    await runtime.stop()

    app = FastAPI(title="Kifli Otthon — Menü & Bevásárló Asszisztens", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.kifli = kifli
    app.state.agent = agent
    app.state.runtime = runtime
    app.state.otthon_mcp = otthon_mcp

    # Saját bejövő MCP végpont (Streamable HTTP: /mcp és /mcp/<TOKEN>) Claude Remote / Desktop számára!
    for r in otthon_mcp_starlette.routes:
        if isinstance(r, Route) and r.path == "/mcp":
            wrapped_mcp = OptionalPinASGIWrapper(r.endpoint, settings.mcp_access_token)
            app.router.routes.append(
                Route("/mcp", endpoint=wrapped_mcp, methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"])
            )
            app.router.routes.append(
                Route("/mcp/", endpoint=wrapped_mcp, methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"])
            )
            app.router.routes.append(
                Route("/mcp/{pin}", endpoint=wrapped_mcp, methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"])
            )
            app.router.routes.append(
                Route("/mcp/{pin}/", endpoint=wrapped_mcp, methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"])
            )

    async def verify_pin(
        request: Request, x_app_pin: str | None = Header(default=None)
    ) -> None:
        expected = settings.app_access_pin
        if not expected:
            return
        supplied = x_app_pin or request.cookies.get("app_pin", "")
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Érvénytelen vagy hiányzó APP_ACCESS_PIN!")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/api/status", dependencies=[Depends(verify_pin)])
    async def status() -> dict[str, Any]:
        return {
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "llm_key_configured": bool(
                settings.llm_api_key and "IDE_JON" not in settings.llm_api_key
            ),
            "telegram_configured": bool(settings.telegram_bot_token),
            "cron_schedule": f"{settings.weekly_cron_day.upper()} {settings.weekly_cron_hour:02d}:{settings.weekly_cron_minute:02d} ({settings.timezone})",
            "kifli": await kifli.get_status(),
        }

    # --- Receptek ---
    @app.get("/api/recipes", dependencies=[Depends(verify_pin)])
    async def get_recipes(category: str | None = None) -> list[dict[str, Any]]:
        return db.list_recipes(category=category)

    @app.post("/api/recipes", dependencies=[Depends(verify_pin)])
    async def create_recipe(payload: RecipeInput) -> dict[str, Any]:
        return db.create_or_update_recipe(
            title=payload.title,
            categories=payload.categories,
            servings=payload.servings,
            instructions=payload.instructions,
            source_url=payload.source_url,
            image_url=payload.image_url,
            healthy_score=payload.healthy_score,
            ingredients=[i.model_dump() for i in payload.ingredients],
        )

    @app.put("/api/recipes/{recipe_id}", dependencies=[Depends(verify_pin)])
    async def update_recipe(recipe_id: int, payload: RecipeInput) -> dict[str, Any]:
        return db.create_or_update_recipe(
            recipe_id=recipe_id,
            title=payload.title,
            categories=payload.categories,
            servings=payload.servings,
            instructions=payload.instructions,
            source_url=payload.source_url,
            image_url=payload.image_url,
            healthy_score=payload.healthy_score,
            ingredients=[i.model_dump() for i in payload.ingredients],
        )

    @app.post("/api/recipes/{recipe_id}/image", dependencies=[Depends(verify_pin)])
    async def upload_recipe_image(
        recipe_id: int, file: UploadFile = File(...)
    ) -> dict[str, Any]:
        try:
            content = await file.read()
            saved_url = save_recipe_image_bytes(
                settings.data_dir,
                content,
                mime_type=file.content_type or "",
                filename=file.filename or "",
            )
            return db.set_recipe_image(recipe_id, saved_url)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/recipes/{recipe_id}/image", dependencies=[Depends(verify_pin)])
    async def delete_recipe_image(recipe_id: int) -> dict[str, Any]:
        try:
            return db.set_recipe_image(recipe_id, "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/recipes/{recipe_id}", dependencies=[Depends(verify_pin)])
    async def remove_recipe(recipe_id: int) -> dict[str, Any]:
        return {"deleted": db.delete_recipe(recipe_id)}

    @app.post("/api/recipes/import", dependencies=[Depends(verify_pin)])
    async def import_recipe(payload: RecipeImportInput) -> dict[str, Any]:
        try:
            return await agent.parse_recipe_from_text_or_url(payload.text_or_url)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- Általános / Háztartási egyszeri lista ---
    @app.get("/api/general-items", dependencies=[Depends(verify_pin)])
    async def get_general_items(include_ordered: bool = False) -> list[dict[str, Any]]:
        return db.list_general_items(include_ordered=include_ordered)

    @app.post("/api/general-items", dependencies=[Depends(verify_pin)])
    async def post_general_item(payload: GeneralItemInput) -> dict[str, Any]:
        return db.add_general_item(
            name=payload.name,
            quantity=payload.quantity,
            unit=payload.unit,
            brand_hint=payload.brand_hint,
        )

    @app.delete("/api/general-items/{item_id}", dependencies=[Depends(verify_pin)])
    async def remove_general_item(item_id: int) -> dict[str, Any]:
        return {"deleted": db.delete_general_item(item_id)}

    @app.post("/api/general-items/confirm-order", dependencies=[Depends(verify_pin)])
    async def confirm_order(payload: ConfirmOrderInput) -> dict[str, Any]:
        return db.finalize_order_and_clear_general_items(
            include_pending_if_forced=payload.include_pending
        )

    @app.post("/api/general-items/revert-cart", dependencies=[Depends(verify_pin)])
    async def revert_cart_items() -> dict[str, Any]:
        return {"reverted": db.revert_in_cart_general_items_to_pending()}

    # --- Heti Menü & Összesített Bevásárlólista ---
    @app.get("/api/weekly-plan", dependencies=[Depends(verify_pin)])
    async def get_weekly_plan() -> dict[str, Any]:
        return {
            "plan": db.get_weekly_plan(),
            "aggregated_shopping": db.aggregate_shopping_list(),
        }

    @app.put("/api/weekly-plan/slot", dependencies=[Depends(verify_pin)])
    async def manual_swap_weekly_slot(payload: ManualSlotSwapInput) -> dict[str, Any]:
        try:
            updated_plan = db.set_weekly_meal_slots_manual(
                day_keys=payload.days,
                meal_type=payload.meal_type,
                recipe_id=payload.recipe_id,
                custom_title=payload.custom_title,
                clear=payload.clear,
            )
            return {
                "plan": updated_plan,
                "aggregated_shopping": db.aggregate_shopping_list(),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/weekly-plan/reset", dependencies=[Depends(verify_pin)])
    async def reset_weekly_plan() -> dict[str, Any]:
        return {
            "plan": db.reset_weekly_plan(),
            "aggregated_shopping": db.aggregate_shopping_list(),
        }

    @app.post("/api/weekly-plan/generate", dependencies=[Depends(verify_pin)])
    async def trigger_weekly_plan_generation() -> dict[str, Any]:
        try:
            proposal_text = await agent.generate_monday_weekly_proposal()
            return {
                "proposal": proposal_text,
                "plan": db.get_weekly_plan(),
                "aggregated_shopping": db.aggregate_shopping_list(),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- Chat ---
    @app.get("/api/chat", dependencies=[Depends(verify_pin)])
    async def get_chat_messages() -> list[dict[str, Any]]:
        return db.get_recent_chat_messages(limit=30)

    @app.post("/api/chat", dependencies=[Depends(verify_pin)])
    async def send_chat_message(payload: ChatInput) -> dict[str, Any]:
        try:
            reply = await agent.chat(payload.message, source="web")
            return {
                "reply": reply,
                "plan": db.get_weekly_plan(),
                "general_items": db.list_general_items(),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/chat", dependencies=[Depends(verify_pin)])
    async def reset_chat() -> dict[str, Any]:
        db.clear_chat_history()
        return {"cleared": True}

    # --- Kamra & Kedvenc Kifli termékek ---
    @app.get("/api/staples", dependencies=[Depends(verify_pin)])
    async def get_staples() -> list[dict[str, str]]:
        return db.list_staples()

    @app.post("/api/staples", dependencies=[Depends(verify_pin)])
    async def create_staple(payload: StapleInput) -> list[dict[str, str]]:
        db.add_staple(payload.name)
        return db.list_staples()

    @app.delete("/api/staples/{key}", dependencies=[Depends(verify_pin)])
    async def remove_staple(key: str) -> dict[str, Any]:
        return {"deleted": db.delete_staple(key)}

    @app.get("/api/preferences", dependencies=[Depends(verify_pin)])
    async def get_preferences() -> list[dict[str, Any]]:
        return db.list_product_preferences()

    @app.post("/api/preferences", dependencies=[Depends(verify_pin)])
    async def create_preference(payload: PreferenceInput) -> dict[str, Any]:
        return db.save_product_preference(
            ingredient_name=payload.ingredient_name,
            kifli_product_id=payload.kifli_product_id,
            kifli_product_name=payload.kifli_product_name,
        )

    @app.delete("/api/preferences/{key}", dependencies=[Depends(verify_pin)])
    async def remove_preference(key: str) -> dict[str, Any]:
        return {"deleted": db.delete_product_preference(key)}

    # --- Kifli.hu OAuth 2.1 MCP ---
    @app.post("/api/kifli/login", dependencies=[Depends(verify_pin)])
    async def start_kifli_login() -> dict[str, Any]:
        try:
            url = await kifli.start_login_flow()
            return {"login_url": url}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/callback", dependencies=[Depends(verify_pin)])
    async def complete_kifli_login(payload: KifliCallbackInput) -> dict[str, Any]:
        try:
            return await kifli.submit_callback_url(payload.callback_url)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/logout", dependencies=[Depends(verify_pin)])
    async def logout_kifli() -> dict[str, Any]:
        await kifli.logout()
        return await kifli.get_status()

    @app.get("/api/kifli/tools", dependencies=[Depends(verify_pin)])
    async def list_kifli_tools() -> list[dict[str, Any]]:
        try:
            return await kifli.list_tools(force_refresh=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _parse_kifli_cart_payload(raw_json: str) -> dict[str, Any]:
        payload = json.loads(raw_json)
        data = payload.get("data") or {}
        items_dict = data.get("items") or {}
        categories_dict = data.get("categories") or {}

        cat_by_product: dict[int, str] = {}
        for cobj in categories_dict.values():
            cname = cobj.get("name", "Egyéb")
            for pid in cobj.get("items") or []:
                cat_by_product[int(pid)] = cname

        parsed_items: list[dict[str, Any]] = []
        for pid_str, item in items_dict.items():
            pid = int(item.get("productId") or pid_str)
            img_path = item.get("imgPath") or ""
            qty = int(item.get("quantity") or 1)
            unit_price = float(item.get("price") or 0)
            orig_price = float(item.get("originalPricePerUnit") or unit_price)
            parsed_items.append(
                {
                    "product_id": pid,
                    "name": item.get("productName", f"Termék #{pid}"),
                    "quantity": qty,
                    "unit_price": round(unit_price),
                    "line_total": round(unit_price * qty),
                    "original_unit_price": round(orig_price),
                    "sale_percent": int(item.get("salePercents") or 0),
                    "volume": item.get("volume") or "",
                    "unit": item.get("unit") or "db",
                    "category": cat_by_product.get(pid, "Kosár"),
                    "image_url": f"https://cdn.kifli.hu{img_path}" if img_path.startswith("/") else img_path,
                    "kifli_url": f"https://www.kifli.hu/{item.get('baseLink', '')}".rstrip("/"),
                }
            )
        parsed_items.sort(key=lambda x: (x["category"], x["name"]))
        return {
            "connected": True,
            "cart_id": data.get("cartId"),
            "total_price": round(float(data.get("totalPrice") or 0)),
            "total_savings": round(float(data.get("totalSavings") or 0)),
            "min_order_price": round(float(data.get("minimalStandardOrderPrice") or 12000)),
            "can_checkout": bool(data.get("submitConditionPassed", False)),
            "item_count": len(parsed_items),
            "total_units": sum(i["quantity"] for i in parsed_items),
            "items": parsed_items,
        }

    @app.get("/api/kifli/cart", dependencies=[Depends(verify_pin)])
    async def get_live_kifli_cart() -> dict[str, Any]:
        st = await kifli.get_status()
        if not st["authenticated"]:
            return {
                "connected": False,
                "total_price": 0,
                "total_savings": 0,
                "min_order_price": 12000,
                "item_count": 0,
                "total_units": 0,
                "items": [],
            }
        try:
            raw = await kifli.call_tool_untruncated(
                "get_cart", {"context": "Display current shopping cart in home assistant UI"}
            )
            return _parse_kifli_cart_payload(raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/cart/update", dependencies=[Depends(verify_pin)])
    async def update_live_kifli_cart_item(payload: CartItemUpdateInput) -> dict[str, Any]:
        try:
            if payload.quantity <= 0:
                await kifli.call_tool_untruncated(
                    "remove_cart_item",
                    {
                        "product_id": payload.product_id,
                        "context": "User removed item from cart in UI",
                    },
                )
            else:
                await kifli.call_tool_untruncated(
                    "update_cart_item",
                    {
                        "product_id": payload.product_id,
                        "quantity": payload.quantity,
                        "context": "User adjusted item quantity in UI",
                    },
                )
            raw = await kifli.call_tool_untruncated(
                "get_cart", {"context": "Refresh shopping cart after quantity update"}
            )
            return _parse_kifli_cart_payload(raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/cart/clear", dependencies=[Depends(verify_pin)])
    async def clear_live_kifli_cart() -> dict[str, Any]:
        try:
            await kifli.call_tool_untruncated(
                "clear_cart", {"context": "User requested clearing the shopping cart"}
            )
            raw = await kifli.call_tool_untruncated(
                "get_cart", {"context": "Refresh empty cart"}
            )
            return _parse_kifli_cart_payload(raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    uploads_dir = settings.data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def serve_index() -> FileResponse:
        return FileResponse(
            str(STATIC_DIR / "index.html"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    return app


app = create_app()
