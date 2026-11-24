from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Set

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from config.loader import AppConfig
from engine.mtf_analyzer import MultiTimeframeAnalyzer
from telegram_bot.formatter import format_analysis_message
from telegram_bot.keyboards import (
    CB_CHG_MKT,
    CB_CHG_METH,
    CB_HOME,
    CB_METH_EDAY,
    CB_METH_SCALP,
    CB_MKT_BTC,
    CB_MKT_XAU,
    CB_REFRESH,
    build_analysis_result_keyboard,
    build_main_menu_keyboard,
    build_method_menu_keyboard,
)


@dataclass
class UserSession:
    selected_symbol: Optional[str] = None
    selected_method: Optional[str] = None
    last_analysis_chat_id: Optional[int] = None
    last_analysis_message_id: Optional[int] = None


class BotController:
    def __init__(
        self,
        config: AppConfig,
        analyzer: MultiTimeframeAnalyzer,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self.analyzer = analyzer
        self.logger = logger or logging.getLogger("mtf_bot.handlers")
        self.sessions: Dict[int, UserSession] = {}
        self._inflight: Set[str] = set()

    def is_authorized(self, user_id: Optional[int]) -> bool:
        if user_id is None:
            return False
        if self.config.public_access:
            return True
        return user_id in self.config.allowed_user_ids

    def get_session(self, user_id: int) -> UserSession:
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession()
        return self.sessions[user_id]

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        user_id = user.id if user else None
        if not self.is_authorized(user_id):
            if update.message:
                await update.message.reply_text("Akses ditolak.")
            return

        assert user_id is not None
        session = self.get_session(user_id)
        session.selected_symbol = None
        session.selected_method = None

        if update.message:
            await update.message.reply_text("PILIH MARKET", reply_markup=build_main_menu_keyboard())

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return

        user = query.from_user
        user_id = user.id if user else None
        if not self.is_authorized(user_id):
            await query.answer("Akses ditolak.", show_alert=True)
            return

        assert user_id is not None
        msg_id = query.message.message_id if query.message else 0
        cb_key = f"{user_id}:{msg_id}:{query.data}"
        if cb_key in self._inflight:
            await query.answer("Sedang diproses...")
            return

        self._inflight.add(cb_key)
        try:
            await query.answer()
            data = query.data or ""
            session = self.get_session(user_id)

            if data in {CB_HOME, CB_CHG_MKT}:
                session.selected_symbol = None
                session.selected_method = None
                if query.message:
                    await query.message.reply_text("PILIH MARKET", reply_markup=build_main_menu_keyboard())
                return

            if data in {CB_MKT_XAU, CB_MKT_BTC}:
                session.selected_symbol = "XAUUSD" if data == CB_MKT_XAU else "BTCUSD"
                session.selected_method = None
                if query.message:
                    await query.message.reply_text(
                        f"Market terpilih: {session.selected_symbol}\n\nPILIH METODE ANALISA",
                        reply_markup=build_method_menu_keyboard(),
                    )
                return

            if data == CB_CHG_METH:
                if not session.selected_symbol:
                    if query.message:
                        await query.message.reply_text("PILIH MARKET", reply_markup=build_main_menu_keyboard())
                    return
                if query.message:
                    await query.message.reply_text(
                        f"Market: {session.selected_symbol}\n\nPILIH METODE ANALISA",
                        reply_markup=build_method_menu_keyboard(),
                    )
                return

            if data in {CB_METH_SCALP, CB_METH_EDAY}:
                if not session.selected_symbol:
                    if query.message:
                        await query.message.reply_text(
                            "Silakan pilih market dulu.\n\nPILIH MARKET",
                            reply_markup=build_main_menu_keyboard(),
                        )
                    return
                session.selected_method = "SCALPING" if data == CB_METH_SCALP else "ENTRY_DAY"
                await self._send_or_edit_analysis(
                    context=context,
                    session=session,
                    fallback_chat_id=query.message.chat_id if query.message else None,
                    force_refresh=False,
                    edit_existing=False,
                )
                return

            if data == CB_REFRESH:
                if not session.selected_symbol or not session.selected_method:
                    if query.message:
                        await query.message.reply_text("PILIH MARKET", reply_markup=build_main_menu_keyboard())
                    return
                await self._send_or_edit_analysis(
                    context=context,
                    session=session,
                    fallback_chat_id=query.message.chat_id if query.message else None,
                    force_refresh=True,
                    edit_existing=True,
                )
                return

        except Exception as exc:
            self.logger.exception("Error callback '%s' user %s: %s", query.data, user_id, exc)
            if query.message:
                await query.message.reply_text(
                    "Terjadi kendala saat menjalankan analisa. Silakan coba lagi.",
                    reply_markup=build_main_menu_keyboard(),
                )
        finally:
            self._inflight.discard(cb_key)

    async def _send_or_edit_analysis(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        session: UserSession,
        fallback_chat_id: Optional[int],
        force_refresh: bool,
        edit_existing: bool,
    ) -> None:
        assert session.selected_symbol is not None
        assert session.selected_method is not None

        market_cfg = self.config.get_market(session.selected_symbol)
        output = await asyncio.to_thread(
            self.analyzer.analyze,
            symbol=session.selected_symbol,
            method=session.selected_method,
            force_refresh=force_refresh,
        )
        text = format_analysis_message(output, market_cfg)
        markup = build_analysis_result_keyboard()

        if (
            edit_existing
            and session.last_analysis_chat_id is not None
            and session.last_analysis_message_id is not None
        ):
            try:
                await context.bot.edit_message_text(
                    chat_id=session.last_analysis_chat_id,
                    message_id=session.last_analysis_message_id,
                    text=text,
                    reply_markup=markup,
                )
                return
            except BadRequest as exc:
                if "Message is not modified" in str(exc):
                    return
                self.logger.warning("Gagal edit pesan lama: %s", exc)

        target_chat = fallback_chat_id or session.last_analysis_chat_id
        if target_chat is not None:
            sent = await context.bot.send_message(chat_id=target_chat, text=text, reply_markup=markup)
            session.last_analysis_chat_id = sent.chat_id
            session.last_analysis_message_id = sent.message_id


def register_handlers(app: Application, controller: BotController) -> None:
    app.add_handler(CommandHandler("start", controller.cmd_start))
    app.add_handler(CallbackQueryHandler(controller.handle_callback))
