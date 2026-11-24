from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from config.loader import AppConfig
from data.validator import Candle
from engine.mtf_analyzer import AnalysisOutput, AnalysisStatus, MultiTimeframeAnalyzer


@dataclass
class BacktestSummary:
    symbol: str
    method: str
    steps_evaluated: int
    status_counts: Dict[str, int] = field(default_factory=dict)
    confirmed_signals: List[AnalysisOutput] = field(default_factory=list)


def run_walk_forward_backtest(
    config: AppConfig,
    symbol: str,
    method: str,
    full_candle_map: Dict[str, List[Candle]],
    warmup_candles: int = 40,
) -> BacktestSummary:
    analyzer = MultiTimeframeAnalyzer(config=config, data_client=None)
    tfs = config.get_method_timeframes(method)
    exec_series = full_candle_map.get(tfs[-1], [])

    counts: Dict[str, int] = {st.value: 0 for st in AnalysisStatus}
    confirmed: List[AnalysisOutput] = []
    steps = 0

    for end_idx in range(warmup_candles, len(exec_series)):
        cutoff = exec_series[end_idx].timestamp
        sliced: Dict[str, List[Candle]] = {}
        ok = True
        for tf in tfs:
            sub = [c for c in full_candle_map.get(tf, []) if c.timestamp <= cutoff]
            if len(sub) < 10:
                ok = False
                break
            sliced[tf] = sub
        if not ok:
            continue

        steps += 1
        out = analyzer.evaluate_from_candle_map(symbol=symbol, method=method, candle_map=sliced)
        counts[out.status.value] = counts.get(out.status.value, 0) + 1
        if out.status in {AnalysisStatus.CONFIRMED_BUY, AnalysisStatus.CONFIRMED_SELL} and out.setup:
            confirmed.append(out)

    return BacktestSummary(symbol.upper(), method.upper(), steps, counts, confirmed)
