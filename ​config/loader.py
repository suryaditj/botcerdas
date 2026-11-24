from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set

from utils.time_utils import TIMEFRAME_MINUTES


@dataclass(frozen=True)
class MarketConfig:
    symbol: str
    twelve_data_symbol: str
    price_precision: int
    tick_size: float
    default_sl_buffer_ticks: int


@dataclass(frozen=True)
class AppConfig:
    twelve_data_api_key: str
    telegram_bot_token: str
    public_access: bool
    allowed_user_ids: Set[int]
    log_level: str
    log_dir: str
    raw: Dict[str, Any]
    markets: Dict[str, MarketConfig]

    def get_market(self, symbol: str) -> MarketConfig:
        key = symbol.upper()
        if key not in self.markets:
            raise ValueError(f"Market tidak didukung: {symbol}")
        return self.markets[key]

    def get_method_timeframes(self, method: str) -> List[str]:
        method_key = method.upper()
        methods_cfg = self.raw.get("methods", {})
        if method_key not in methods_cfg:
            raise ValueError(f"Metode analisa tidak dikenal: {method}")
        tfs = [str(tf).upper() for tf in methods_cfg[method_key].get("timeframes", [])]
        for tf in tfs:
            if tf not in TIMEFRAME_MINUTES:
                raise ValueError(f"Timeframe '{tf}' pada metode '{method_key}' tidak valid.")
        return tfs


def _parse_user_ids(raw_val: str | None) -> Set[int]:
    if not raw_val:
        return set()
    result: Set[int] = set()
    for part in raw_val.split(","):
        cleaned = part.strip()
        if cleaned:
            result.add(int(cleaned))
    return result


def _validate_settings(cfg: Dict[str, Any]) -> None:
    expected_markets = {"XAUUSD", "BTCUSD"}
    markets_cfg = cfg.get("markets", {})
    if set(markets_cfg.keys()) != expected_markets:
        raise ValueError(
            f"Market harus tepat {sorted(expected_markets)}, ditemukan: {sorted(markets_cfg.keys())}"
        )

    for sym, m_cfg in markets_cfg.items():
        if int(m_cfg.get("price_precision", -1)) < 0:
            raise ValueError(f"price_precision untuk {sym} harus >= 0")
        if float(m_cfg.get("tick_size", 0.0)) <= 0.0:
            raise ValueError(f"tick_size untuk {sym} harus > 0")

    max_active = int(cfg.get("zones", {}).get("max_active_per_side", 0))
    if max_active < 1 or max_active > 3:
        raise ValueError("max_active_per_side harus antara 1 dan 3.")

    min_rrr = float(cfg.get("risk", {}).get("min_rr_ratio", 0.0))
    if min_rrr <= 0.0:
        raise ValueError("min_rr_ratio harus > 0.")


def load_config(
    settings_path: str = "config/settings.json",
    require_secrets: bool = True,
) -> AppConfig:
    path = Path(settings_path)
    if not path.exists():
        raise FileNotFoundError(f"File konfigurasi tidak ditemukan: {settings_path}")

    with path.open("r", encoding="utf-8") as fh:
        raw_cfg: Dict[str, Any] = json.load(fh)

    _validate_settings(raw_cfg)

    td_api_key = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    allowed_users = _parse_user_ids(os.environ.get("ALLOWED_USER_IDS", ""))

    if require_secrets:
        if not td_api_key:
            raise ValueError("Environment variable TWELVE_DATA_API_KEY wajib diisi.")
        if not tg_token:
            raise ValueError("Environment variable TELEGRAM_BOT_TOKEN wajib diisi.")

    bot_cfg = raw_cfg.get("bot", {})
    public_default = bool(bot_cfg.get("public_access", True))
    env_public = os.environ.get("PUBLIC_ACCESS", "").strip().lower()
    if env_public in {"1", "true", "yes"}:
        public_access = True
    elif env_public in {"0", "false", "no"}:
        public_access = False
    else:
        public_access = public_default

    log_level = os.environ.get("LOG_LEVEL", bot_cfg.get("log_level", "INFO")).strip()
    log_dir = os.environ.get("LOG_DIR", bot_cfg.get("log_dir", "logs")).strip()

    markets: Dict[str, MarketConfig] = {}
    for sym, m_data in raw_cfg["markets"].items():
        markets[sym.upper()] = MarketConfig(
            symbol=sym.upper(),
            twelve_data_symbol=str(m_data["twelve_data_symbol"]),
            price_precision=int(m_data["price_precision"]),
            tick_size=float(m_data["tick_size"]),
            default_sl_buffer_ticks=int(m_data.get("sl_buffer_ticks", 5)),
        )

    return AppConfig(
        twelve_data_api_key=td_api_key,
        telegram_bot_token=tg_token,
        public_access=public_access,
        allowed_user_ids=allowed_users,
        log_level=log_level,
        log_dir=log_dir,
        raw=raw_cfg,
        markets=markets,
    )
