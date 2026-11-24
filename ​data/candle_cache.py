from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from data.validator import Candle


@dataclass
class CacheEntry:
    timeframe: str
    candles: List[Candle]
    latest_closed_ts: datetime
    cached_at: datetime


class CandleCache:
    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl = timedelta(seconds=max(1, ttl_seconds))
        self._store: Dict[Tuple[str, str], CacheEntry] = {}

    def get(
        self,
        symbol: str,
        timeframe: str,
        expected_latest_closed_ts: Optional[datetime] = None,
        now_utc: Optional[datetime] = None,
    ) -> Optional[List[Candle]]:
        key = (symbol.upper(), timeframe.upper())
        entry = self._store.get(key)
        if entry is None or not entry.candles:
            return None

        current = (
            now_utc.astimezone(timezone.utc)
            if now_utc and now_utc.tzinfo
            else (now_utc.replace(tzinfo=timezone.utc) if now_utc else datetime.now(timezone.utc))
        )

        if expected_latest_closed_ts is not None:
            exp_utc = (
                expected_latest_closed_ts.astimezone(timezone.utc)
                if expected_latest_closed_ts.tzinfo
                else expected_latest_closed_ts.replace(tzinfo=timezone.utc)
            )
            if entry.latest_closed_ts >= exp_utc:
                return list(entry.candles)
            return None

        if (current - entry.cached_at) <= self.ttl:
            return list(entry.candles)
        return None

    def set(
        self,
        symbol: str,
        timeframe: str,
        candles: List[Candle],
        now_utc: Optional[datetime] = None,
    ) -> None:
        if not candles:
            return
        current = (
            now_utc.astimezone(timezone.utc)
            if now_utc and now_utc.tzinfo
            else (now_utc.replace(tzinfo=timezone.utc) if now_utc else datetime.now(timezone.utc))
        )
        sorted_candles = sorted(candles, key=lambda c: c.timestamp)
        self._store[(symbol.upper(), timeframe.upper())] = CacheEntry(
            timeframe=timeframe.upper(),
            candles=sorted_candles,
            latest_closed_ts=sorted_candles[-1].timestamp,
            cached_at=current,
        )

    def clear(self) -> None:
        self._store.clear()
