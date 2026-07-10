#!/usr/bin/env python3
"""P1 — time stop ablation on T2 cache (Sprint 4 paper stack)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from intraday_agent.config import Config
from intraday_agent.learning.metrics import summarize_trades
from intraday_agent.learning.research_data import (
    build_regime,
    init_research_session,
    load_symbol_dfs,
    normalize_source,
)
from intraday_agent.logging_setup import setup_logger
from intraday_agent.universe import symbols_for_tier
from tools.research_phases import ENTRY_FILTER, SPRINT4_PAPER_STACK, config_override, run_sim


def _exit_breakdown(trades: list) -> dict[str, dict[str, float | int]]:
    by: dict[str, dict[str, float | int]] = {}
    for t in trades:
        reason = t.exit_reason or "unknown"
        if reason.startswith("ATR stop"):
            family = "ATR stop"
        elif reason.startswith("time stop"):
            family = "time stop"
        elif reason.startswith("RSI"):
            family = "RSI exit"
        elif "square-off" in reason.lower():
            family = "EOD"
        else:
            family = reason.split("(")[0].strip()
        row = by.setdefault(family, {"trades": 0, "net": 0.0})
        row["trades"] = int(row["trades"]) + 1
        row["net"] = float(row["net"]) + float(t.pnl_amount or 0)
    return by


def run_variant(
    symbol_dfs: dict,
    regime,
    *,
    label: str,
    config: dict,
    capital: float,
) -> dict:
    with config_override(CAPITAL_PER_TRADE=capital, MAX_QUANTITY=200):
        trades, stats = run_sim(symbol_dfs, regime, config=config, source="backtest")
    return {
        "label": label,
        "config": {k: config[k] for k in config if k.startswith(("TIME_", "VOLUME_", "ATR_", "TRAILING"))},
        "stats": stats,
        "exits": _exit_breakdown(trades),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="P1 time-stop ablation on T2")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--source", default="cache")
    p.add_argument("--capital", type=float, default=50000)
    p.add_argument("--output-json", default="data/research/time_stop_ablation_t2.json")
    p.add_argument("--output-md", default="data/research/TIME_STOP_ABLATION_T2.md")
    args = p.parse_args()

    setup_logger()
    source = normalize_source(args.source)
    _, broker = init_research_session(source)
    symbols = symbols_for_tier("t2")
    symbol_dfs = load_symbol_dfs(symbols, args.days, source, broker=broker)
    if not symbol_dfs:
        print("Error: no candle data", file=sys.stderr)
        return 1

    regime = build_regime(args.days, source, Config.REGIME_FILTER_ENABLED, broker=broker)
    base = dict(SPRINT4_PAPER_STACK)
    variants = [
        ("P1a_base", {**base, "TIME_STOP_BARS": 0}),
        ("P1b_ts4", {**base, "TIME_STOP_BARS": 4}),
        ("P1c_ts5", {**base, "TIME_STOP_BARS": 5}),
        ("P1d_ts6", {**base, "TIME_STOP_BARS": 6}),
        ("P1e_ts5_surge", {**base, "TIME_STOP_BARS": 5, "VOLUME_SURGE_BLOCK_MULT": 2.0}),
    ]

    results = [
        run_variant(symbol_dfs, regime, label=label, config=cfg, capital=args.capital)
        for label, cfg in variants
    ]

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "tier": "t2",
        "days": args.days,
        "capital_per_trade": args.capital,
        "results": results,
    }

    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    lines = [
        "# P1 — Time Stop Ablation (T2)",
        "",
        f"Generated: {report['generated_at']} | {args.days}d | CAPITAL={args.capital:,.0f}",
        "",
        "| Variant | Trades | Net ₹ | Sharpe | ATR stops | Time stops | RSI exits |",
        "|---------|--------|-------|--------|-----------|------------|-----------|",
    ]
    for row in results:
        s = row["stats"]
        ex = row["exits"]
        atr_n = int(ex.get("ATR stop", {}).get("trades", 0))
        ts_n = int(ex.get("time stop", {}).get("trades", 0))
        rsi_n = int(ex.get("RSI exit", {}).get("trades", 0))
        lines.append(
            f"| {row['label']} | {s['trades']} | **{s['net_pnl_rs']:,.0f}** | "
            f"{s['sharpe']:.3f} | {atr_n} | {ts_n} | {rsi_n} |"
        )

    baseline = results[0]["stats"]["net_pnl_rs"]
    best = max(results, key=lambda r: r["stats"]["net_pnl_rs"])
    lines.extend([
        "",
        f"**Baseline (no time stop):** ₹{baseline:,.0f}",
        f"**Best variant:** {best['label']} — ₹{best['stats']['net_pnl_rs']:,.0f}",
        "",
    ])
    with open(args.output_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
