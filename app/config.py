from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    llm_base_url: str | None
    llm_api_key: str
    llm_model: str
    kifli_mcp_url: str
    kifli_oauth_redirect_uri: str
    telegram_bot_token: str
    telegram_allowed_user_ids: tuple[int, ...]
    timezone: str
    weekly_cron_day: str
    weekly_cron_hour: int
    weekly_cron_minute: int
    app_access_pin: str
    mcp_access_token: str
    app_secret_key: str
    invite_code: str
    demo_mode_enabled: bool
    demo_daily_ai_limit: int
    server_fallback_daily_ai_limit: int
    auth_required: bool
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    allowed_google_emails: tuple[str, ...]
    data_dir: Path
    port: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kifli_otthon.db"

    @property
    def kifli_oauth_dir(self) -> Path:
        return self.data_dir / "kifli_oauth"


def load_settings() -> Settings:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider == "gemini":
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
    elif provider == "openai":
        base_url = None
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
    else:
        base_url = os.getenv("CUSTOM_LLM_BASE_URL", "http://localhost:11434/v1").strip()
        api_key = os.getenv("CUSTOM_LLM_API_KEY", "ollama").strip()
        model = os.getenv("CUSTOM_LLM_MODEL", "qwen2.5:14b").strip()

    raw_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    allowed_ids: list[int] = []
    for part in raw_ids.split(","):
        part = part.strip()
        if part.isdigit():
            allowed_ids.append(int(part))

    raw_google_emails = os.getenv("ALLOWED_GOOGLE_EMAILS", "").strip()
    allowed_google = tuple(
        e.strip().lower() for e in raw_google_emails.split(",") if e.strip()
    )

    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        llm_provider=provider,
        llm_base_url=base_url,
        llm_api_key=api_key,
        llm_model=model,
        kifli_mcp_url=os.getenv("KIFLI_MCP_URL", "https://mcp.kifli.hu/mcp").strip(),
        kifli_oauth_redirect_uri=os.getenv(
            "KIFLI_OAUTH_REDIRECT_URI", "http://localhost:3334/oauth/callback"
        ).strip(),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_allowed_user_ids=tuple(allowed_ids),
        timezone=os.getenv("TIMEZONE", "Europe/Budapest").strip(),
        weekly_cron_day=os.getenv("WEEKLY_MENU_CRON_DAY", "mon").strip(),
        weekly_cron_hour=int(os.getenv("WEEKLY_MENU_CRON_HOUR", "8")),
        weekly_cron_minute=int(os.getenv("WEEKLY_MENU_CRON_MINUTE", "0")),
        app_access_pin=os.getenv("APP_ACCESS_PIN", "").strip(),
        mcp_access_token=(
            os.getenv("MCP_ACCESS_TOKEN", "").strip()
            or os.getenv("APP_ACCESS_PIN", "").strip()
        ),
        app_secret_key=os.getenv("APP_SECRET_KEY", "").strip(),
        invite_code=os.getenv("INVITE_CODE", "").strip(),
        demo_mode_enabled=os.getenv("DEMO_MODE_ENABLED", "true").strip().lower()
        not in ("0", "false", "no"),
        demo_daily_ai_limit=int(os.getenv("DEMO_DAILY_AI_LIMIT", "8")),
        server_fallback_daily_ai_limit=int(os.getenv("SERVER_FALLBACK_DAILY_AI_LIMIT", "15")),
        auth_required=os.getenv("AUTH_REQUIRED", "true").strip().lower()
        not in ("0", "false", "no"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        google_redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", "").strip(),
        allowed_google_emails=allowed_google,
        data_dir=data_dir,
        port=int(os.getenv("PORT", "8085")),
    )
