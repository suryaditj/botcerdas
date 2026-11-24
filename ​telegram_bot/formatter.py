from __future__ import annotations

from config.loader import MarketConfig
from engine.mtf_analyzer import AnalysisOutput, AnalysisStatus


def _fmt_price(val: float, market_cfg: MarketConfig) -> str:
    return f"{val:.{market_cfg.price_precision}f}"


def format_analysis_message(output: AnalysisOutput, market_cfg: MarketConfig) -> str:
    method_label = "SCALPING" if output.method == "SCALPING" else "ENTRY DAY"
    lines = [
        f"📊 {output.symbol} — {method_label}",
        "",
        f"Arah Market: {output.market_direction}",
        "",
        "Timeframe:",
    ]

    for tf, state in output.timeframe_states.items():
        lines.append(f"- {tf}: {state}")

    lines.append("")
    if output.selected_zone is not None:
        z = output.selected_zone
        prox = _fmt_price(z.proximal, market_cfg)
        dist = _fmt_price(z.distal, market_cfg)
        lines.extend(
            [
                f"Zona {z.kind.value.title()} ({z.pattern.value}):",
                f"- {prox} – {dist}",
                f"- Status: {z.status.value} (Sentuhan: {z.touch_count})",
                f"- Quality: {z.quality_label} ({z.quality_score:.0f}/100)",
                "",
            ]
        )
    else:
        lines.extend(["Zona SNR/SND:", "- Tidak ada zona aktif valid", ""])

    lines.extend(
        [
            "Status Analisa:",
            output.status.value,
            "",
            "Alasan:",
            output.reason,
            "",
        ]
    )

    is_confirmed = output.status in {AnalysisStatus.CONFIRMED_BUY, AnalysisStatus.CONFIRMED_SELL}
    if is_confirmed and output.setup is not None:
        s = output.setup
        exec_tf = list(output.timeframe_states.keys())[-1] if output.timeframe_states else "-"
        lines.extend(
            [
                f"Entry: {_fmt_price(s.entry_price, market_cfg)}",
                f"Stop Loss: {_fmt_price(s.stop_loss, market_cfg)}",
                f"Take Profit 1: {_fmt_price(s.take_profit_1, market_cfg)}",
                f"Take Profit 2: {_fmt_price(s.take_profit_2, market_cfg)}",
                f"Risk/Reward: 1:{s.rr_ratio:.2f}",
                f"Timeframe Konfirmasi: {exec_tf}",
            ]
        )
    else:
        lines.extend(["Entry: —", "Stop Loss: —", "Take Profit: —"])

    lines.append("")
    lines.append(f"Update UTC: {output.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)
