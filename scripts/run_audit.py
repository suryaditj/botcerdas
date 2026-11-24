from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import requests

from config.loader import load_config
from data.twelve_data_client import TwelveDataClient
from engine.mtf_analyzer import MultiTimeframeAnalyzer
from telegram_bot.formatter import format_analysis_message
from utils.logger import setup_logger


def main() -> None:
    td_key = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("BROADCAST_CHAT_ID", "").strip()

    if not td_key or not tg_token:
        print("Secret belum lengkap, melewati eksekusi API.")
        return

    cfg = load_config(settings_path="config/settings.json", require_secrets=True)
    logger = setup_logger(name="gh_audit", log_dir=cfg.log_dir, level_name=cfg.log_level)
    client = TwelveDataClient(config=cfg, logger=logger)
    analyzer = MultiTimeframeAnalyzer(config=cfg, data_client=client, logger=logger)

    for sym in ("XAUUSD", "BTCUSD"):
        m_cfg = cfg.get_market(sym)
        for meth in ("SCALPING", "ENTRY_DAY"):
            out = analyzer.analyze(symbol=sym, method=meth, force_refresh=False)
            logger.info("AUDIT %s %s -> %s", sym, meth, out.status.value)
            if chat_id:
                msg = format_analysis_message(out, m_cfg)
                resp = requests.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg},
                    timeout=15,
                )
                resp.raise_for_status()


if __name__ == "__main__":
    main()
