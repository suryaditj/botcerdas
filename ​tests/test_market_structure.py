from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from analysis.market_structure import StructureBreakType, TrendDirection, analyze_market_structure
from data.validator import Candle


def _series(rows: List[tuple[float, float, float, float]]) -> List[Candle]:
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    return [
        Candle(base + timedelta(hours=i), o, h, l, c, 100.0)
        for i, (o, h, l, c) in enumerate(rows)
    ]


def test_bullish_bos_close() -> None:
    rows = [
        (100.0, 102.0, 99.0, 101.0),
        (101.0, 104.0, 100.5, 103.5),
        (103.5, 106.0, 103.0, 105.0),
        (105.0, 104.5, 101.5, 102.0),
        (102.0, 104.0, 101.8, 103.8),
        (103.8, 109.0, 103.5, 108.5),
        (108.5, 107.0, 104.0, 104.5),
        (104.5, 106.0, 104.2, 105.5),
        (105.5, 106.2, 105.0, 105.8),
        (105.8, 110.5, 105.5, 108.0),
        (108.0, 111.5, 107.8, 111.0),
    ]
    res = analyze_market_structure(_series(rows), left_bars=2, right_bars=2)
    assert res.direction == TrendDirection.BULLISH
    assert res.latest_bos is not None
    assert res.latest_bos.break_type == StructureBreakType.BOS


def test_bearish_to_bullish_choch_close() -> None:
    rows = [
        (120.0, 121.0, 118.0, 119.0),
        (119.0, 119.5, 115.0, 115.5),
        (115.5, 118.0, 115.2, 117.0),
        (117.0, 116.5, 112.0, 112.5),
        (112.5, 115.5, 112.2, 114.5),
        (114.5, 114.8, 110.0, 110.5),
        (110.5, 113.0, 110.2, 112.5),
        (112.5, 113.5, 112.0, 113.0),
        (113.0, 117.5, 112.8, 117.0),
    ]
    res = analyze_market_structure(_series(rows), left_bars=2, right_bars=2)
    assert res.latest_choch is not None
    assert res.latest_choch.break_type == StructureBreakType.CHOCH
