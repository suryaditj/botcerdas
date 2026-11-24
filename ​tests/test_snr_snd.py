from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from analysis.snr_snd_detector import ZonePattern, ZoneStatus, analyze_snr_snd, detect_snd_zones
from data.validator import Candle


def _make(rows: List[tuple[float, float, float, float]]) -> List[Candle]:
    start = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    return [Candle(start + timedelta(hours=i), o, h, l, c, 200.0) for i, (o, h, l, c) in enumerate(rows)]


def test_dbr_lifecycle_fresh_tested_invalid() -> None:
    cfg = {
        "atr_period": 5,
        "max_base_candles": 2,
        "min_leg_atr_mult": 1.0,
        "min_departure_atr_mult": 1.2,
        "max_zone_atr_mult": 3.0,
        "max_base_body_to_atr": 1.2,
        "snr_band_atr_mult": 0.25,
        "min_quality_score": 40.0,
        "max_active_per_side": 3,
    }
    rows = [
        (100.0, 102.0, 99.5, 101.5),
        (101.5, 103.5, 101.0, 103.0),
        (103.0, 105.0, 102.5, 104.5),
        (104.5, 106.0, 104.0, 105.5),
        (105.5, 107.0, 105.0, 106.5),
        (106.5, 106.8, 101.5, 102.0),
        (102.0, 102.4, 101.2, 101.8),
        (101.8, 111.0, 101.7, 110.5),
        (110.5, 113.0, 110.0, 112.5),
    ]
    z_fresh = [z for z in detect_snd_zones(_make(rows), "H1", cfg) if z.pattern == ZonePattern.DBR]
    assert z_fresh and z_fresh[0].status == ZoneStatus.FRESH

    z_tested = [
        z for z in detect_snd_zones(_make(rows + [(112.5, 112.8, 101.6, 103.0)]), "H1", cfg)
        if z.pattern == ZonePattern.DBR
    ]
    assert z_tested and z_tested[0].status == ZoneStatus.TESTED

    after_break = analyze_snr_snd(_make(rows + [(112.5, 112.8, 101.6, 103.0), (103.0, 103.2, 95.0, 96.0)]), "H1", cfg)
    assert all(z.pattern != ZonePattern.DBR for z in after_break.active_buy_zones)
