#!/usr/bin/env python3
"""Export trade journal to CSV for external analysis."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from intraday_agent.config import Config
from intraday_agent.learning.costs import apply_costs
from intraday_agent.learning.journal import TradeJournal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export trade journal to CSV")
    parser.add_argument("--source", default="", help="Filter: backtest, paper, live")
    parser.add_argument(
        "--output",
        default="",
        help="Output CSV path (default: data/exports/trades_YYYYMMDD.csv)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journal = TradeJournal()

    tag = datetime.now().strftime("%Y%m%d")
    source_tag = args.source or "all"
    default_path = os.path.join(Config.DATA_DIR, "exports", f"trades_{source_tag}_{tag}.csv")
    out_path = args.output or default_path

    count = journal.export_csv(out_path, source=args.source or None)
    if count == 0:
        print("No trades to export. Run backtest or paper trading first.")
        return 1

    import pandas as pd

    df = pd.read_csv(out_path)
    df = apply_costs(df)
    df.to_csv(out_path, index=False)

    pnl = journal.summary(source=args.source or None)
    print(f"Exported {count} trades -> {out_path}")
    print(f"Gross: ₹{pnl['gross_pnl_rs']:,.0f}  |  Net: ₹{pnl['net_pnl_rs']:,.0f}  ({pnl['cost_model']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
