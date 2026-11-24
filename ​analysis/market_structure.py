from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional

from data.validator import Candle


class TrendDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"


class SwingType(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class StructureBreakType(str, Enum):
    BOS = "BOS"
    CHOCH = "CHoCH"


@dataclass(frozen=True)
class SwingPoint:
    index: int
    timestamp: datetime
    price: float
    swing_type: SwingType
    label: str = ""


@dataclass(frozen=True)
class StructureBreak:
    index: int
    timestamp: datetime
    break_type: StructureBreakType
    direction: str
    broken_level: float
    close_price: float
    confirmed_by_close: bool = True


@dataclass(frozen=True)
class MarketStructureResult:
    direction: TrendDirection
    swings: List[SwingPoint]
    swing_highs: List[SwingPoint]
    swing_lows: List[SwingPoint]
    breaks: List[StructureBreak]
    latest_bos: Optional[StructureBreak]
    latest_choch: Optional[StructureBreak]
    last_confirmed_swing_high: Optional[float]
    last_confirmed_swing_low: Optional[float]


def detect_confirmed_swings(
    candles: List[Candle],
    left_bars: int = 3,
    right_bars: int = 2,
) -> List[SwingPoint]:
    n = len(candles)
    if n == 0 or left_bars < 1 or right_bars < 1:
        return []

    last_valid_idx = n - 1 - right_bars
    if last_valid_idx < left_bars:
        return []

    swings: List[SwingPoint] = []
    for idx in range(left_bars, last_valid_idx + 1):
        curr_high = candles[idx].high
        curr_low = candles[idx].low
        left_slice = candles[idx - left_bars : idx]
        right_slice = candles[idx + 1 : idx + right_bars + 1]

        is_sh = all(curr_high > c.high for c in left_slice) and all(
            curr_high >= c.high for c in right_slice
        )
        is_sl = all(curr_low < c.low for c in left_slice) and all(
            curr_low <= c.low for c in right_slice
        )

        if is_sh and not is_sl:
            swings.append(SwingPoint(idx, candles[idx].timestamp, curr_high, SwingType.HIGH))
        elif is_sl and not is_sh:
            swings.append(SwingPoint(idx, candles[idx].timestamp, curr_low, SwingType.LOW))
        elif is_sh and is_sl:
            if candles[idx].is_bullish:
                swings.append(SwingPoint(idx, candles[idx].timestamp, curr_high, SwingType.HIGH))
            else:
                swings.append(SwingPoint(idx, candles[idx].timestamp, curr_low, SwingType.LOW))

    return swings


def analyze_market_structure(
    candles: List[Candle],
    left_bars: int = 3,
    right_bars: int = 2,
    close_break_buffer: float = 0.0,
) -> MarketStructureResult:
    raw_swings = detect_confirmed_swings(candles, left_bars=left_bars, right_bars=right_bars)

    labeled_swings: List[SwingPoint] = []
    swing_highs: List[SwingPoint] = []
    swing_lows: List[SwingPoint] = []

    for sp in raw_swings:
        if sp.swing_type == SwingType.HIGH:
            if not swing_highs:
                label = "SH"
            elif sp.price > swing_highs[-1].price:
                label = "HH"
            elif sp.price < swing_highs[-1].price:
                label = "LH"
            else:
                label = "EQH"
            item = SwingPoint(sp.index, sp.timestamp, sp.price, sp.swing_type, label)
            swing_highs.append(item)
            labeled_swings.append(item)
        else:
            if not swing_lows:
                label = "SL"
            elif sp.price > swing_lows[-1].price:
                label = "HL"
            elif sp.price < swing_lows[-1].price:
                label = "LL"
            else:
                label = "EQL"
            item = SwingPoint(sp.index, sp.timestamp, sp.price, sp.swing_type, label)
            swing_lows.append(item)
            labeled_swings.append(item)

    current_trend = TrendDirection.SIDEWAYS
    recent_high_labels = [sh.label for sh in swing_highs[-2:] if sh.label in {"HH", "LH"}]
    recent_low_labels = [sl.label for sl in swing_lows[-2:] if sl.label in {"HL", "LL"}]

    bull_pts = sum(1 for l in recent_high_labels if l == "HH") + sum(
        1 for l in recent_low_labels if l == "HL"
    )
    bear_pts = sum(1 for l in recent_high_labels if l == "LH") + sum(
        1 for l in recent_low_labels if l == "LL"
    )

    if bull_pts >= 2 and bear_pts == 0:
        current_trend = TrendDirection.BULLISH
    elif bear_pts >= 2 and bull_pts == 0:
        current_trend = TrendDirection.BEARISH

    breaks: List[StructureBreak] = []
    active_sh: Optional[SwingPoint] = None
    active_sl: Optional[SwingPoint] = None
    start_idx = (min(sp.index for sp in labeled_swings) + 1) if labeled_swings else 0

    for idx in range(max(0, start_idx), len(candles)):
        c = candles[idx]
        prior_highs = [sh for sh in swing_highs if sh.index < idx]
        prior_lows = [sl for sl in swing_lows if sl.index < idx]
        if prior_highs:
            active_sh = prior_highs[-1]
        if prior_lows:
            active_sl = prior_lows[-1]

        if active_sh is not None and c.close > (active_sh.price + close_break_buffer):
            if current_trend == TrendDirection.BULLISH:
                b_type = StructureBreakType.BOS
            else:
                b_type = StructureBreakType.CHOCH if current_trend == TrendDirection.BEARISH else StructureBreakType.BOS
                current_trend = TrendDirection.BULLISH

            breaks.append(
                StructureBreak(
                    index=idx,
                    timestamp=c.timestamp,
                    break_type=b_type,
                    direction="BULLISH",
                    broken_level=active_sh.price,
                    close_price=c.close,
                    confirmed_by_close=True,
                )
            )
            active_sh = None

        if active_sl is not None and c.close < (active_sl.price - close_break_buffer):
            if current_trend == TrendDirection.BEARISH:
                b_type = StructureBreakType.BOS
            else:
                b_type = StructureBreakType.CHOCH if current_trend == TrendDirection.BULLISH else StructureBreakType.BOS
                current_trend = TrendDirection.BEARISH

            breaks.append(
                StructureBreak(
                    index=idx,
                    timestamp=c.timestamp,
                    break_type=b_type,
                    direction="BEARISH",
                    broken_level=active_sl.price,
                    close_price=c.close,
                    confirmed_by_close=True,
                )
            )
            active_sl = None

    latest_bos = next((b for b in reversed(breaks) if b.break_type == StructureBreakType.BOS), None)
    latest_choch = next((b for b in reversed(breaks) if b.break_type == StructureBreakType.CHOCH), None)

    return MarketStructureResult(
        direction=current_trend,
        swings=labeled_swings,
        swing_highs=swing_highs,
        swing_lows=swing_lows,
        breaks=breaks,
        latest_bos=latest_bos,
        latest_choch=latest_choch,
        last_confirmed_swing_high=swing_highs[-1].price if swing_highs else None,
        last_confirmed_swing_low=swing_lows[-1].price if swing_lows else None,
    )
