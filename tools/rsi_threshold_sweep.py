#!/usr/bin/env python3
"""Tier 2: RSI threshold sweep on new stack (hour<14, symbol denylist)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator

from intraday_agent.config import Config
from intraday_agent.learning.metrics import summarize_trades
from intraday_agent.learning.portfolio_sim import simulate_portfolio
from intraday_agent.learning.research_data import (
    build_regime,
    init_research_session,
    load_symbol_dfs,
    normalize_source,
)
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import get_strategy

T2_SYMBOLS = [
    "RELIANCE", "SBIN", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "KOTAKBANK", "AXISBANK",
    "LT", "ITC", "BHARTIARTL", "HINDUNILVR", "MARUTI", "TATASTEEL", "TATACONSUM", "WIPRO",
    "HCLTECH", "TECHM", "SUNPHARMA", "NTPC", "ONGC", "POWERGRID", "TITAN", "M&M",
    "BAJFINANCE", "ASIANPAINT", "ULTRACEMCO", "JSWSTEEL", "INDUSINDBK", "COALINDIA",
]

NEW_STACK_BASE = {
    "ENTRY_CUTOFF_TIME": "14:00",
    "EXCLUDED_SYMBOLS": frozenset({"ONGC", "SBIN", "BAJFINANCE"}),
    "ALLOW_LONG": False,
    "ALLOW_SHORT": True,
}

RSI_LEVELS = [80, 82, 84, 85]


@contextmanager
def config_override(**overrides: Any) -> Iterator[None]:
    saved = {k: getattr(Config, k) for k in overrides}
    try:
        for k, v in overrides.items():
            setattr(Config, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(Config, k, v)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RSI threshold sweep (Tier 2)")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--tier", choices=("t1", "t2"), default="t2")
    parser.add_argument("--source", type=str, default="cache")
    parser.add_argument("--output", type=str, default="data/research/rsi_threshold_sweep.json")
    parser.add_argument("--verdict-path", type=str, default="data/research/rsi_threshold_sweep.md")
    return parser.parse_args()


def atr_stop_stats(trades: list) -> dict[str, Any]:
    stops = [t for t in trades if t.exit_reason and t.exit_reason.startswith("ATR stop")]
    stop_net = 0.0
    if stops:
        from intraday_agent.learning.metrics import summarize_trades
        stop_net = summarize_trades(stops).get("net_pnl_rs", 0)
    max_hold = 0.0
    for t in stops:
        if t.entry_time and t.exit_time:
            from intraday_agent.universe import to_ist
            hold = (to_ist(t.exit_time) - to_ist(t.entry_time)).total_seconds() / 60.0
            max_hold = max(max_hold, hold)
    return {"atr_stop_count": len(stops), "atr_stop_net_rs": stop_net, "max_atr_hold_min": round(max_hold, 1)}


def write_markdown(path: str, report: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# Tier 2 — RSI Threshold Sweep (new stack, 180d T2)",
        "",
        "Fixed: hour < 14 IST, exclude ONGC/SBIN/BAJFINANCE, EOD square-off IST fix.",
        "",
        "| RSI > | Trades | Gross ₹ | Net ₹ | Sharpe | ATR stops | ATR stop net ₹ | Max hold |",
        "|-------|--------|---------|-------|--------|-----------|----------------|----------|",
    ]
    for row in report["results"]:
        s = row["stats"]
        a = row["atr_stops"]
        lines.append(
            f"| {row['rsi_overbought']} | {s['trades']} | {s['gross_pnl_rs']:,.0f} | "
            f"**{s['net_pnl_rs']:,.0f}** | {s['sharpe']:.3f} | {a['atr_stop_count']} | "
            f"{a['atr_stop_net_rs']:,.0f} | {a['max_atr_hold_min']}m |"
        )
    lines.extend(["", report.get("recommendation", ""), ""])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main() -> int:
    args = parse_args()
    setup_logger()

    source = normalize_source(args.source or None)
    _, broker = init_research_session(source)
    symbols = T2_SYMBOLS if args.tier == "t2" else T2_SYMBOLS[:5]
    symbol_dfs = load_symbol_dfs(symbols, args.days, source, broker=broker)
    if not symbol_dfs:
        print("Error: no candle data", file=sys.stderr)
        return 1

    regime = build_regime(args.days, source, Config.REGIME_FILTER_ENABLED, broker=broker)
    results: list[dict[str, Any]] = []

    print(f"\n=== RSI threshold sweep ({args.days}d) ===\n")
    for rsi in RSI_LEVELS:
        overrides = {**NEW_STACK_BASE, "RSI_OVERBOUGHT": float(rsi)}
        with config_override(**overrides):
            trades = simulate_portfolio(
                symbol_dfs,
                strategy=get_strategy("rsi_mr"),
                journal=None,
                source=f"rsi_sweep_{rsi}",
                regime=regime,
            )
            stats = summarize_trades(trades)
            atr = atr_stop_stats(trades)
        row = {"rsi_overbought": rsi, "stats": stats, "atr_stops": atr}
        results.append(row)
        print(
            f"RSI>{rsi:<2}  trades={stats['trades']:>3}  gross=₹{stats['gross_pnl_rs']:>6,.0f}  "
            f"net=₹{stats['net_pnl_rs']:>6,.0f}  atr_stops={atr['atr_stop_count']}"
        )

    best = max(results, key=lambda r: r["stats"]["net_pnl_rs"])
    report = {
        "days": args.days,
        "stack": NEW_STACK_BASE,
        "results": results,
        "recommendation": (
            f"Best net: **RSI > {best['rsi_overbought']}** "
            f"(₹{best['stats']['net_pnl_rs']:,.0f}, {best['stats']['trades']} trades). "
            "Tier 1 paper: keep **RSI>80** for trade count; consider RSI>84 only after paper confirms sim."
        ),
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    write_markdown(args.verdict_path, report)
    print(f"\n{report['recommendation']}")
    print(f"Report: {args.verdict_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
