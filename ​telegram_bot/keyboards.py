from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CB_HOME = "home"
CB_MKT_XAU = "mkt:XAUUSD"
CB_MKT_BTC = "mkt:BTCUSD"
CB_METH_SCALP = "meth:SCALPING"
CB_METH_EDAY = "meth:ENTRY_DAY"
CB_REFRESH = "act:refresh"
CB_CHG_METH = "act:chgm"
CB_CHG_MKT = "act:chgmkt"


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🪙 XAUUSD", callback_data=CB_MKT_XAU),
                InlineKeyboardButton("💰 BTCUSD", callback_data=CB_MKT_BTC),
            ]
        ]
    )


def build_method_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔥 SCALPING H1 + M15 🔥", callback_data=CB_METH_SCALP)],
            [InlineKeyboardButton("🔰 ENTRY DAY H4 + H1 + M5 🔰", callback_data=CB_METH_EDAY)],
            [
                InlineKeyboardButton("📊 Ganti Market", callback_data=CB_CHG_MKT),
                InlineKeyboardButton("🏠 Menu Utama", callback_data=CB_HOME),
            ],
        ]
    )


def build_analysis_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Refresh Analisa", callback_data=CB_REFRESH),
                InlineKeyboardButton("🔁 Ganti Metode", callback_data=CB_CHG_METH),
            ],
            [
                InlineKeyboardButton("📊 Ganti Market", callback_data=CB_CHG_MKT),
                InlineKeyboardButton("🏠 Menu Utama", callback_data=CB_HOME),
            ],
        ]
    )
