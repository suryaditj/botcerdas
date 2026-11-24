from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

import requests

from config.loader import AppConfig
from data.candle_cache import CandleCache
from data.validator import ValidationReport, parse_raw_ohlcv_rows, validate_candles
from utils.time_utils import latest_closed_candle_open, to_twelve_data_interval


class TwelveDataAPIError(RuntimeError):
    """Error dari Twelve Data API."""


class TwelveDataRateLimitError(TwelveDataAPIError):
    """Error rate limit / kuota Twelve Data."""


class TwelveDataClient:
    def __init__(
        self,
        config: AppConfig,
        cache: Optional[CandleCache] = None,
        logger: Optional[logging.Logger] = None,
        session: Optional[requests.Session] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        api_cfg = config.raw.get("api", {})
        self.base_url: str = str(api_cfg.get("base_url", "https://api.twelvedata.com/time_series"))
        self.timeout_seconds: float = float(api_cfg.get("timeout_seconds", 15.0))
        self.max_retries: int = int(api_cfg.get("max_retries", 3))
        self.backoff_base_seconds: float = float(api_cfg.get("backoff_base_seconds", 1.5))
        self.default_outputsize: int = int(api_cfg.get("default_outputsize", 250))
        self.timezone_param: str = str(api_cfg.get("timezone", "UTC"))

        cache_ttl = int(config.raw.get("cache", {}).get("ttl_seconds", 60))
        self.cache = cache if cache is not None else CandleCache(ttl_seconds=cache_ttl)
        self.logger = logger or logging.getLogger("mtf_bot.twelve_data")
        self.session = session or requests.Session()
        self._sleep = sleep_fn

    def _request_raw_values(self, td_symbol: str, interval: str, outputsize: int) -> List[Dict[str, Any]]:
        if not self.config.twelve_data_api_key:
            raise TwelveDataAPIError("TWELVE_DATA_API_KEY belum diatur.")

        params = {
            "symbol": td_symbol,
            "interval": interval,
            "outputsize": outputsize,
            "timezone": self.timezone_param,
            "apikey": self.config.twelve_data_api_key,
            "order": "ASC",
        }

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(self.base_url, params=params, timeout=self.timeout_seconds)
                if resp.status_code == 429:
                    raise TwelveDataRateLimitError(
                        f"HTTP 429 Rate Limit pada {td_symbol} ({interval}) percobaan {attempt}."
                    )
                if resp.status_code >= 500:
                    raise TwelveDataAPIError(f"HTTP {resp.status_code} pada {td_symbol} ({interval}).")
                if resp.status_code != 200:
                    raise TwelveDataAPIError(
                        f"HTTP {resp.status_code} pada {td_symbol} ({interval}): {resp.text[:200]}"
                    )

                payload = resp.json()
                if isinstance(payload, dict) and str(payload.get("status", "")).lower() == "error":
                    code = str(payload.get("code", ""))
                    msg = str(payload.get("message", "Unknown Twelve Data error"))
                    if code == "429" or "rate limit" in msg.lower() or "api credits" in msg.lower():
                        raise TwelveDataRateLimitError(f"Twelve Data limit [{code}]: {msg}")
                    raise TwelveDataAPIError(f"Twelve Data error [{code}]: {msg}")

                values = payload.get("values") if isinstance(payload, dict) else None
                if not isinstance(values, list) or not values:
                    raise TwelveDataAPIError(f"Data OHLCV kosong untuk {td_symbol} ({interval}).")

                return values

            except TwelveDataRateLimitError as exc:
                last_error = exc
                wait_sec = self.backoff_base_seconds * (2 ** (attempt - 1)) + 1.0
                self.logger.warning("Rate limit: %s. Menunggu %.1fs...", exc, wait_sec)
                if attempt < self.max_retries:
                    self._sleep(wait_sec)
            except (requests.RequestException, ValueError, TwelveDataAPIError) as exc:
                last_error = exc
                wait_sec = self.backoff_base_seconds * (2 ** (attempt - 1))
                self.logger.warning(
                    "Gagal fetch %s (%s) percobaan %d/%d: %s",
                    td_symbol,
                    interval,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    self._sleep(wait_sec)

        raise TwelveDataAPIError(
            f"Gagal mengambil data {td_symbol} ({interval}) setelah {self.max_retries} percobaan: {last_error}"
        )

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        outputsize: Optional[int] = None,
        force_refresh: bool = False,
    ) -> ValidationReport:
        market_cfg = self.config.get_market(symbol)
        tf_upper = timeframe.upper()
        interval = to_twelve_data_interval(tf_upper)
        expected_closed = latest_closed_candle_open(tf_upper)

        val_cfg = self.config.raw.get("validation", {})
        min_candles = int(val_cfg.get("min_candles", 60))
        max_gap_tolerance = int(val_cfg.get("max_gap_tolerance", 3))
        max_stale_multiplier = float(val_cfg.get("max_stale_multiplier", 2.0))

        if not force_refresh:
            cached = self.cache.get(
                symbol=market_cfg.symbol,
                timeframe=tf_upper,
                expected_latest_closed_ts=expected_closed,
            )
            if cached is not None:
                return validate_candles(
                    raw_candles=cached,
                    timeframe=tf_upper,
                    min_candles=min_candles,
                    max_gap_tolerance=max_gap_tolerance,
                    max_stale_multiplier=max_stale_multiplier,
                )

        size = int(outputsize or self.default_outputsize)
        raw_rows = self._request_raw_values(
            td_symbol=market_cfg.twelve_data_symbol,
            interval=interval,
            outputsize=size,
        )
        parsed = parse_raw_ohlcv_rows(raw_rows, timeframe=tf_upper)
        report = validate_candles(
            raw_candles=parsed,
            timeframe=tf_upper,
            min_candles=min_candles,
            max_gap_tolerance=max_gap_tolerance,
            max_stale_multiplier=max_stale_multiplier,
        )

        if report.candles:
            self.cache.set(
                symbol=market_cfg.symbol,
                timeframe=tf_upper,
                candles=report.candles,
            )

        return report
