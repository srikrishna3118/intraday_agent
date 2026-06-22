#!/usr/bin/env python3
"""Tier 4: ATR stop multiplier sensitivity on new stack (after EOD sim fix)."""

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

NEW_STACK = {
    "RSI_OVERBOUGHT": 80.0,
    "ENTRY_CUTOFF_TIME": "14:00",
    "EXCLUDED_SYMBOLS": frozenset({"ONGC", "SBIN", "BAJFINANCE"}),
    "ALLOW_LONG": False,
    "ALLOW_SHORT": True,
}

ATR_STOP_MULTS = [1.0, 1.25, 1.5]


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
    parser = argparse.ArgumentParser(description="ATR stop mult sensitivity (Tier 4)")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--tier", choices=("t1", "t2"), default="t2")
    parser.add_argument("--source", type=str, default="cache")
    parser.add_argument("--rsi-overbought", type=float, default=80.0, help="Use best from Tier 2")
    parser.add_argument("--output", type=str, default="data/research/atr_sensitivity.json")
    parser.add_argument("--verdict-path", type=str, default="data/research/atr_sensitivity.md")
    return parser.parse_args()


def stop_summary(trades: list) -> dict[str, Any]:
    stops = [t for t in trades if t.exit_reason and t.exit_reason.startswith("ATR stop")]
    if not stops:
        return {"count": 0, "net_rs": 0, "avg_loss_pct": 0}
    st = summarize_trades(stops)
    avg_loss = sum(t.pnl_pct for t in stops) / len(stops)
    return {"count": len(stops), "net_rs": st.get("net_pnl_rs", 0), "avg_loss_pct": round(avg_loss, 3)}


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
    base = {**NEW_STACK, "RSI_OVERBOUGHT": args.rsi_overbought}
    results: list[dict[str, Any]] = []

    print(f"\n=== ATR stop sensitivity (RSI>{args.rsi_overbought}) ===\n")
    for mult in ATR_STOP_MULTS:
        overrides = {**base, "ATR_STOP_MULT": mult}
        with config_override(**overrides):
            trades = simulate_portfolio(
                symbol_dfs,
                strategy=get_strategy("rsi_mr"),
                journal=None,
                source=f"atr_mult_{mult}",
                regime=regime,
            )
            stats = summarize_trades(trades)
            stops = stop_summary(trades)
        results.append({"atr_stop_mult": mult, "stats": stats, "atr_stops": stops})
        print(
            f"mult={mult:<4}  trades={stats['trades']:>3}  net=₹{stats['net_pnl_rs']:>6,.0f}  "
            f"atr_stops={stops['count']}  stop_net=₹{stops['net_rs']:,.0f}"
        )

    best = max(results, key=lambda r: r["stats"]["net_pnl_rs"])
    report = {
        "days": args.days,
        "rsi_overbought": args.rsi_overbought,
        "results": results,
        "recommendation": (
            f"Best net at ATR_STOP_MULT={best['atr_stop_mult']} "
            f"(₹{best['stats']['net_pnl_rs']:,.0f}). Validate in paper before changing .env."
        ),
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    os.makedirs(os.path.dirname(args.verdict_path) or ".", exist_ok=True)
    lines = [
        "# Tier 4 — ATR Stop Multiplier Sensitivity",
        "",
        f"Stack: RSI>{args.rsi_overbought}, hour<14, denylist. EOD square-off IST fix applied.",
        "",
        "| ATR_STOP_MULT | Trades | Gross ₹ | Net ₹ | ATR stops | Stop net ₹ |",
        "|---------------|--------|---------|-------|-----------|------------|",
    ]
    for row in results:
        s, a = row["stats"], row["atr_stops"]
        lines.append(
            f"| {row['atr_stop_mult']} | {s['trades']} | {s['gross_pnl_rs']:,.0f} | "
            f"**{s['net_pnl_rs']:,.0f}** | {a['count']} | {a['net_rs']:,.0f} |"
        )
    lines.extend(["", report["recommendation"], ""])
    with open(args.verdict_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(f"\n{report['recommendation']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
