from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from analysis.market_structure import MarketStructureResult
from data.validator import Candle


class ZoneKind(str, Enum):
    SUPPLY = "SUPPLY"
    DEMAND = "DEMAND"
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class ZonePattern(str, Enum):
    RBR = "RBR"
    DBR = "DBR"
    DBD = "DBD"
    RBD = "RBD"
    SNR_SWING = "SNR_SWING"


class ZoneStatus(str, Enum):
    FRESH = "FRESH"
    TESTED = "TESTED"
    INVALID = "INVALID"


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class PriceZone:
    zone_id: str
    kind: ZoneKind
    pattern: ZonePattern
    timeframe: str
    proximal: float
    distal: float
    created_at: datetime
    created_index: int
    trade_side: TradeSide
    status: ZoneStatus = ZoneStatus.FRESH
    touch_count: int = 0
    departure_strength: float = 0.0
    quality_score: float = 0.0

    @property
    def lower(self) -> float:
        return min(self.proximal, self.distal)

    @property
    def upper(self) -> float:
        return max(self.proximal, self.distal)

    @property
    def width(self) -> float:
        return max(0.0, self.upper - self.lower)

    @property
    def quality_label(self) -> str:
        if self.quality_score >= 75.0:
            return "HIGH"
        if self.quality_score >= 55.0:
            return "MEDIUM"
        return "LOW"


@dataclass
class ZoneDetectionResult:
    timeframe: str
    atr: float
    active_buy_zones: List[PriceZone]
    active_sell_zones: List[PriceZone]
    all_valid_zones: List[PriceZone]


def compute_atr(candles: List[Candle], period: int = 14) -> float:
    if not candles:
        return 0.0
    if len(candles) == 1:
        return candles[0].range_size

    trs: List[float] = [candles[0].range_size]
    for i in range(1, len(candles)):
        curr = candles[i]
        prev_close = candles[i - 1].close
        trs.append(
            max(
                curr.high - curr.low,
                abs(curr.high - prev_close),
                abs(curr.low - prev_close),
            )
        )
    eff = min(period, len(trs))
    return sum(trs[-eff:]) / eff


def _evaluate_zone_lifecycle(zone: PriceZone, subsequent: List[Candle]) -> PriceZone:
    touches = 0
    in_zone_prev = False

    for c in subsequent:
        if zone.trade_side == TradeSide.BUY and c.close < zone.distal:
            zone.status = ZoneStatus.INVALID
            zone.touch_count = touches
            return zone
        if zone.trade_side == TradeSide.SELL and c.close > zone.distal:
            zone.status = ZoneStatus.INVALID
            zone.touch_count = touches
            return zone

        overlaps = (c.low <= zone.upper) and (c.high >= zone.lower)
        if overlaps and not in_zone_prev:
            touches += 1
            in_zone_prev = True
        elif not overlaps:
            in_zone_prev = False

    zone.touch_count = touches
    zone.status = ZoneStatus.FRESH if touches == 0 else ZoneStatus.TESTED
    return zone


def _score_zone(
    zone: PriceZone,
    atr: float,
    max_zone_atr_mult: float,
    min_departure_atr_mult: float,
    structure: Optional[MarketStructureResult],
) -> float:
    if atr <= 0:
        return 0.0

    score = 40.0
    if zone.status == ZoneStatus.FRESH:
        score += 20.0
    elif zone.status == ZoneStatus.TESTED:
        score += 8.0

    dep_ratio = zone.departure_strength / max(min_departure_atr_mult, 1e-6)
    score += min(25.0, max(0.0, dep_ratio * 12.5))

    width_ratio = zone.width / atr
    if width_ratio <= max_zone_atr_mult:
        tightness = 1.0 - (width_ratio / max(max_zone_atr_mult, 1e-6))
        score += max(0.0, tightness * 10.0)
    else:
        score -= 15.0

    if structure is not None:
        if zone.trade_side == TradeSide.BUY and structure.direction.value == "BULLISH":
            score += 5.0
        elif zone.trade_side == TradeSide.SELL and structure.direction.value == "BEARISH":
            score += 5.0

    return round(max(0.0, min(100.0, score)), 2)


def detect_snd_zones(
    candles: List[Candle],
    timeframe: str,
    zone_cfg: Dict[str, Any],
    structure: Optional[MarketStructureResult] = None,
) -> List[PriceZone]:
    atr = compute_atr(candles, period=int(zone_cfg.get("atr_period", 14)))
    if atr <= 0 or len(candles) < 6:
        return []

    max_base = int(zone_cfg.get("max_base_candles", 3))
    min_leg_atr = float(zone_cfg.get("min_leg_atr_mult", 1.1))
    min_dep_atr = float(zone_cfg.get("min_departure_atr_mult", 1.5))
    max_zone_atr = float(zone_cfg.get("max_zone_atr_mult", 2.5))
    min_score = float(zone_cfg.get("min_quality_score", 55.0))
    max_base_body_ratio = float(zone_cfg.get("max_base_body_to_atr", 0.85))

    zones: List[PriceZone] = []
    n = len(candles)

    for dep_idx in range(2, n):
        dep_c = candles[dep_idx]
        dep_impulse = max(abs(dep_c.close - dep_c.open), dep_c.range_size * 0.75)
        if dep_impulse < (min_dep_atr * atr):
            continue

        is_bull_dep = dep_c.is_bullish and dep_c.close > dep_c.open
        is_bear_dep = dep_c.is_bearish and dep_c.close < dep_c.open
        if not (is_bull_dep or is_bear_dep):
            continue

        for base_len in range(1, max_base + 1):
            base_start = dep_idx - base_len
            leg_in_idx = base_start - 1
            if leg_in_idx < 0:
                continue

            base_candles = candles[base_start:dep_idx]
            leg_in = candles[leg_in_idx]

            if any(bc.body_size > (max_base_body_ratio * atr) for bc in base_candles):
                continue

            base_high = max(bc.high for bc in base_candles)
            base_low = min(bc.low for bc in base_candles)

            if is_bull_dep:
                leg_in_drop = leg_in.open - leg_in.close
                leg_in_rally = leg_in.close - leg_in.open
                if leg_in.is_bearish and leg_in_drop >= (min_leg_atr * atr):
                    z = PriceZone(
                        zone_id=f"{timeframe}_DBR_{base_start}_{dep_idx}",
                        kind=ZoneKind.DEMAND,
                        pattern=ZonePattern.DBR,
                        timeframe=timeframe,
                        proximal=base_high,
                        distal=min(base_low, leg_in.low),
                        created_at=dep_c.timestamp,
                        created_index=dep_idx,
                        trade_side=TradeSide.BUY,
                        departure_strength=dep_impulse / atr,
                    )
                elif leg_in.is_bullish and leg_in_rally >= (min_leg_atr * atr):
                    z = PriceZone(
                        zone_id=f"{timeframe}_RBR_{base_start}_{dep_idx}",
                        kind=ZoneKind.DEMAND,
                        pattern=ZonePattern.RBR,
                        timeframe=timeframe,
                        proximal=base_high,
                        distal=base_low,
                        created_at=dep_c.timestamp,
                        created_index=dep_idx,
                        trade_side=TradeSide.BUY,
                        departure_strength=dep_impulse / atr,
                    )
                else:
                    continue
            else:
                leg_in_rally = leg_in.close - leg_in.open
                leg_in_drop = leg_in.open - leg_in.close
                if leg_in.is_bullish and leg_in_rally >= (min_leg_atr * atr):
                    z = PriceZone(
                        zone_id=f"{timeframe}_RBD_{base_start}_{dep_idx}",
                        kind=ZoneKind.SUPPLY,
                        pattern=ZonePattern.RBD,
                        timeframe=timeframe,
                        proximal=base_low,
                        distal=max(base_high, leg_in.high),
                        created_at=dep_c.timestamp,
                        created_index=dep_idx,
                        trade_side=TradeSide.SELL,
                        departure_strength=dep_impulse / atr,
                    )
                elif leg_in.is_bearish and leg_in_drop >= (min_leg_atr * atr):
                    z = PriceZone(
                        zone_id=f"{timeframe}_DBD_{base_start}_{dep_idx}",
                        kind=ZoneKind.SUPPLY,
                        pattern=ZonePattern.DBD,
                        timeframe=timeframe,
                        proximal=base_low,
                        distal=base_high,
                        created_at=dep_c.timestamp,
                        created_index=dep_idx,
                        trade_side=TradeSide.SELL,
                        departure_strength=dep_impulse / atr,
                    )
                else:
                    continue

            if z.width <= 0 or z.width > (max_zone_atr * atr):
                continue

            z = _evaluate_zone_lifecycle(z, candles[dep_idx + 1 :])
            if z.status == ZoneStatus.INVALID:
                continue

            z.quality_score = _score_zone(z, atr, max_zone_atr, min_dep_atr, structure)
            if z.quality_score >= min_score:
                zones.append(z)

    return zones


def detect_snr_zones(
    candles: List[Candle],
    timeframe: str,
    zone_cfg: Dict[str, Any],
    structure: Optional[MarketStructureResult] = None,
) -> List[PriceZone]:
    atr = compute_atr(candles, period=int(zone_cfg.get("atr_period", 14)))
    if atr <= 0 or not candles or structure is None:
        return []

    band_mult = float(zone_cfg.get("snr_band_atr_mult", 0.25))
    min_score = float(zone_cfg.get("min_quality_score", 55.0))
    max_zone_atr = float(zone_cfg.get("max_zone_atr_mult", 2.5))
    min_dep_atr = float(zone_cfg.get("min_departure_atr_mult", 1.5))
    half_band = max(atr * band_mult, 1e-9)

    candidates: List[PriceZone] = []
    for i, sh in enumerate(structure.swing_highs[-6:]):
        z = PriceZone(
            zone_id=f"{timeframe}_RES_{sh.index}_{i}",
            kind=ZoneKind.RESISTANCE,
            pattern=ZonePattern.SNR_SWING,
            timeframe=timeframe,
            proximal=sh.price - half_band,
            distal=sh.price + half_band,
            created_at=sh.timestamp,
            created_index=sh.index,
            trade_side=TradeSide.SELL,
            departure_strength=1.2,
        )
        z = _evaluate_zone_lifecycle(z, candles[sh.index + 1 :])
        if z.status != ZoneStatus.INVALID and z.width <= (max_zone_atr * atr):
            z.quality_score = _score_zone(z, atr, max_zone_atr, min_dep_atr, structure)
            if z.quality_score >= min_score:
                candidates.append(z)

    for i, sl in enumerate(structure.swing_lows[-6:]):
        z = PriceZone(
            zone_id=f"{timeframe}_SUP_{sl.index}_{i}",
            kind=ZoneKind.SUPPORT,
            pattern=ZonePattern.SNR_SWING,
            timeframe=timeframe,
            proximal=sl.price + half_band,
            distal=sl.price - half_band,
            created_at=sl.timestamp,
            created_index=sl.index,
            trade_side=TradeSide.BUY,
            departure_strength=1.2,
        )
        z = _evaluate_zone_lifecycle(z, candles[sl.index + 1 :])
        if z.status != ZoneStatus.INVALID and z.width <= (max_zone_atr * atr):
            z.quality_score = _score_zone(z, atr, max_zone_atr, min_dep_atr, structure)
            if z.quality_score >= min_score:
                candidates.append(z)

    return candidates


def _top_zones(zones: List[PriceZone], side: TradeSide, ref_price: float, max_active: int) -> List[PriceZone]:
    filtered = [z for z in zones if z.trade_side == side and z.status != ZoneStatus.INVALID]
    filtered.sort(key=lambda z: (-z.quality_score, abs(((z.lower + z.upper) / 2.0) - ref_price)))
    return filtered[:max_active]


def analyze_snr_snd(
    candles: List[Candle],
    timeframe: str,
    zone_cfg: Dict[str, Any],
    structure: Optional[MarketStructureResult] = None,
) -> ZoneDetectionResult:
    atr = compute_atr(candles, period=int(zone_cfg.get("atr_period", 14)))
    max_active = min(3, max(1, int(zone_cfg.get("max_active_per_side", 3))))
    all_raw = detect_snd_zones(candles, timeframe, zone_cfg, structure) + detect_snr_zones(
        candles, timeframe, zone_cfg, structure
    )
    ref_price = candles[-1].close if candles else 0.0
    buy_zones = _top_zones(all_raw, TradeSide.BUY, ref_price, max_active)
    sell_zones = _top_zones(all_raw, TradeSide.SELL, ref_price, max_active)
    return ZoneDetectionResult(
        timeframe=timeframe,
        atr=atr,
        active_buy_zones=buy_zones,
        active_sell_zones=sell_zones,
        all_valid_zones=buy_zones + sell_zones,
    )
