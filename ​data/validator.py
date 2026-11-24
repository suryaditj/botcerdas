from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from utils.time_utils import (
    candle_open_time,
    is_candle_closed,
    is_data_stale,
    latest_closed_candle_open,
    parse_timestamp_utc,
    timeframe_to_minutes,
)


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        return max(0.0, self.high - self.low)

    @property
    def upper_wick(self) -> float:
        return max(0.0, self.high - max(self.open, self.close))

    @property
    def lower_wick(self) -> float:
        return max(0.0, min(self.open, self.close) - self.low)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class ValidationReport:
    candles: List[Candle]
    dropped_unclosed: int
    duplicates_removed: int
    missing_gaps_detected: int
    is_stale: bool
    is_sufficient: bool
    reason: str = ""


def parse_raw_ohlcv_rows(rows: List[Dict[str, Any]], timeframe: str) -> List[Candle]:
    candles: List[Candle] = []
    for row in rows:
        ts_raw = row.get("datetime") or row.get("timestamp")
        if ts_raw is None:
            continue
        ts = candle_open_time(parse_timestamp_utc(ts_raw), timeframe)
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        v = float(row.get("volume", 0.0) or 0.0)

        if h < max(o, l, c) or l > min(o, h, c) or o <= 0 or h <= 0 or l <= 0 or c <= 0:
            raise ValueError(f"Data OHLC tidak valid pada {ts.isoformat()}")

        candles.append(Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=v))

    candles.sort(key=lambda item: item.timestamp)
    return candles


def validate_candles(
    raw_candles: List[Candle],
    timeframe: str,
    min_candles: int = 60,
    max_gap_tolerance: int = 3,
    max_stale_multiplier: float = 2.0,
    now_utc: Optional[datetime] = None,
) -> ValidationReport:
    current = (
        now_utc.astimezone(timezone.utc)
        if now_utc and now_utc.tzinfo
        else (now_utc.replace(tzinfo=timezone.utc) if now_utc else datetime.now(timezone.utc))
    )

    closed_only: List[Candle] = []
    dropped_unclosed = 0
    for c in raw_candles:
        norm_ts = candle_open_time(c.timestamp, timeframe)
        if is_candle_closed(norm_ts, timeframe, now_utc=current):
            closed_only.append(
                Candle(
                    timestamp=norm_ts,
                    open=c.open,
                    high=c.high,
                    low=c.low,
                    close=c.close,
                    volume=c.volume,
                )
            )
        else:
            dropped_unclosed += 1

    closed_only.sort(key=lambda item: item.timestamp)

    deduped: List[Candle] = []
    duplicates_removed = 0
    for c in closed_only:
        if deduped and deduped[-1].timestamp == c.timestamp:
            deduped[-1] = c
            duplicates_removed += 1
        else:
            deduped.append(c)

    step = timedelta(minutes=timeframe_to_minutes(timeframe))
    missing_gaps_detected = 0
    for i in range(1, len(deduped)):
        delta = deduped[i].timestamp - deduped[i - 1].timestamp
        if delta > step:
            missing_steps = int(delta // step) - 1
            if missing_steps > 0:
                missing_gaps_detected += missing_steps

    if not deduped:
        return ValidationReport(
            candles=[],
            dropped_unclosed=dropped_unclosed,
            duplicates_removed=duplicates_removed,
            missing_gaps_detected=missing_gaps_detected,
            is_stale=True,
            is_sufficient=False,
            reason="Tidak ada candle yang sudah close.",
        )

    stale = is_data_stale(
        latest_closed_open=deduped[-1].timestamp,
        timeframe=timeframe,
        max_delay_multiplier=max_stale_multiplier,
        now_utc=current,
    )

    if stale:
        expected = latest_closed_candle_open(timeframe, current)
        return ValidationReport(
            candles=deduped,
            dropped_unclosed=dropped_unclosed,
            duplicates_removed=duplicates_removed,
            missing_gaps_detected=missing_gaps_detected,
            is_stale=True,
            is_sufficient=False,
            reason=(
                f"Data kedaluwarsa (terakhir close: {deduped[-1].timestamp.isoformat()}, "
                f"diharapkan: {expected.isoformat()})."
            ),
        )

    if missing_gaps_detected > max_gap_tolerance:
        return ValidationReport(
            candles=deduped,
            dropped_unclosed=dropped_unclosed,
            duplicates_removed=duplicates_removed,
            missing_gaps_detected=missing_gaps_detected,
            is_stale=stale,
            is_sufficient=False,
            reason=f"Missing candle ({missing_gaps_detected}) melebihi toleransi ({max_gap_tolerance}).",
        )

    if len(deduped) < min_candles:
        return ValidationReport(
            candles=deduped,
            dropped_unclosed=dropped_unclosed,
            duplicates_removed=duplicates_removed,
            missing_gaps_detected=missing_gaps_detected,
            is_stale=stale,
            is_sufficient=False,
            reason=f"Jumlah candle ({len(deduped)}) kurang dari minimum ({min_candles}).",
        )

    return ValidationReport(
        candles=deduped,
        dropped_unclosed=dropped_unclosed,
        duplicates_removed=duplicates_removed,
        missing_gaps_detected=missing_gaps_detected,
        is_stale=False,
        is_sufficient=True,
        reason="OK",
    )
