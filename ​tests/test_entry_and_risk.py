from __future__ import annotations

from datetime import datetime, timedelta, timezone

from analysis.entry_confirmation import evaluate_entry_confirmation
from analysis.snr_snd_detector import PriceZone, TradeSide, ZoneKind, ZonePattern, ZoneStatus
from config.loader import MarketConfig
from data.validator import Candle
from engine.risk_manager import build_trade_setup


def _c(i: int, o: float, h: float, l: float, c: float) -> Candle:
    t0 = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    return Candle(t0 + timedelta(minutes=15 * i), o, h, l, c, 50.0)


def test_confirmation_and_risk() -> None:
    conf_cfg = {
        "min_confirmation_score": 1.5,
        "weights": {
            "rejection_pin_bar": 1.5,
            "engulfing": 1.5,
            "strong_displacement": 1.5,
            "momentum_candle": 1.0,
        },
    }
    candles = [
        _c(0, 100.0, 101.0, 99.0, 100.5),
        _c(1, 100.5, 101.5, 99.5, 101.0),
        _c(2, 101.5, 102.0, 99.8, 100.0),
        _c(3, 99.9, 102.6, 99.7, 102.3),
    ]
    conf = evaluate_entry_confirmation(candles, TradeSide.BUY, conf_cfg)
    assert conf.confirmed is True

    m_cfg = MarketConfig("XAUUSD", "XAU/USD", 2, 0.01, 10)
    zone = PriceZone(
        "H1_DBR_1_2",
        ZoneKind.DEMAND,
        ZonePattern.DBR,
        "H1",
        2505.00,
        2500.00,
        datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        2,
        TradeSide.BUY,
        ZoneStatus.FRESH,
        0,
        2.0,
        80.0,
    )
    setup = build_trade_setup(
        TradeSide.BUY,
        zone,
        [_c(0, 2501.0, 2504.0, 2500.5, 2503.50)],
        [],
        m_cfg,
        {"min_rr_ratio": 1.5, "tp2_fallback_rr_mult": 2.5, "sl_atr_buffer_mult": 0.1},
        1.0,
    )
    assert setup.valid is True
    assert setup.rr_ratio >= 1.5
