from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import Settings
from app.db import Database
from app.kifli_mcp import KifliMCPManager
from app.llm_agent import ChefShoppingAgent

log = logging.getLogger("kifli_otthon.bot")


class BotAndSchedulerRuntime:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        kifli: KifliMCPManager,
        agent: ChefShoppingAgent,
    ) -> None:
        self.settings = settings
        self.db = db
        self.kifli = kifli
        self.agent = agent
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self.tg_app: Application | None = None

    def _is_allowed_user(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        if not self.settings.telegram_allowed_user_ids:
            log.warning(
                "TELEGRAM_ALLOWED_USER_IDS üres! Biztonsági okból elutasítva (user_id=%s). Írd be a .env-be!",
                user_id,
            )
            return False
        return user_id in self.settings.telegram_allowed_user_ids

    def _order_confirm_keyboard(self) -> InlineKeyboardMarkup | None:
        in_cart = [
            g for g in self.db.list_general_items(include_ordered=False) if g["status"] == "IN_CART"
        ]
        if not in_cart:
            return None
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"✅ Megrendeltem a Kiflin ({len(in_cart)} db Egyéb tétel törlése)",
                        callback_data="confirm_kifli_order",
                    )
                ]
            ]
        )

    async def start(self) -> None:
        self.scheduler.add_job(
            self.run_monday_menu_job,
            CronTrigger(
                day_of_week=self.settings.weekly_cron_day,
                hour=self.settings.weekly_cron_hour,
                minute=self.settings.weekly_cron_minute,
                timezone=self.settings.timezone,
            ),
            id="weekly_monday_menu",
            replace_existing=True,
        )
        self.scheduler.start()
        log.info(
            "Heti menü ütemező elindítva (%s %02d:%02d %s)",
            self.settings.weekly_cron_day,
            self.settings.weekly_cron_hour,
            self.settings.weekly_cron_minute,
            self.settings.timezone,
        )

        if self.settings.telegram_bot_token:
            self.tg_app = Application.builder().token(self.settings.telegram_bot_token).build()
            self.tg_app.add_handler(CommandHandler("start", self._cmd_start))
            self.tg_app.add_handler(CommandHandler("menu", self._cmd_menu))
            self.tg_app.add_handler(CommandHandler("lista", self._cmd_lista))
            self.tg_app.add_handler(CommandHandler("megrendeltem", self._cmd_megrendeltem))
            self.tg_app.add_handler(CommandHandler("kifli_login", self._cmd_kifli_login))
            self.tg_app.add_handler(CommandHandler("kifli_callback", self._cmd_kifli_callback))
            self.tg_app.add_handler(CallbackQueryHandler(self._on_callback_button))
            self.tg_app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text_message)
            )
            await self.tg_app.initialize()
            await self.tg_app.start()
            if self.tg_app.updater:
                await self.tg_app.updater.start_polling(drop_pending_updates=True)
            log.info("Privát Telegram Bot polling elindítva.")

    async def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        if self.tg_app:
            if self.tg_app.updater and self.tg_app.updater.running:
                await self.tg_app.updater.stop()
            await self.tg_app.stop()
            await self.tg_app.shutdown()

    async def broadcast_to_owners(self, text: str) -> None:
        if not self.tg_app or not self.settings.telegram_allowed_user_ids:
            return
        kb = self._order_confirm_keyboard()
        for uid in self.settings.telegram_allowed_user_ids:
            try:
                await self._send_chunked(uid, text, reply_markup=kb)
            except Exception as exc:
                log.warning("Telegram küldési hiba (%s): %s", uid, exc)

    async def _send_chunked(
        self, chat_id: int, text: str, reply_markup: Any = None
    ) -> None:
        assert self.tg_app is not None
        chunk_size = 3900
        parts = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or [text]
        for idx, part in enumerate(parts):
            markup = reply_markup if idx == len(parts) - 1 else None
            await self.tg_app.bot.send_message(chat_id=chat_id, text=part, reply_markup=markup)

    async def run_monday_menu_job(self) -> str:
        log.info("Hétfő reggeli automatikus menütervezés indítása...")
        proposal = await self.agent.generate_monday_weekly_proposal()
        await self.broadcast_to_owners(f"☀️ Jó reggelt! Íme az eheti menütervezet:\n\n{proposal}")
        return proposal

    # -------------------------------------------------------------------------
    # Telegram handlerek
    # -------------------------------------------------------------------------
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else None
        if not self._is_allowed_user(uid):
            if update.message:
                await update.message.reply_text(
                    f"⛔ Hozzáférés megtagadva. A te Telegram ID-d: {uid} (ezt írd be a .env TELEGRAM_ALLOWED_USER_IDS mezőjébe)."
                )
            return
        await update.message.reply_text(
            "👋 Szia! Én vagyok az otthoni Kifli Séf & Bevásárló-Asszisztensed.\n\n"
            "Parancsok:\n"
            "• /menu – Új heti menü + 1 ajánlás generálása most\n"
            "• /lista – Összesített bevásárlólista és Általános tételek\n"
            "• /megrendeltem – Kosárba tett Általános tételek végleges törlése\n"
            "• /kifli_login – Kifli.hu OAuth belépési link kérése\n\n"
            "Vagy csak írj bármit simán magyarul, pl.:\n"
            "„Kedd ebédre inkább krumplifőzeléket kívántam meg, adj még hozzá 2 tejet és rakd össze a Kifli kosarat!”"
        )

    async def _cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed_user(update.effective_user.id if update.effective_user else None):
            return
        assert update.message is not None
        await update.message.reply_text("👨‍🍳 Pillanat, összeállítom a heti menüt és a +1 ajánlást...")
        reply = await self.agent.generate_monday_weekly_proposal()
        await self._send_chunked(
            update.message.chat_id, reply, reply_markup=self._order_confirm_keyboard()
        )

    async def _cmd_lista(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed_user(update.effective_user.id if update.effective_user else None):
            return
        assert update.message is not None
        agg = self.db.aggregate_shopping_list()
        lines = [f"🛒 Összesített lista ({agg['week_start']}):"]
        lines.append("\n🍲 Receptekből + extrákból:")
        for item in agg["recipe_and_adhoc_items"] or []:
            brand = f" [{item['brand_hint']}]" if item.get("brand_hint") else ""
            lines.append(f"  • {item['name']}: {item['quantity']} {item['unit']}{brand}")
        if not agg["recipe_and_adhoc_items"]:
            lines.append("  (még üres)")

        lines.append("\n🧻 Általános / Háztartási (PENDING):")
        for g in agg["general_pending_items"] or []:
            brand = f" ({g['brand_hint']})" if g.get("brand_hint") else ""
            lines.append(f"  • {g['name']}: {g['quantity']} {g['unit']}{brand}")
        if not agg["general_pending_items"]:
            lines.append("  (nincs függő tétel)")

        if agg["general_already_in_cart"]:
            lines.append("\n🧺 Már Kifli kosárba téve (rendelésre vár):")
            for g in agg["general_already_in_cart"]:
                lines.append(f"  • {g['name']} -> {g['kifli_product_name'] or 'kosárban'}")

        if agg["staples_assumed_at_home"]:
            lines.append("\n🧂 Kamra-alapanyagok (kihagyva): " + ", ".join(agg["staples_assumed_at_home"]))

        await self._send_chunked(
            update.message.chat_id, "\n".join(lines), reply_markup=self._order_confirm_keyboard()
        )

    async def _cmd_megrendeltem(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed_user(update.effective_user.id if update.effective_user else None):
            return
        assert update.message is not None
        res = self.db.finalize_order_and_clear_general_items()
        await update.message.reply_text(
            f"✅ Szuper! {res['cleared_count']} db kosárba tett Általános tételt végleg lezártam/töröltem, "
            "így jövő héten biztosan nem rendeli újra!"
        )

    async def _cmd_kifli_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed_user(update.effective_user.id if update.effective_user else None):
            return
        assert update.message is not None
        url = await self.kifli.start_login_flow()
        await update.message.reply_text(
            f"🔐 1. Nyisd meg ezt a Kifli belépési linket:\n{url}\n\n"
            "2. Belépés után a böngésző egy 'http://localhost:3334/oauth/callback?code=...' címre irányít "
            "(ami nem tölt be — ez normális!). Másold ki a teljes címsort, és küldd vissza így:\n"
            "/kifli_callback http://localhost:3334/oauth/callback?code=..."
        )

    async def _cmd_kifli_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed_user(update.effective_user.id if update.effective_user else None):
            return
        assert update.message is not None
        if not context.args:
            await update.message.reply_text("Használat: /kifli_callback <teljes_localhost_url>")
            return
        st = await self.kifli.submit_callback_url(context.args[0])
        await update.message.reply_text(
            f"🎉 Kifli.hu MCP sikeresen összekötve! Elérhető eszközök: {st['cached_tool_count']} db."
        )

    async def _on_callback_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not self._is_allowed_user(query.from_user.id if query.from_user else None):
            return
        await query.answer()
        if query.data == "confirm_kifli_order":
            res = self.db.finalize_order_and_clear_general_items()
            await query.edit_message_reply_markup(reply_markup=None)
            if query.message:
                await query.message.reply_text(
                    f"✅ Rendelés rögzítve! {res['cleared_count']} db Általános/Háztartási tétel törölve a listáról (nem fog loopolni)."
                )

    async def _on_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed_user(update.effective_user.id if update.effective_user else None):
            return
        if not update.message or not update.message.text:
            return
        await update.message.chat.send_action("typing")
        try:
            reply = await self.agent.chat(update.message.text, source="telegram")
            await self._send_chunked(
                update.message.chat_id, reply, reply_markup=self._order_confirm_keyboard()
            )
        except Exception as exc:
            log.exception("Telegram AI chat hiba")
            await update.message.reply_text(f"⚠️ Hiba történt: {exc}")
