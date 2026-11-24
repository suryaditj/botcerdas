from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from config.loader import load_config
from data.validator import Candle
from engine.backtester import run_walk_forward_backtest


def test_backtest_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "k")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    cfg = load_config("config/settings.json", require_secrets=True)

    start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    h1: List[Candle] = []
    m15: List[Candle] = []
    price = 2400.0

    for step in range(45):
        delta = 4.0 if (step % 4 != 3) else -1.5
        o, c = price, price + delta
        ts_h1 = start + timedelta(hours=step)
        h1.append(Candle(ts_h1, o, max(o, c) + 1.0, min(o, c) - 1.0, c, 100.0))
        for q in range(4):
            ts_m15 = ts_h1 + timedelta(minutes=15 * q)
            qo = o + ((c - o) * (q / 4.0))
            qc = o + ((c - o) * ((q + 1) / 4.0))
            m15.append(Candle(ts_m15, qo, max(qo, qc) + 0.5, min(qo, qc) - 0.5, qc, 25.0))
        price = c

    summary = run_walk_forward_backtest(cfg, "XAUUSD", "SCALPING", {"H1": h1, "M15": m15}, warmup_candles=20)
    assert summary.steps_evaluated > 0
