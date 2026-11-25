from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.routing import Route

from app.auth import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_session_token,
    decrypt_secret,
    encrypt_secret,
    generate_personal_mcp_token,
    hash_password,
    load_or_create_secret,
    mask_api_key,
    verify_password,
    verify_session_token,
)
from app.config import Settings, load_settings
from app.db import Database
from app.demo_sandbox import DemoCartSandbox
from app.kifli_mcp import KifliMCPManager
from app.kifli_recipes import import_kifli_recipe_to_db, search_kifli_recipes
from app.llm_agent import ChefShoppingAgent
from app.media import save_recipe_image_bytes
from app.otthon_mcp_server import OptionalPinASGIWrapper, create_otthon_mcp_server
from app.private_label import execute_cart_swaps, optimize_cart_private_label_structured
from app.scheduler_and_bot import BotAndSchedulerRuntime
from app.smart_restock import analyze_smart_restock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

STATIC_DIR = Path(__file__).parent / "static"


class RegisterInput(BaseModel):
    email: str
    password: str = Field(min_length=6)
    display_name: str = ""
    invite_code: str = ""


class LoginInput(BaseModel):
    email: str
    password: str


class UserLLMSettingsInput(BaseModel):
    llm_provider: str = ""  # "", "gemini", "openai", "custom"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str | None = None  # None = ne bántsa, "" = törölje a saját kulcsot


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
    kcal_per_serving: int | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    is_public: bool | None = None
    ingredients: list[IngredientInput] = Field(default_factory=list)


class RecipeVisibilityInput(BaseModel):
    is_public: bool


class KifliRecipeImportInput(BaseModel):
    fallback_title: str = ""
    fallback_image_url: str = ""
    fallback_ingredients_preview: str = ""


class TinderDaysUpdateInput(BaseModel):
    target_days: list[str]


class HouseholdJoinInput(BaseModel):
    join_code: str


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


class PlannerSettingsInput(BaseModel):
    household_size: int | None = None
    plan_days: int | None = None
    days_per_meal: int | None = None
    weekly_budget_ft: int | None = None
    daily_calorie_target: int | None = None
    allergens: list[str] | None = None
    prefer_private_label: bool | None = None
    prefer_discounts_and_save_food: bool | None = None
    min_healthy_score: float | None = None
    ai_recommendations_enabled: bool | None = None
    ai_recommendation_count: int | None = None
    ai_recommendation_meals: list[str] | None = None
    recipe_sources: list[str] | None = None


class TinderSessionCreateInput(BaseModel):
    meal_type: str = "ebed"
    target_days: list[str] = Field(default_factory=lambda: ["hetfo", "kedd"])


class TinderSwipeInput(BaseModel):
    user_slot: str = "p1"
    recipe_id: int
    decision: str = "like"


class TinderAcceptMatchInput(BaseModel):
    days: list[str] = Field(min_length=1)
    meal_type: str
    recipe_id: int


class CartSwapItemInput(BaseModel):
    old_product_id: int
    new_product_id: int
    new_quantity: int = 1


class CartApplySwapsInput(BaseModel):
    swaps: list[CartSwapItemInput] = Field(min_length=1)


def create_app(
    custom_settings: Settings | None = None, enable_background: bool | None = None
) -> FastAPI:
    settings = custom_settings or load_settings()
    secret_key = load_or_create_secret(settings.data_dir, settings.app_secret_key)
    db = Database(settings.db_path)

    # Per-user KifliMCPManager pool (user_id=1 a régi ./data/kifli_oauth mappát örökli!)
    kifli_pool: dict[int, KifliMCPManager] = {}

    def get_kifli_for_user(user_id: int) -> KifliMCPManager:
        uid = int(user_id)
        if uid not in kifli_pool:
            oauth_dir = (
                settings.kifli_oauth_dir
                if uid == 1
                else settings.kifli_oauth_dir / f"user_{uid}"
            )
            kifli_pool[uid] = KifliMCPManager(
                mcp_url=settings.kifli_mcp_url,
                redirect_uri=settings.kifli_oauth_redirect_uri,
                oauth_dir=oauth_dir,
            )
        return kifli_pool[uid]

    default_kifli = get_kifli_for_user(1)
    demo_sandbox = DemoCartSandbox()
    agent = ChefShoppingAgent(
        settings=settings, db=db, kifli=default_kifli, secret_key=secret_key
    )
    runtime = BotAndSchedulerRuntime(
        settings=settings, db=db, kifli=default_kifli, agent=agent
    )
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

    app = FastAPI(title="kifli.otthon — Multi-User Menü & Bevásárló Asszisztens", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.kifli = default_kifli
    app.state.agent = agent
    app.state.runtime = runtime
    app.state.otthon_mcp = otthon_mcp
    app.state.demo_sandbox = demo_sandbox

    # Saját bejövő MCP végpont (Streamable HTTP: /mcp és /mcp/<TOKEN>)
    for r in otthon_mcp_starlette.routes:
        if isinstance(r, Route) and r.path == "/mcp":
            wrapped_mcp = OptionalPinASGIWrapper(
                r.endpoint,
                settings.mcp_access_token,
                db=db,
                require_token_always=settings.auth_required,
            )
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

    def _set_session_cookie(response: Response, user_id: int, request: Request) -> None:
        token = create_session_token(secret_key, user_id)
        is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").lower() == "https"
        )
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=is_https,
            path="/",
        )

    def _ws_id(user: dict[str, Any]) -> int:
        return db.effective_workspace_id(user)

    def _public_user_payload(user: dict[str, Any]) -> dict[str, Any]:
        uid = int(user["id"])
        ws_id = _ws_id(user)
        ws_user = db.get_user_by_id(ws_id) or user
        llm_cfg = agent.resolve_llm_config_for_user(ws_id)
        raw_user_key = (
            decrypt_secret(secret_key, ws_user.get("llm_api_key_enc") or "")
            if ws_user.get("llm_api_key_enc")
            else ""
        )
        return {
            "id": uid,
            "workspace_user_id": ws_id,
            "email": user["email"],
            "display_name": user["display_name"],
            "is_admin": bool(user.get("is_admin")),
            "is_demo": bool(user.get("is_demo")),
            "mcp_token": user.get("mcp_token") or (settings.mcp_access_token if uid == 1 else ""),
            "llm": {
                "provider": llm_cfg["provider"],
                "model": llm_cfg["model"],
                "base_url": ws_user.get("llm_base_url") or "",
                "using_own_key": llm_cfg["using_own_key"],
                "masked_api_key": mask_api_key(raw_user_key),
                "daily_limit": llm_cfg["daily_limit"],
                "daily_used": db.get_daily_ai_usage(ws_id),
            },
        }

    async def get_current_user(
        request: Request, x_app_pin: str | None = Header(default=None)
    ) -> dict[str, Any]:
        if not settings.auth_required:
            # Egyszemélyes LAN mód (opcionális PIN védelemmel)
            expected = settings.app_access_pin
            if expected:
                supplied = x_app_pin or request.cookies.get("app_pin", "")
                if not supplied or not hmac.compare_digest(supplied, expected):
                    raise HTTPException(
                        status_code=401, detail="Érvénytelen vagy hiányzó APP_ACCESS_PIN!"
                    )
            u = db.get_user_by_id(1)
            if u:
                return u
            return {
                "id": 1,
                "email": "local@kifli.otthon",
                "display_name": "Otthoni Fiók",
                "is_admin": 1,
                "is_demo": 0,
                "llm_provider": "",
                "llm_model": "",
                "llm_base_url": "",
                "llm_api_key_enc": "",
                "mcp_token": settings.mcp_access_token,
            }

        cookie_token = request.cookies.get(SESSION_COOKIE_NAME, "")
        uid = verify_session_token(secret_key, cookie_token)
        if uid is None:
            raise HTTPException(status_code=401, detail="Bejelentkezés szükséges!")
        user = db.get_user_by_id(uid)
        if not user:
            raise HTTPException(status_code=401, detail="Érvénytelen munkamenet!")
        return user

    # --- Health & Auth ---
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/api/auth/config")
    async def auth_config() -> dict[str, Any]:
        return {
            "auth_required": settings.auth_required,
            "demo_mode_enabled": settings.demo_mode_enabled,
            "google_login_enabled": bool(
                settings.google_client_id and settings.google_client_secret
            ),
            "invite_required": bool(settings.invite_code) and db.count_real_users() > 0,
            "has_registered_users": db.count_real_users() > 0,
        }

    def _resolve_google_redirect_uri(request: Request) -> str:
        if settings.google_redirect_uri:
            return settings.google_redirect_uri
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        return f"{proto}://{host}/api/auth/google/callback"

    @app.get("/api/auth/google/login")
    async def google_oauth_login(request: Request) -> RedirectResponse:
        if not settings.google_client_id or not settings.google_client_secret:
            raise HTTPException(
                status_code=400, detail="A Google bejelentkezés még nincs beállítva a .env-ben."
            )
        state = secrets.token_urlsafe(24)
        redirect_uri = _resolve_google_redirect_uri(request)
        params = urlencode(
            {
                "client_id": settings.google_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "prompt": "select_account",
            }
        )
        resp = RedirectResponse(
            url=f"https://accounts.google.com/o/oauth2/v2/auth?{params}",
            status_code=302,
        )
        is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").lower() == "https"
        )
        resp.set_cookie(
            key="kifli_google_state",
            value=state,
            max_age=600,
            httponly=True,
            samesite="lax",
            secure=is_https,
            path="/",
        )
        return resp

    @app.get("/api/auth/google/callback")
    async def google_oauth_callback(
        request: Request,
        code: str = "",
        state: str = "",
        error: str = "",
    ) -> RedirectResponse:
        def _err_redirect(msg: str) -> RedirectResponse:
            r = RedirectResponse(url=f"/?{urlencode({'auth_error': msg})}", status_code=302)
            r.delete_cookie("kifli_google_state", path="/")
            return r

        if error:
            return _err_redirect(f"Google belépés megszakítva ({error}).")
        expected_state = request.cookies.get("kifli_google_state", "")
        if not state or not expected_state or not hmac.compare_digest(state, expected_state):
            return _err_redirect("Lejárt vagy érvénytelen Google belépési munkamenet. Próbáld újra!")
        if not code:
            return _err_redirect("Hiányzó Google hitelesítési kód.")

        redirect_uri = _resolve_google_redirect_uri(request)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                tok_resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": settings.google_client_id,
                        "client_secret": settings.google_client_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
                if tok_resp.status_code != 200:
                    return _err_redirect("Google token csere sikertelen (ellenőrizd a Redirect URI-t!).")
                access_token = tok_resp.json().get("access_token", "")
                info_resp = await client.get(
                    "https://openidconnect.googleapis.com/v1/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if info_resp.status_code != 200:
                    return _err_redirect("Nem sikerült lekérni a Google profil adatait.")
                profile = info_resp.json()
        except Exception as exc:
            logging.getLogger("kifli_otthon.auth").warning("Google OAuth hiba: %s", exc)
            return _err_redirect("Hálózati hiba a Google bejelentkezés közben.")

        email = str(profile.get("email") or "").strip().lower()
        if not email or profile.get("email_verified") is False:
            return _err_redirect("Csak megerősített Google e-mail címmel lehet belépni.")

        if settings.allowed_google_emails and email not in settings.allowed_google_emails:
            return _err_redirect("Ez a Google e-mail cím nincs engedélyezve ezen a szerveren.")

        user = db.get_user_by_email(email)
        if not user:
            is_first_real_user = db.count_real_users() == 0
            force_id = 1 if (is_first_real_user and db.get_user_by_id(1) is None) else None
            mcp_tok = (
                settings.mcp_access_token
                if (force_id == 1 and settings.mcp_access_token)
                else generate_personal_mcp_token()
            )
            user = db.create_user(
                email=email,
                display_name=str(profile.get("name") or email.split("@")[0]),
                password_hash=hash_password(secrets.token_urlsafe(32)),
                is_admin=is_first_real_user,
                is_demo=False,
                mcp_token=mcp_tok,
                force_id=force_id,
            )

        resp = RedirectResponse(url="/", status_code=302)
        resp.delete_cookie("kifli_google_state", path="/")
        _set_session_cookie(resp, int(user["id"]), request)
        return resp

    @app.get("/api/auth/me")
    async def auth_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        return _public_user_payload(user)

    @app.post("/api/auth/register")
    async def auth_register(
        payload: RegisterInput, request: Request, response: Response
    ) -> dict[str, Any]:
        email = payload.email.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise HTTPException(status_code=400, detail="Adj meg egy érvényes e-mail címet!")
        if db.get_user_by_email(email):
            raise HTTPException(status_code=400, detail="Ezzel az e-mail címmel már létezik fiók!")

        is_first_real_user = db.count_real_users() == 0
        if not is_first_real_user and settings.invite_code:
            if not hmac.compare_digest(payload.invite_code.strip(), settings.invite_code):
                raise HTTPException(
                    status_code=403, detail="Érvénytelen vagy hiányzó meghívókód!"
                )

        # Az első regisztráló tulajdonos megkapja a user_id=1 fiókot (és az összes meglévő NAS receptet!)
        force_id = 1 if (is_first_real_user and db.get_user_by_id(1) is None) else None
        mcp_tok = (
            settings.mcp_access_token
            if (force_id == 1 and settings.mcp_access_token)
            else generate_personal_mcp_token()
        )
        user = db.create_user(
            email=email,
            display_name=payload.display_name or email.split("@")[0],
            password_hash=hash_password(payload.password),
            is_admin=is_first_real_user,
            is_demo=False,
            mcp_token=mcp_tok,
            force_id=force_id,
        )
        _set_session_cookie(response, int(user["id"]), request)
        return _public_user_payload(user)

    @app.post("/api/auth/login")
    async def auth_login(
        payload: LoginInput, request: Request, response: Response
    ) -> dict[str, Any]:
        user = db.get_user_by_email(payload.email)
        if not user or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Hibás e-mail cím vagy jelszó!")
        _set_session_cookie(response, int(user["id"]), request)
        return _public_user_payload(user)

    @app.post("/api/auth/demo")
    async def auth_demo_login(request: Request, response: Response) -> dict[str, Any]:
        if not settings.demo_mode_enabled:
            raise HTTPException(status_code=403, detail="A Demo mód ki van kapcsolva.")
        demo_user = db.ensure_demo_user(
            password_hash=hash_password(generate_personal_mcp_token()),
            mcp_token=generate_personal_mcp_token(),
        )
        _set_session_cookie(response, int(demo_user["id"]), request)
        return _public_user_payload(demo_user)

    @app.post("/api/auth/logout")
    async def auth_logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return {"ok": True}

    @app.put("/api/auth/llm-settings")
    async def update_my_llm_settings(
        payload: UserLLMSettingsInput,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        ws_id = _ws_id(user)
        enc_key: str | None = None
        if payload.llm_api_key is not None:
            enc_key = (
                encrypt_secret(secret_key, payload.llm_api_key)
                if payload.llm_api_key.strip()
                else ""
            )
        db.update_user_llm_settings(
            user_id=ws_id,
            llm_provider=payload.llm_provider,
            llm_model=payload.llm_model,
            llm_base_url=payload.llm_base_url,
            llm_api_key_enc=enc_key,
        )
        fresh_me = db.get_user_by_id(int(user["id"])) or user
        return _public_user_payload(fresh_me)

    # --- 🏠 Családi / Háztartási Fiók Összekapcsolás ---
    @app.get("/api/household")
    async def get_household_api(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user.get("is_demo"):
            return {
                "workspace_user_id": int(user["id"]),
                "is_owner": True,
                "owner_name": user["display_name"],
                "join_code": "DEMO99",
                "members": [
                    {
                        "id": int(user["id"]),
                        "email": user["email"],
                        "display_name": user["display_name"],
                        "is_owner": True,
                        "is_me": True,
                    }
                ],
            }
        return db.get_household_info(int(user["id"]))

    @app.post("/api/household/join")
    async def join_household_api(
        payload: HouseholdJoinInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        try:
            return db.join_household_by_code(int(user["id"]), payload.join_code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/household/leave")
    async def leave_household_api(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        try:
            return db.leave_or_remove_from_household(int(user["id"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/household/members/{member_id}")
    async def remove_household_member_api(
        member_id: int, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        try:
            return db.leave_or_remove_from_household(int(user["id"]), target_member_id=member_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/household/rotate-code")
    async def rotate_household_code_api(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            return db.rotate_household_join_code(int(user["id"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/auth/mcp-token/rotate")
    async def rotate_my_mcp_token(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        updated = db.rotate_user_mcp_token(int(user["id"]), generate_personal_mcp_token())
        return _public_user_payload(updated)

    # --- Status ---
    @app.get("/api/status")
    async def status(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        uid = _ws_id(user)
        is_demo = bool(user.get("is_demo"))
        llm_cfg = agent.resolve_llm_config_for_user(uid)
        kifli_status = (
            {
                "mcp_url": "demo://sandbox.kifli.hu",
                "authenticated": True,
                "has_refresh_token": True,
                "pending_login_url": None,
                "cached_tool_count": 18,
                "last_error": "",
                "is_demo_sandbox": True,
            }
            if is_demo
            else await get_kifli_for_user(uid).get_status()
        )
        return {
            "llm_provider": llm_cfg["provider"],
            "llm_model": llm_cfg["model"],
            "llm_key_configured": bool(
                llm_cfg["api_key"] and "IDE_JON" not in llm_cfg["api_key"]
            ),
            "using_own_key": llm_cfg["using_own_key"],
            "ai_daily_limit": llm_cfg["daily_limit"],
            "ai_daily_used": db.get_daily_ai_usage(uid),
            "telegram_configured": bool(settings.telegram_bot_token),
            "cron_schedule": f"{settings.weekly_cron_day.upper()} {settings.weekly_cron_hour:02d}:{settings.weekly_cron_minute:02d} ({settings.timezone})",
            "kifli": kifli_status,
            "user": _public_user_payload(user),
        }

    # --- Receptek ---
    @app.get("/api/recipes")
    async def get_recipes(
        category: str | None = None, user: dict[str, Any] = Depends(get_current_user)
    ) -> list[dict[str, Any]]:
        return db.list_recipes(category=category, user_id=_ws_id(user))

    @app.post("/api/recipes")
    async def create_recipe(
        payload: RecipeInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return db.create_or_update_recipe(
            title=payload.title,
            categories=payload.categories,
            servings=payload.servings,
            instructions=payload.instructions,
            source_url=payload.source_url,
            image_url=payload.image_url,
            healthy_score=payload.healthy_score,
            kcal_per_serving=payload.kcal_per_serving,
            protein_g=payload.protein_g,
            carbs_g=payload.carbs_g,
            fat_g=payload.fat_g,
            is_public=payload.is_public,
            ingredients=[i.model_dump() for i in payload.ingredients],
            user_id=_ws_id(user),
        )

    @app.put("/api/recipes/{recipe_id}")
    async def update_recipe(
        recipe_id: int, payload: RecipeInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        try:
            return db.create_or_update_recipe(
                recipe_id=recipe_id,
                title=payload.title,
                categories=payload.categories,
                servings=payload.servings,
                instructions=payload.instructions,
                source_url=payload.source_url,
                image_url=payload.image_url,
                healthy_score=payload.healthy_score,
                kcal_per_serving=payload.kcal_per_serving,
                protein_g=payload.protein_g,
                carbs_g=payload.carbs_g,
                fat_g=payload.fat_g,
                is_public=payload.is_public,
                ingredients=[i.model_dump() for i in payload.ingredients],
                user_id=_ws_id(user),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/recipes/{recipe_id}/visibility")
    async def set_recipe_visibility_api(
        recipe_id: int,
        payload: RecipeVisibilityInput,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            return db.set_recipe_visibility(
                recipe_id=recipe_id, is_public=payload.is_public, user_id=_ws_id(user)
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # --- 🌍 Közösségi Recept Válogatás + Kifli.hu Recept Szinkron ---
    @app.get("/api/community/recipes")
    async def list_community_recipes_api(
        category: str | None = None,
        search: str = "",
        user: dict[str, Any] = Depends(get_current_user),
    ) -> list[dict[str, Any]]:
        return db.list_community_recipes(
            category=category or None, search=search, current_user_id=_ws_id(user)
        )

    @app.post("/api/community/recipes/{recipe_id}/copy")
    async def copy_community_recipe_api(
        recipe_id: int, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        try:
            return db.copy_public_recipe_to_user(
                source_recipe_id=recipe_id, target_user_id=_ws_id(user)
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/kifli/recipes")
    async def search_kifli_recipes_api(
        query: str = "",
        limit: int = 9,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        uid = _ws_id(user)
        is_demo = bool(user.get("is_demo"))
        return await search_kifli_recipes(
            kifli=None if is_demo else get_kifli_for_user(uid),
            query=query,
            limit=limit,
            is_demo=is_demo,
        )

    @app.post("/api/kifli/recipes/{kifli_recipe_id}/import")
    async def import_kifli_recipe_api(
        kifli_recipe_id: int,
        payload: KifliRecipeImportInput | None = None,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        uid = _ws_id(user)
        is_demo = bool(user.get("is_demo"))
        p = payload or KifliRecipeImportInput()
        try:
            return await import_kifli_recipe_to_db(
                db=db,
                kifli=None if is_demo else get_kifli_for_user(uid),
                kifli_recipe_id=kifli_recipe_id,
                user_id=uid,
                is_demo=is_demo,
                fallback_title=p.fallback_title,
                fallback_image_url=p.fallback_image_url,
                fallback_ingredients_preview=p.fallback_ingredients_preview,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/recipes/{recipe_id}/estimate-macros")
    async def estimate_recipe_macros_api(
        recipe_id: int, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        try:
            return await agent.estimate_recipe_macros(recipe_id=recipe_id, user_id=_ws_id(user))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/recipes/{recipe_id}/image")
    async def upload_recipe_image(
        recipe_id: int,
        file: UploadFile = File(...),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            content = await file.read()
            saved_url = save_recipe_image_bytes(
                settings.data_dir,
                content,
                mime_type=file.content_type or "",
                filename=file.filename or "",
            )
            return db.set_recipe_image(recipe_id, saved_url, user_id=_ws_id(user))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/recipes/{recipe_id}/image")
    async def delete_recipe_image(
        recipe_id: int, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        try:
            return db.set_recipe_image(recipe_id, "", user_id=_ws_id(user))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/recipes/{recipe_id}")
    async def remove_recipe(
        recipe_id: int, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return {"deleted": db.delete_recipe(recipe_id, user_id=_ws_id(user))}

    @app.post("/api/recipes/import")
    async def import_recipe(
        payload: RecipeImportInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        try:
            return await agent.parse_recipe_from_text_or_url(
                payload.text_or_url, user_id=_ws_id(user)
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- Általános / Háztartási egyszeri lista ---
    @app.get("/api/general-items")
    async def get_general_items(
        include_ordered: bool = False, user: dict[str, Any] = Depends(get_current_user)
    ) -> list[dict[str, Any]]:
        return db.list_general_items(include_ordered=include_ordered, user_id=_ws_id(user))

    @app.post("/api/general-items")
    async def post_general_item(
        payload: GeneralItemInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return db.add_general_item(
            name=payload.name,
            quantity=payload.quantity,
            unit=payload.unit,
            brand_hint=payload.brand_hint,
            user_id=_ws_id(user),
        )

    @app.delete("/api/general-items/{item_id}")
    async def remove_general_item(
        item_id: int, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return {"deleted": db.delete_general_item(item_id, user_id=_ws_id(user))}

    @app.post("/api/general-items/confirm-order")
    async def confirm_order(
        payload: ConfirmOrderInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return db.finalize_order_and_clear_general_items(
            include_pending_if_forced=payload.include_pending, user_id=_ws_id(user)
        )

    @app.post("/api/general-items/revert-cart")
    async def revert_cart_items(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        return {"reverted": db.revert_in_cart_general_items_to_pending(user_id=_ws_id(user))}

    # --- Heti Menü & Összesített Bevásárlólista ---
    @app.get("/api/weekly-plan")
    async def get_weekly_plan(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        uid = _ws_id(user)
        return {
            "plan": db.get_weekly_plan(user_id=uid),
            "aggregated_shopping": db.aggregate_shopping_list(user_id=uid),
        }

    @app.put("/api/weekly-plan/slot")
    async def manual_swap_weekly_slot(
        payload: ManualSlotSwapInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        uid = _ws_id(user)
        try:
            updated_plan = db.set_weekly_meal_slots_manual(
                day_keys=payload.days,
                meal_type=payload.meal_type,
                recipe_id=payload.recipe_id,
                custom_title=payload.custom_title,
                clear=payload.clear,
                user_id=uid,
            )
            return {
                "plan": updated_plan,
                "aggregated_shopping": db.aggregate_shopping_list(user_id=uid),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/weekly-plan/reset")
    async def reset_weekly_plan(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        uid = _ws_id(user)
        return {
            "plan": db.reset_weekly_plan(user_id=uid),
            "aggregated_shopping": db.aggregate_shopping_list(user_id=uid),
        }

    @app.post("/api/weekly-plan/generate")
    async def trigger_weekly_plan_generation(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        uid = _ws_id(user)
        is_demo = bool(user.get("is_demo"))
        try:
            proposal_text = await agent.generate_monday_weekly_proposal(
                user_id=uid,
                kifli_client=None if is_demo else get_kifli_for_user(uid),
                is_demo=is_demo,
            )
            return {
                "proposal": proposal_text,
                "plan": db.get_weekly_plan(user_id=uid),
                "aggregated_shopping": db.aggregate_shopping_list(user_id=uid),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- Chat ---
    @app.get("/api/chat")
    async def get_chat_messages(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> list[dict[str, Any]]:
        return db.get_recent_chat_messages(limit=30, user_id=_ws_id(user))

    @app.post("/api/chat")
    async def send_chat_message(
        payload: ChatInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        uid = _ws_id(user)
        is_demo = bool(user.get("is_demo"))
        try:
            reply = await agent.chat(
                payload.message,
                source="web",
                user_id=uid,
                kifli_client=None if is_demo else get_kifli_for_user(uid),
                is_demo=is_demo,
            )
            return {
                "reply": reply,
                "plan": db.get_weekly_plan(user_id=uid),
                "general_items": db.list_general_items(user_id=uid),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/chat")
    async def reset_chat(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        db.clear_chat_history(user_id=_ws_id(user))
        return {"cleared": True}

    # --- Kamra & Kedvenc Kifli termékek ---
    @app.get("/api/staples")
    async def get_staples(user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, str]]:
        return db.list_staples(user_id=_ws_id(user))

    @app.post("/api/staples")
    async def create_staple(
        payload: StapleInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> list[dict[str, str]]:
        uid = _ws_id(user)
        db.add_staple(payload.name, user_id=uid)
        return db.list_staples(user_id=uid)

    @app.delete("/api/staples/{key}")
    async def remove_staple(
        key: str, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return {"deleted": db.delete_staple(key, user_id=_ws_id(user))}

    @app.get("/api/preferences")
    async def get_preferences(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> list[dict[str, Any]]:
        return db.list_product_preferences(user_id=_ws_id(user))

    @app.post("/api/preferences")
    async def create_preference(
        payload: PreferenceInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return db.save_product_preference(
            ingredient_name=payload.ingredient_name,
            kifli_product_id=payload.kifli_product_id,
            kifli_product_name=payload.kifli_product_name,
            user_id=_ws_id(user),
        )

    @app.delete("/api/preferences/{key}")
    async def remove_preference(
        key: str, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return {"deleted": db.delete_product_preference(key, user_id=_ws_id(user))}

    # --- Kifli.hu OAuth 2.1 MCP (Per-User + Demo Sandbox!) ---
    @app.post("/api/kifli/login")
    async def start_kifli_login(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user.get("is_demo"):
            raise HTTPException(
                status_code=400,
                detail="Demo módban szimulált Kifli kosár fut. Saját Kifli fiók összekötéséhez regisztrálj saját fiókot!",
            )
        try:
            url = await get_kifli_for_user(_ws_id(user)).start_login_flow()
            return {"login_url": url}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/callback")
    async def complete_kifli_login(
        payload: KifliCallbackInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        try:
            return await get_kifli_for_user(_ws_id(user)).submit_callback_url(
                payload.callback_url
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/logout")
    async def logout_kifli(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user.get("is_demo"):
            return {"authenticated": True, "is_demo_sandbox": True}
        km = get_kifli_for_user(_ws_id(user))
        await km.logout()
        return await km.get_status()

    @app.get("/api/kifli/tools")
    async def list_kifli_tools(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> list[dict[str, Any]]:
        if user.get("is_demo"):
            return []
        try:
            return await get_kifli_for_user(_ws_id(user)).list_tools(force_refresh=True)
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

    async def _fetch_user_cart(user: dict[str, Any]) -> dict[str, Any]:
        if user.get("is_demo"):
            return demo_sandbox.get_cart()
        km = get_kifli_for_user(_ws_id(user))
        st = await km.get_status()
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
        raw = await km.call_tool_untruncated(
            "get_cart", {"context": "Display current shopping cart in home assistant UI"}
        )
        return _parse_kifli_cart_payload(raw)

    @app.get("/api/kifli/cart")
    async def get_live_kifli_cart(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        try:
            return await _fetch_user_cart(user)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/cart/update")
    async def update_live_kifli_cart_item(
        payload: CartItemUpdateInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        if user.get("is_demo"):
            return demo_sandbox.update_item(payload.product_id, payload.quantity)
        km = get_kifli_for_user(_ws_id(user))
        try:
            if payload.quantity <= 0:
                await km.call_tool_untruncated(
                    "remove_cart_item",
                    {"product_id": payload.product_id, "context": "User removed item from cart"},
                )
            else:
                await km.call_tool_untruncated(
                    "update_cart_item",
                    {
                        "product_id": payload.product_id,
                        "quantity": payload.quantity,
                        "context": "User adjusted item quantity in UI",
                    },
                )
            return await _fetch_user_cart(user)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/cart/clear")
    async def clear_live_kifli_cart(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        if user.get("is_demo"):
            return demo_sandbox.clear()
        km = get_kifli_for_user(_ws_id(user))
        try:
            await km.call_tool_untruncated(
                "clear_cart", {"context": "User requested clearing the shopping cart"}
            )
            return await _fetch_user_cart(user)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/cart/demo-reset")
    async def reset_demo_cart(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if not user.get("is_demo"):
            raise HTTPException(status_code=403, detail="Csak Demo módban elérhető.")
        return demo_sandbox.reset()

    @app.post("/api/kifli/cart/optimize-private-label")
    async def optimize_cart_private_label(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        uid = _ws_id(user)
        if user.get("is_demo"):
            return demo_sandbox.optimize_private_label(db=db, user_id=uid)
        km = get_kifli_for_user(uid)
        try:
            current_cart = await _fetch_user_cart(user)
            res = await optimize_cart_private_label_structured(
                db=db, kifli=km, agent=agent, parsed_cart=current_cart, user_id=uid
            )
            fresh_cart = await _fetch_user_cart(user) if res["auto_swapped"] else current_cart
            return {
                "cart": fresh_cart,
                "auto_swapped": res["auto_swapped"],
                "auto_savings_ft": res["auto_savings_ft"],
                "favorite_proposals": res["favorite_proposals"],
                "message": res["message"],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/kifli/cart/apply-swaps")
    async def apply_cart_swaps(
        payload: CartApplySwapsInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        if user.get("is_demo"):
            return demo_sandbox.apply_swaps([s.model_dump() for s in payload.swaps])
        km = get_kifli_for_user(_ws_id(user))
        try:
            applied = await execute_cart_swaps(km, [s.model_dump() for s in payload.swaps])
            fresh_cart = await _fetch_user_cart(user)
            return {"applied_count": len(applied), "cart": fresh_cart}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- Tervező Preferenciák ---
    @app.get("/api/planner-settings")
    async def get_planner_settings_api(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return db.get_planner_settings(user_id=_ws_id(user))

    @app.put("/api/planner-settings")
    async def update_planner_settings_api(
        payload: PlannerSettingsInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return db.update_planner_settings(
            payload.model_dump(exclude_none=True), user_id=_ws_id(user)
        )

    # --- 🧠 Smart Restock ---
    @app.get("/api/smart-restock")
    async def get_smart_restock_api(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        uid = _ws_id(user)
        if user.get("is_demo"):
            return {
                "kifli_connected": True,
                "kifli_orders_analyzed": 8,
                "local_events_analyzed": 4,
                "suggestions": [
                    {
                        "name": "Ubomi 100% Arabica szemes kávé 500 g",
                        "kifli_product_id": "99101",
                        "brand_hint": "Ubomi",
                        "source": "demo_orders",
                        "order_count": 4,
                        "avg_interval_days": 21.0,
                        "days_since_last": 23.0,
                        "due_ratio": 1.1,
                        "urgency": "overdue",
                        "reason": "Átlagosan 21 naponta veszed · 23 napja vetted utoljára",
                    },
                    {
                        "name": "Moddia 3 rétegű WC-papír 16 tekercs",
                        "kifli_product_id": "115386",
                        "brand_hint": "Moddia",
                        "source": "demo_orders",
                        "order_count": 5,
                        "avg_interval_days": 18.0,
                        "days_since_last": 16.0,
                        "due_ratio": 0.89,
                        "urgency": "soon",
                        "reason": "Átlagosan 18 naponta veszed · 16 napja vetted utoljára",
                    },
                ],
            }
        return await analyze_smart_restock(
            db=db, kifli=get_kifli_for_user(uid), user_id=uid
        )

    # --- 🔥 Páros Kaja Tinder Match ---
    @app.post("/api/tinder/sessions")
    async def create_tinder_session_api(
        payload: TinderSessionCreateInput, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        return db.create_tinder_session(
            meal_type=payload.meal_type,
            target_days=payload.target_days,
            owner_user_id=_ws_id(user),
        )

    @app.get("/api/tinder/sessions/{code}")
    async def get_tinder_session_api(
        code: str, _user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, Any]:
        try:
            return db.get_tinder_session(code)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/tinder/sessions/{code}/swipe")
    async def swipe_tinder_session_api(
        code: str,
        payload: TinderSwipeInput,
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            return db.record_tinder_swipe(
                code=code,
                user_slot=payload.user_slot,
                recipe_id=payload.recipe_id,
                decision=payload.decision,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/tinder/sessions/{code}/days")
    async def update_tinder_days_api(
        code: str,
        payload: TinderDaysUpdateInput,
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            return db.update_tinder_session_days(code, payload.target_days)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/tinder/sessions/{code}/accept")
    async def accept_tinder_match_api(
        code: str,
        payload: TinderAcceptMatchInput,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            return db.accept_tinder_match(
                code=code,
                recipe_id=payload.recipe_id,
                meal_type=payload.meal_type,
                requested_days=payload.days,
                actor_user_id=_ws_id(user),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
