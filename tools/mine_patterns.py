#!/usr/bin/env python3
"""Mine patterns from trade journal — symbols, RSI, volume, time, exits."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeJournal
from intraday_agent.learning.patterns import PatternMiner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine patterns from trade journal")
    parser.add_argument("--source", default="", help="Filter: backtest, paper, live")
    parser.add_argument("--lookback-days", type=int, default=0, help="Limit to last N days (0=all)")
    parser.add_argument("--min-trades", type=int, default=5, help="Min trades per segment")
    parser.add_argument(
        "--output",
        default=os.path.join(Config.DATA_DIR, "reports"),
        help="Directory for JSON report",
    )
    return parser.parse_args()


def _print_section(title: str, rows: list[dict], key: str) -> None:
    if not rows:
        return
    print(f"\n{title}")
    print("-" * len(title))
    for row in rows[:8]:
        if "side" in row and key == "symbol":
            label = f"{row['symbol']} {row['side']}"
        else:
            label = row.get(key, row.get("side", "?"))
        pnl_rs = row.get("total_pnl_rs", "")
        pnl_suffix = f" | net ₹{pnl_rs}" if pnl_rs != "" else ""
        print(
            f"  {label}: {row['trades']} trades | "
            f"{row['win_rate_pct']}% win | {row['avg_pnl_pct']}% avg{pnl_suffix}"
        )


def main() -> int:
    args = parse_args()
    source = args.source or None
    lookback = args.lookback_days or None

    journal = TradeJournal()
    summary = journal.summary()
    print("\n" + "=" * 60)
    print("Trade Journal — Pattern Mining")
    print("=" * 60)
    print(f"Database: {summary['db_path']}")
    print(f"Total trades: {summary['total_trades']}  ({summary['by_source']})")

    miner = PatternMiner(journal, min_trades=args.min_trades)
    report = miner.analyze(source=source, lookback_days=lookback)

    if report.get("error"):
        print(report["error"])
        return 1

    print(f"\nFiltered: {report['trade_count']} trades | "
          f"{report['win_rate_pct']}% win")
    print(f"Gross P&L: ₹{report['gross_pnl_rs']:,.0f}  |  "
          f"Est. costs: ₹{report['total_costs_rs']:,.0f}  ({report['cost_model']})")
    print(f"Net P&L:   ₹{report['net_pnl_rs']:,.0f}  |  "
          f"Avg net/trade: ₹{report['avg_net_per_trade_rs']:,.1f}")

    if report.get("insights"):
        print("\nKey insights")
        print("------------")
        for line in report["insights"]:
            print(f"  • {line}")

    _print_section("Best symbol+side (min trades)", report["best_symbol_side"], "symbol")
    _print_section("Worst symbol+side", report["worst_symbol_side"], "symbol")
    _print_section("By RSI bucket", report["by_rsi_bucket"], "rsi_bucket")
    _print_section("By volume bucket", report["by_volume_bucket"], "volume_bucket")
    _print_section("By entry hour (IST)", report["by_entry_hour"], "hour_label")
    _print_section("By weekday", report["by_day"], "day_label")
    _print_section("By exit reason", report["by_exit_reason"], "exit_reason")
    _print_section("Long vs short", report["by_side"], "side")

    os.makedirs(args.output, exist_ok=True)
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(args.output, f"{tag}_patterns.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    print(f"\nFull report saved: {json_path}")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
