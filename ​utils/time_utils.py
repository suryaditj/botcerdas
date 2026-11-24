from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict

TIMEFRAME_MINUTES: Dict[str, int] = {
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
}

TWELVE_DATA_INTERVALS: Dict[str, str] = {
    "M5": "5min",
    "M15": "15min",
    "H1": "1h",
    "H4": "4h",
}


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_timestamp_utc(value: str | int | float | datetime) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        return ensure_utc(datetime.fromisoformat(raw))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    raise ValueError(f"Format timestamp tidak valid: {value!r}")


def timeframe_to_minutes(timeframe: str) -> int:
    tf = timeframe.upper()
    if tf not in TIMEFRAME_MINUTES:
        raise ValueError(f"Timeframe tidak didukung: {timeframe}")
    return TIMEFRAME_MINUTES[tf]


def to_twelve_data_interval(timeframe: str) -> str:
    tf = timeframe.upper()
    if tf not in TWELVE_DATA_INTERVALS:
        raise ValueError(f"Timeframe tidak didukung Twelve Data: {timeframe}")
    return TWELVE_DATA_INTERVALS[tf]


def candle_open_time(ts: datetime, timeframe: str) -> datetime:
    utc_dt = ensure_utc(ts)
    minutes = timeframe_to_minutes(timeframe)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    elapsed_minutes = int((utc_dt - epoch).total_seconds() // 60)
    bucket_start_minutes = (elapsed_minutes // minutes) * minutes
    return epoch + timedelta(minutes=bucket_start_minutes)


def candle_close_time(open_ts: datetime, timeframe: str) -> datetime:
    minutes = timeframe_to_minutes(timeframe)
    return candle_open_time(open_ts, timeframe) + timedelta(minutes=minutes)


def is_candle_closed(open_ts: datetime, timeframe: str, now_utc: datetime | None = None) -> bool:
    current = ensure_utc(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    return current >= candle_close_time(open_ts, timeframe)


def latest_closed_candle_open(timeframe: str, now_utc: datetime | None = None) -> datetime:
    current = ensure_utc(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    minutes = timeframe_to_minutes(timeframe)
    current_bucket_open = candle_open_time(current, timeframe)
    return current_bucket_open - timedelta(minutes=minutes)


def is_data_stale(
    latest_closed_open: datetime,
    timeframe: str,
    max_delay_multiplier: float = 2.0,
    now_utc: datetime | None = None,
) -> bool:
    current = ensure_utc(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    expected_latest_open = latest_closed_candle_open(timeframe, current)
    minutes = timeframe_to_minutes(timeframe)
    max_allowed_lag = timedelta(minutes=minutes * max_delay_multiplier)
    return (expected_latest_open - ensure_utc(latest_closed_open)) > max_allowed_lag
