#!/usr/bin/env python3
"""Sequential filter ablation backtests on rsi_mr portfolio sim (180d T2 cache)."""

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
from intraday_agent.learning.sim_filters import SimEntryFilter
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import get_strategy

T2_SYMBOLS = [
    "RELIANCE", "SBIN", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "KOTAKBANK", "AXISBANK",
    "LT", "ITC", "BHARTIARTL", "HINDUNILVR", "MARUTI", "TATASTEEL", "TATACONSUM", "WIPRO",
    "HCLTECH", "TECHM", "SUNPHARMA", "NTPC", "ONGC", "POWERGRID", "TITAN", "M&M",
    "BAJFINANCE", "ASIANPAINT", "ULTRACEMCO", "JSWSTEEL", "INDUSINDBK", "COALINDIA",
]

BASELINE_NET = -4789.0
BASELINE_TRADES = 142

FILTER_TESTS: list[dict[str, Any]] = [
    {
        "id": "baseline",
        "label": "Baseline (no filter)",
        "filter": SimEntryFilter(),
    },
    {
        "id": "test1_hour_lt_14",
        "label": "Test 1: entry hour < 14 IST",
        "filter": SimEntryFilter(max_entry_hour=14),
    },
    {
        "id": "test2_rsi_gt_80",
        "label": "Test 2: RSI > 80",
        "filter": SimEntryFilter(min_rsi=80.0),
    },
    {
        "id": "test3_vol_lt_1_5",
        "label": "Test 3: volume_ratio < 1.5",
        "filter": SimEntryFilter(max_volume_ratio=1.5),
    },
    {
        "id": "test4_exclude_symbols",
        "label": "Test 4: exclude ONGC, SBIN, BAJFINANCE",
        "filter": SimEntryFilter(exclude_symbols=frozenset({"ONGC", "SBIN", "BAJFINANCE"})),
    },
    {
        "id": "test5_combined",
        "label": "Test 5: hour<14 AND RSI>80 AND vol<1.5",
        "filter": SimEntryFilter(
            max_entry_hour=14,
            min_rsi=80.0,
            max_volume_ratio=1.5,
        ),
    },
    {
        "id": "test6_pivot_proximity",
        "label": "Test 6: pivot proximity (MR at S/R)",
        "filter": SimEntryFilter(),
        "config": {
            "PIVOT_FILTER_ENABLED": True,
            "PIVOT_FILTER_MODE": "proximity",
            "PIVOT_TOUCH_PCT": 0.35,
        },
    },
    {
        "id": "test7_pivot_zone",
        "label": "Test 7: pivot zone (long below PP, short above)",
        "filter": SimEntryFilter(),
        "config": {
            "PIVOT_FILTER_ENABLED": True,
            "PIVOT_FILTER_MODE": "zone",
        },
    },
    {
        "id": "test8_pivot_both",
        "label": "Test 8: pivot zone + proximity",
        "filter": SimEntryFilter(),
        "config": {
            "PIVOT_FILTER_ENABLED": True,
            "PIVOT_FILTER_MODE": "both",
            "PIVOT_TOUCH_PCT": 0.35,
        },
    },
    {
        "id": "test9_combined_pivot",
        "label": "Test 9: hour<14 AND RSI>80 AND pivot proximity",
        "filter": SimEntryFilter(max_entry_hour=14, min_rsi=80.0),
        "config": {
            "PIVOT_FILTER_ENABLED": True,
            "PIVOT_FILTER_MODE": "proximity",
            "PIVOT_TOUCH_PCT": 0.35,
        },
    },
]


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
    parser = argparse.ArgumentParser(description="Filter ablation backtests (rsi_mr portfolio)")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--tier", choices=("t1", "t2"), default="t2")
    parser.add_argument("--source", type=str, default="cache")
    parser.add_argument(
        "--tests",
        type=str,
        default="",
        help="Comma test ids (default: all including baseline)",
    )
    parser.add_argument("--output", type=str, default="data/research/filter_backtests.json")
    parser.add_argument("--verdict-path", type=str, default="data/research/filter_backtests.md")
    return parser.parse_args()


def write_markdown(path: str, report: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# Filter Ablation Backtests — rsi_mr (180d T2 portfolio)",
        "",
        f"Baseline reference: {BASELINE_TRADES} trades, net ₹{BASELINE_NET:,.0f} "
        f"(from loss decomposition run).",
        "",
        "| Test | Trades | Gross ₹ | Costs ₹ | Net ₹ | Sharpe | Δ net vs baseline |",
        "|------|--------|---------|---------|-------|--------|-------------------|",
    ]
    for row in report["results"]:
        delta = row["stats"]["net_pnl_rs"] - BASELINE_NET
        lines.append(
            f"| {row['label']} | {row['stats']['trades']} | "
            f"{row['stats']['gross_pnl_rs']:,.0f} | {row['stats']['total_costs_rs']:,.0f} | "
            f"**{row['stats']['net_pnl_rs']:,.0f}** | {row['stats']['sharpe']:.3f} | "
            f"{delta:+,.0f} |"
        )
    lines.extend(["", "## Interpretation", "", report.get("interpretation", ""), ""])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def interpret(results: list[dict[str, Any]]) -> str:
    baseline = next((r for r in results if r["id"] == "baseline"), results[0])
    bnet = baseline["stats"]["net_pnl_rs"]
    parts = []
    singles = [
        r for r in results
        if r["id"].startswith("test") and r["id"] != "test5_combined"
    ]
    if singles:
        best = max(singles, key=lambda r: r["stats"]["net_pnl_rs"])
        parts.append(
            f"Best single filter: **{best['label']}** — net ₹{best['stats']['net_pnl_rs']:,.0f} "
            f"({best['stats']['net_pnl_rs'] - bnet:+,.0f} vs baseline), "
            f"{best['stats']['trades']} trades, Sharpe {best['stats']['sharpe']:.3f}."
        )

    test5 = next((r for r in results if r["id"] == "test5_combined"), None)
    if test5:
        parts.append(
            f"Combined Test 5: {test5['stats']['trades']} trades, "
            f"net ₹{test5['stats']['net_pnl_rs']:,.0f} "
            f"({test5['stats']['net_pnl_rs'] - bnet:+,.0f} vs baseline), "
            f"Sharpe {test5['stats']['sharpe']:.3f}."
        )

    if all(r["stats"]["net_pnl_rs"] <= 0 for r in results):
        parts.append(
            "All variants still net negative — filters may reduce damage but do not flip expectancy; "
            "ATR stop review remains next after confirming best filter stack in paper."
        )
    return " ".join(parts)


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

    test_ids = {t.strip() for t in args.tests.split(",") if t.strip()}
    tests = FILTER_TESTS
    if test_ids:
        tests = [t for t in FILTER_TESTS if t["id"] in test_ids]

    strategy = get_strategy("rsi_mr")
    regime = build_regime(args.days, source, Config.REGIME_FILTER_ENABLED, broker=broker)

    results: list[dict[str, Any]] = []
    print(f"\n=== Filter backtests ({len(symbol_dfs)} symbols, {args.days}d) ===\n")
    print(f"{'Test':<42} {'Trades':>6} {'Gross':>8} {'Net':>9} {'Sharpe':>7}")
    print("-" * 78)

    for spec in tests:
        filt: SimEntryFilter = spec["filter"]
        overrides = spec.get("config") or {}
        with config_override(**overrides):
            trades = simulate_portfolio(
                symbol_dfs,
                strategy=strategy,
                journal=None,
                source=f"filter_{spec['id']}",
                regime=regime,
                entry_filter=filt,
            )
        stats = summarize_trades(trades)
        row = {"id": spec["id"], "label": spec["label"], "filter": {
            "max_entry_hour": filt.max_entry_hour,
            "min_rsi": filt.min_rsi,
            "max_volume_ratio": filt.max_volume_ratio,
            "exclude_symbols": sorted(filt.exclude_symbols),
        }, "config": overrides, "stats": stats}
        results.append(row)
        print(
            f"{spec['label']:<42} {stats['trades']:>6} "
            f"{stats['gross_pnl_rs']:>8,.0f} {stats['net_pnl_rs']:>9,.0f} "
            f"{stats['sharpe']:>7.3f}"
        )

    report = {
        "days": args.days,
        "data_source": source,
        "strategy": "rsi_mr",
        "baseline_reference": {"trades": BASELINE_TRADES, "net_pnl_rs": BASELINE_NET},
        "results": results,
    }
    report["interpretation"] = interpret(results)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    write_markdown(args.verdict_path, report)

    print(f"\n{report['interpretation']}")
    print(f"\nJSON: {args.output}")
    print(f"Report: {args.verdict_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
