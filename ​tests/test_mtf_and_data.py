from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from config.loader import load_config
from data.twelve_data_client import TwelveDataAPIError, TwelveDataClient
from data.validator import Candle, parse_raw_ohlcv_rows, validate_candles
from engine.mtf_analyzer import AnalysisStatus, MultiTimeframeAnalyzer


class _Resp:
    def __init__(self, code: int, payload: Dict[str, Any]) -> None:
        self.status_code = code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> Dict[str, Any]:
        return self._payload


class _Sess:
    def __init__(self, items: List[_Resp]) -> None:
        self._items = list(items)

    def get(self, url: str, params: Dict[str, Any], timeout: float) -> _Resp:
        return self._items.pop(0) if self._items else _Resp(200, {"status": "ok", "values": []})


def test_validator_and_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "k")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("PUBLIC_ACCESS", "true")

    now = datetime(2026, 4, 10, 12, 30, tzinfo=timezone.utc)
    rows = [
        {"datetime": "2026-04-10 10:00:00", "open": "100", "high": "102", "low": "99", "close": "101"},
        {"datetime": "2026-04-10 10:00:00", "open": "100", "high": "102", "low": "99", "close": "101.2"},
        {"datetime": "2026-04-10 11:00:00", "open": "101.2", "high": "104", "low": "101", "close": "103.5"},
        {"datetime": "2026-04-10 12:00:00", "open": "103.5", "high": "105", "low": "103", "close": "104"},
    ]
    parsed = parse_raw_ohlcv_rows(rows, "H1")
    rep = validate_candles(parsed, "H1", min_candles=2, max_gap_tolerance=2, now_utc=now)
    assert rep.dropped_unclosed == 1
    assert rep.duplicates_removed == 1
    assert rep.is_sufficient is True

    cfg = load_config("config/settings.json", require_secrets=True)
    client = TwelveDataClient(
        cfg,
        session=_Sess([_Resp(429, {"status": "error", "code": "429", "message": "limit"})] * 3),
        sleep_fn=lambda _s: None,
    )
    with pytest.raises(TwelveDataAPIError):
        client._request_raw_values("XAU/USD", "1h", 100)


def test_mtf_no_trade_on_flat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "k")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    cfg = load_config("config/settings.json", require_secrets=True)
    analyzer = MultiTimeframeAnalyzer(cfg, data_client=None)

    h1 = [
        Candle(datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc) + timedelta(hours=i), 2500.0, 2501.0, 2499.0, 2500.0, 10.0)
        for i in range(40)
    ]
    m15 = [
        Candle(datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=15 * i), 2500.0, 2501.0, 2499.0, 2500.0, 10.0)
        for i in range(40)
    ]
    out = analyzer.evaluate_from_candle_map("XAUUSD", "SCALPING", {"H1": h1, "M15": m15})
    assert out.status == AnalysisStatus.NO_TRADE
