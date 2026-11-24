from __future__ import annotations

import signal
import sys
from typing import Optional

from telegram import Update
from telegram.ext import ApplicationBuilder

from config.loader import load_config
from data.twelve_data_client import TwelveDataClient
from engine.mtf_analyzer import MultiTimeframeAnalyzer
from telegram_bot.handlers import BotController, register_handlers
from utils.instance_lock import InstanceAlreadyRunningError, SingleInstanceLock
from utils.logger import setup_logger


def main() -> None:
    config = load_config(settings_path="config/settings.json", require_secrets=True)
    logger = setup_logger(
        name="mtf_bot",
        log_dir=config.log_dir,
        level_name=config.log_level,
    )

    lock_path = str(config.raw.get("bot", {}).get("lock_file", "logs/.bot_instance.lock"))
    lock = SingleInstanceLock(lock_path=lock_path)

    try:
        lock.acquire()
    except InstanceAlreadyRunningError as exc:
        logger.error("Bot batal jalan: %s", exc)
        sys.exit(1)

    def _stop(signum: int, _frame: Optional[object]) -> None:
        logger.info("Menerima sinyal %s, menghentikan bot...", signum)
        lock.release()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        client = TwelveDataClient(config=config, logger=logger)
        analyzer = MultiTimeframeAnalyzer(config=config, data_client=client, logger=logger)
        controller = BotController(config=config, analyzer=analyzer, logger=logger)

        app = ApplicationBuilder().token(config.telegram_bot_token).build()
        register_handlers(app, controller)

        logger.info(
            "Bot aktif | public_access=%s | markets=%s",
            config.public_access,
            list(config.markets.keys()),
        )
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
    finally:
        lock.release()


if __name__ == "__main__":
    main()
