from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from analysis.entry_confirmation import ConfirmationResult, evaluate_entry_confirmation
from analysis.market_structure import MarketStructureResult, TrendDirection, analyze_market_structure
from analysis.snr_snd_detector import PriceZone, TradeSide, ZoneDetectionResult, analyze_snr_snd
from config.loader import AppConfig
from data.twelve_data_client import TwelveDataClient
from data.validator import Candle
from engine.risk_manager import TradeSetup, build_trade_setup


class AnalysisStatus(str, Enum):
    ANALYZING = "ANALYZING"
    WAITING_ZONE = "WAITING ZONE"
    WAITING_CONFIRMATION = "WAITING CONFIRMATION"
    CONFIRMED_BUY = "CONFIRMED BUY"
    CONFIRMED_SELL = "CONFIRMED SELL"
    NO_TRADE = "NO TRADE"
    INVALIDATED = "INVALIDATED"


@dataclass
class AnalysisOutput:
    symbol: str
    method: str
    status: AnalysisStatus
    market_direction: str
    timeframe_states: Dict[str, str]
    selected_zone: Optional[PriceZone]
    active_zones_count: int
    reason: str
    setup: Optional[TradeSetup] = None
    confirmation: Optional[ConfirmationResult] = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MultiTimeframeAnalyzer:
    def __init__(
        self,
        config: AppConfig,
        data_client: Optional[TwelveDataClient],
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self.data_client = data_client
        self.logger = logger or logging.getLogger("mtf_bot.mtf_analyzer")

    def _tf_analysis(self, candles: List[Candle], tf: str) -> tuple[MarketStructureResult, ZoneDetectionResult]:
        ms_cfg = self.config.raw.get("market_structure", {})
        zone_cfg = self.config.raw.get("zones", {})
        structure = analyze_market_structure(
            candles=candles,
            left_bars=int(ms_cfg.get("left_bars", 3)),
            right_bars=int(ms_cfg.get("right_bars", 2)),
            close_break_buffer=float(ms_cfg.get("close_break_buffer", 0.0)),
        )
        zones = analyze_snr_snd(candles=candles, timeframe=tf, zone_cfg=zone_cfg, structure=structure)
        return structure, zones

    @staticmethod
    def _nearest_zone(zones: List[PriceZone], price: float) -> Optional[PriceZone]:
        if not zones:
            return None
        return min(zones, key=lambda z: abs(((z.lower + z.upper) / 2.0) - price))

    def evaluate_from_candle_map(
        self,
        symbol: str,
        method: str,
        candle_map: Dict[str, List[Candle]],
    ) -> AnalysisOutput:
        sym = symbol.upper()
        meth = method.upper()
        market_cfg = self.config.get_market(sym)
        conf_cfg = self.config.raw.get("entry_confirmation", {})
        risk_cfg = self.config.raw.get("risk", {})
        tol = float(self.config.raw.get("zones", {}).get("touch_tolerance", 0.0))

        if meth == "SCALPING":
            h1 = candle_map.get("H1", [])
            m15 = candle_map.get("M15", [])
            if not h1 or not m15:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.NO_TRADE, "UNKNOWN",
                    {"H1": "NO DATA", "M15": "NO DATA"}, None, 0,
                    "Data candle H1 atau M15 tidak lengkap.",
                )

            h1_struct, h1_zones = self._tf_analysis(h1, "H1")
            m15_struct, _ = self._tf_analysis(m15, "M15")
            direction = h1_struct.direction.value

            if h1_struct.direction == TrendDirection.SIDEWAYS:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.NO_TRADE, "SIDEWAYS / UNCLEAR",
                    {"H1": "SIDEWAYS", "M15": m15_struct.direction.value}, None, 0,
                    "Struktur utama H1 belum menunjukkan arah tren jelas.",
                )

            side = TradeSide.BUY if h1_struct.direction == TrendDirection.BULLISH else TradeSide.SELL
            zones = h1_zones.active_buy_zones if side == TradeSide.BUY else h1_zones.active_sell_zones
            opp_zones = h1_zones.active_sell_zones if side == TradeSide.BUY else h1_zones.active_buy_zones
            selected = self._nearest_zone(zones, m15[-1].close)

            if selected is None:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.NO_TRADE, direction,
                    {"H1": direction, "M15": "NO ZONE"}, None, 0,
                    f"Tidak ada zona {side.value} valid pada H1.",
                )

            in_zone = (m15[-1].low <= selected.upper + tol) and (m15[-1].high >= selected.lower - tol)
            if not in_zone:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.WAITING_ZONE, direction,
                    {"H1": direction, "M15": "WAITING ZONE"}, selected, len(zones),
                    f"Harga belum memasuki zona {selected.kind.value} H1.",
                )

            conf = evaluate_entry_confirmation(m15, side=side, conf_cfg=conf_cfg)
            if not conf.confirmed:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.WAITING_CONFIRMATION, direction,
                    {"H1": direction, "M15": "WAITING CONFIRMATION"}, selected, len(zones),
                    f"Harga menyentuh zona H1, namun {conf.reason.lower()}",
                    confirmation=conf,
                )

            setup = build_trade_setup(side, selected, m15, opp_zones, market_cfg, risk_cfg, h1_zones.atr)
            if not setup.valid:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.NO_TRADE, direction,
                    {"H1": direction, "M15": "INVALID RRR"}, selected, len(zones),
                    setup.reason, confirmation=conf,
                )

            final_st = AnalysisStatus.CONFIRMED_BUY if side == TradeSide.BUY else AnalysisStatus.CONFIRMED_SELL
            return AnalysisOutput(
                sym, meth, final_st, direction,
                {"H1": direction, "M15": "CONFIRMED"}, selected, len(zones),
                f"{conf.reason} {setup.reason}", setup=setup, confirmation=conf,
            )

        if meth == "ENTRY_DAY":
            h4 = candle_map.get("H4", [])
            h1 = candle_map.get("H1", [])
            m5 = candle_map.get("M5", [])
            if not h4 or not h1 or not m5:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.NO_TRADE, "UNKNOWN",
                    {"H4": "NO DATA", "H1": "NO DATA", "M5": "NO DATA"}, None, 0,
                    "Data candle H4, H1, atau M5 tidak lengkap.",
                )

            h4_struct, _ = self._tf_analysis(h4, "H4")
            h1_struct, h1_zones = self._tf_analysis(h1, "H1")
            m5_struct, _ = self._tf_analysis(m5, "M5")
            direction = h4_struct.direction.value

            if h4_struct.direction == TrendDirection.SIDEWAYS:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.NO_TRADE, "SIDEWAYS / UNCLEAR",
                    {"H4": "SIDEWAYS", "H1": h1_struct.direction.value, "M5": m5_struct.direction.value},
                    None, 0, "Arah utama H4 belum terkonfirmasi BUY atau SELL.",
                )

            side = TradeSide.BUY if h4_struct.direction == TrendDirection.BULLISH else TradeSide.SELL
            zones = h1_zones.active_buy_zones if side == TradeSide.BUY else h1_zones.active_sell_zones
            opp_zones = h1_zones.active_sell_zones if side == TradeSide.BUY else h1_zones.active_buy_zones
            selected = self._nearest_zone(zones, m5[-1].close)

            if selected is None:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.NO_TRADE, direction,
                    {"H4": direction, "H1": "NO ZONE", "M5": "NO ZONE"}, None, 0,
                    f"Tidak ada zona H1 yang searah dengan arah utama H4 ({direction}).",
                )

            h1_in = (h1[-1].low <= selected.upper + tol) and (h1[-1].high >= selected.lower - tol)
            m5_in = (m5[-1].low <= selected.upper + tol) and (m5[-1].high >= selected.lower - tol)
            if not (h1_in or m5_in):
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.WAITING_ZONE, direction,
                    {"H4": direction, "H1": "WAITING ZONE", "M5": "WAITING ZONE"},
                    selected, len(zones), "Zona H1 tersedia, namun harga belum menyentuhnya.",
                )

            conf = evaluate_entry_confirmation(m5, side=side, conf_cfg=conf_cfg)
            if not conf.confirmed:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.WAITING_CONFIRMATION, direction,
                    {"H4": direction, "H1": "IN ZONE", "M5": "WAITING CONFIRMATION"},
                    selected, len(zones), f"Zona H1 tersentuh, namun {conf.reason.lower()}",
                    confirmation=conf,
                )

            setup = build_trade_setup(side, selected, m5, opp_zones, market_cfg, risk_cfg, h1_zones.atr)
            if not setup.valid:
                return AnalysisOutput(
                    sym, meth, AnalysisStatus.NO_TRADE, direction,
                    {"H4": direction, "H1": "IN ZONE", "M5": "INVALID RRR"},
                    selected, len(zones), setup.reason, confirmation=conf,
                )

            final_st = AnalysisStatus.CONFIRMED_BUY if side == TradeSide.BUY else AnalysisStatus.CONFIRMED_SELL
            return AnalysisOutput(
                sym, meth, final_st, direction,
                {"H4": direction, "H1": "IN ZONE", "M5": "CONFIRMED"},
                selected, len(zones), f"{conf.reason} {setup.reason}",
                setup=setup, confirmation=conf,
            )

        raise ValueError(f"Metode analisa tidak dikenal: {method}")

    def analyze(self, symbol: str, method: str, force_refresh: bool = False) -> AnalysisOutput:
        if self.data_client is None:
            raise RuntimeError("data_client belum diinisialisasi.")

        tfs = self.config.get_method_timeframes(method)
        candle_map: Dict[str, List[Candle]] = {}

        for tf in tfs:
            report = self.data_client.fetch_candles(symbol=symbol, timeframe=tf, force_refresh=force_refresh)
            if not report.is_sufficient:
                self.logger.warning("Data tidak valid %s %s (%s): %s", symbol, method, tf, report.reason)
                states = {other: ("ERROR/STALE" if other == tf else "SKIPPED") for other in tfs}
                return AnalysisOutput(
                    symbol.upper(), method.upper(), AnalysisStatus.NO_TRADE, "UNKNOWN",
                    states, None, 0, f"Data {tf} tidak valid: {report.reason}",
                )
            candle_map[tf] = report.candles

        return self.evaluate_from_candle_map(symbol=symbol, method=method, candle_map=candle_map)
