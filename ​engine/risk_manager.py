from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List

from analysis.snr_snd_detector import PriceZone, TradeSide
from config.loader import MarketConfig
from data.validator import Candle


@dataclass(frozen=True)
class TradeSetup:
    valid: bool
    side: TradeSide
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    rr_ratio: float
    reason: str


def quantize_price(value: float, market_cfg: MarketConfig) -> float:
    tick = Decimal(str(market_cfg.tick_size))
    val = Decimal(str(value))
    snapped = (val / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick
    fmt = "0" if market_cfg.price_precision == 0 else "0." + ("0" * market_cfg.price_precision)
    return float(snapped.quantize(Decimal(fmt), rounding=ROUND_HALF_UP))


def build_trade_setup(
    side: TradeSide,
    zone: PriceZone,
    entry_candles: List[Candle],
    opposing_zones: List[PriceZone],
    market_cfg: MarketConfig,
    risk_cfg: Dict[str, Any],
    atr_value: float,
) -> TradeSetup:
    min_rrr = float(risk_cfg.get("min_rr_ratio", 1.5))
    tp2_mult = float(risk_cfg.get("tp2_fallback_rr_mult", 2.5))
    atr_buf_mult = float(risk_cfg.get("sl_atr_buffer_mult", 0.15))

    buffer_dist = max(
        market_cfg.default_sl_buffer_ticks * market_cfg.tick_size,
        max(0.0, atr_value * atr_buf_mult),
    )
    entry = quantize_price(entry_candles[-1].close, market_cfg)

    if side == TradeSide.BUY:
        sl = quantize_price(zone.distal - buffer_dist, market_cfg)
        risk = entry - sl
        if risk <= 0:
            return TradeSetup(False, side, entry, sl, entry, entry, 0.0, "SL BUY tidak valid.")

        targets = sorted([z.lower for z in opposing_zones if z.lower > (entry + risk * min_rrr * 0.8)])
        min_tp1 = entry + (risk * min_rrr)
        tp1_raw = max(targets[0], min_tp1) if targets else min_tp1
        tp2_raw = targets[1] if len(targets) > 1 else max(tp1_raw + risk, entry + (risk * tp2_mult))

        tp1 = quantize_price(tp1_raw, market_cfg)
        tp2 = quantize_price(max(tp2_raw, tp1 + market_cfg.tick_size), market_cfg)
        rrr = round((tp1 - entry) / risk, 2)
    else:
        sl = quantize_price(zone.distal + buffer_dist, market_cfg)
        risk = sl - entry
        if risk <= 0:
            return TradeSetup(False, side, entry, sl, entry, entry, 0.0, "SL SELL tidak valid.")

        targets = sorted(
            [z.upper for z in opposing_zones if z.upper < (entry - risk * min_rrr * 0.8)],
            reverse=True,
        )
        min_tp1 = entry - (risk * min_rrr)
        tp1_raw = min(targets[0], min_tp1) if targets else min_tp1
        tp2_raw = targets[1] if len(targets) > 1 else min(tp1_raw - risk, entry - (risk * tp2_mult))

        tp1 = quantize_price(tp1_raw, market_cfg)
        tp2 = quantize_price(min(tp2_raw, tp1 - market_cfg.tick_size), market_cfg)
        rrr = round((entry - tp1) / risk, 2)

    if rrr < min_rrr:
        return TradeSetup(
            False,
            side,
            entry,
            sl,
            tp1,
            tp2,
            rrr,
            f"RRR ({rrr:.2f}) di bawah minimum ({min_rrr:.2f}).",
        )

    return TradeSetup(True, side, entry, sl, tp1, tp2, rrr, f"Setup {side.value} valid (RRR 1:{rrr:.2f}).")
