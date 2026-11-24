from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from analysis.snr_snd_detector import TradeSide, compute_atr
from data.validator import Candle


@dataclass(frozen=True)
class ConfirmationResult:
    confirmed: bool
    score: float
    min_required_score: float
    signals: List[str] = field(default_factory=list)
    reason: str = ""


def evaluate_entry_confirmation(
    candles: List[Candle],
    side: TradeSide,
    conf_cfg: Dict[str, Any],
) -> ConfirmationResult:
    min_score = float(conf_cfg.get("min_confirmation_score", 1.5))
    weights = conf_cfg.get(
        "weights",
        {
            "rejection_pin_bar": 1.5,
            "engulfing": 1.5,
            "strong_displacement": 1.5,
            "momentum_candle": 1.0,
        },
    )

    if len(candles) < 2:
        return ConfirmationResult(
            confirmed=False,
            score=0.0,
            min_required_score=min_score,
            reason="Candle tidak cukup untuk konfirmasi.",
        )

    curr = candles[-1]
    prev = candles[-2]
    atr = max(compute_atr(candles, period=14), 1e-9)

    score = 0.0
    signals: List[str] = []

    if side == TradeSide.BUY:
        if (
            curr.range_size > 0
            and curr.lower_wick >= (1.8 * max(curr.body_size, 1e-9))
            and curr.lower_wick >= (0.45 * curr.range_size)
            and curr.close >= (curr.low + 0.55 * curr.range_size)
        ):
            w = float(weights.get("rejection_pin_bar", 1.5))
            score += w
            signals.append(f"PinBar({w:.1f})")

        if prev.is_bearish and curr.is_bullish and curr.close >= prev.open and curr.open <= prev.close:
            w = float(weights.get("engulfing", 1.5))
            score += w
            signals.append(f"Engulfing({w:.1f})")

        if curr.is_bullish and curr.body_size >= (1.25 * atr):
            w = float(weights.get("strong_displacement", 1.5))
            score += w
            signals.append(f"Displacement({w:.1f})")

        if curr.is_bullish and curr.body_size >= (0.65 * atr) and curr.body_size > prev.body_size:
            w = float(weights.get("momentum_candle", 1.0))
            score += w
            signals.append(f"Momentum({w:.1f})")
    else:
        if (
            curr.range_size > 0
            and curr.upper_wick >= (1.8 * max(curr.body_size, 1e-9))
            and curr.upper_wick >= (0.45 * curr.range_size)
            and curr.close <= (curr.high - 0.55 * curr.range_size)
        ):
            w = float(weights.get("rejection_pin_bar", 1.5))
            score += w
            signals.append(f"PinBar({w:.1f})")

        if prev.is_bullish and curr.is_bearish and curr.close <= prev.open and curr.open >= prev.close:
            w = float(weights.get("engulfing", 1.5))
            score += w
            signals.append(f"Engulfing({w:.1f})")

        if curr.is_bearish and curr.body_size >= (1.25 * atr):
            w = float(weights.get("strong_displacement", 1.5))
            score += w
            signals.append(f"Displacement({w:.1f})")

        if curr.is_bearish and curr.body_size >= (0.65 * atr) and curr.body_size > prev.body_size:
            w = float(weights.get("momentum_candle", 1.0))
            score += w
            signals.append(f"Momentum({w:.1f})")

    ok = score >= min_score
    reason = (
        f"Konfirmasi {side.value} valid (skor {score:.2f} >= {min_score:.2f}): {', '.join(signals)}."
        if ok
        else f"Konfirmasi {side.value} belum memenuhi syarat (skor {score:.2f} < {min_score:.2f})."
    )
    return ConfirmationResult(
        confirmed=ok,
        score=round(score, 2),
        min_required_score=min_score,
        signals=signals,
        reason=reason,
    )
