#!/usr/bin/env python3
"""Export paper trades with rich entry_features for post-mortem analysis."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

import pandas as pd

from intraday_agent.config import Config
from intraday_agent.learning.costs import apply_costs
from intraday_agent.learning.entry_features import features_from_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export paper trades with flattened features")
    parser.add_argument("--source", default="paper", help="Journal source filter (default: paper)")
    parser.add_argument("--db", default=Config.TRADE_JOURNAL_PATH)
    parser.add_argument(
        "--output",
        default=os.path.join(Config.DATA_DIR, "research", "paper_trades_export.csv"),
    )
    return parser.parse_args()


def _flatten_features(raw: str | None) -> dict:
    feats = features_from_json(raw)
    stack = feats.get("stack") or {}
    return {
        "feat_rsi": feats.get("rsi"),
        "feat_volume_ratio": feats.get("volume_ratio"),
        "feat_atr_pct": feats.get("atr_pct"),
        "feat_vwap_distance": feats.get("vwap_distance"),
        "feat_adx": feats.get("adx"),
        "feat_vix": feats.get("vix"),
        "feat_minutes_from_open": feats.get("minutes_from_open"),
        "stack_rsi_ob": stack.get("rsi_overbought"),
        "stack_cutoff": stack.get("entry_cutoff"),
        "stack_excluded": json.dumps(stack.get("excluded_symbols", [])),
        "stack_atr_stop_mult": stack.get("atr_stop_mult"),
    }


def main() -> int:
    args = parse_args()
    if not os.path.isfile(args.db):
        print(f"Journal not found: {args.db}", file=sys.stderr)
        return 1

    query = "SELECT * FROM trades WHERE source = ? ORDER BY exit_time ASC"
    with sqlite3.connect(args.db) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(query, (args.source,))]

    if not rows:
        print(f"No trades with source={args.source!r}", file=sys.stderr)
        return 1

    df = pd.DataFrame(rows)
    df = apply_costs(df)
    extras = df["entry_features"].apply(lambda raw: pd.Series(_flatten_features(raw)))
    df = pd.concat([df, extras], axis=1)

    export_cols = [
        "symbol", "side", "entry_time", "exit_time", "hold_minutes", "entry_rsi",
        "volume_ratio", "entry_price", "exit_price", "quantity", "pnl_pct", "pnl_amount",
        "net_pnl_amount", "trade_cost_rs", "exit_reason", "source",
        "feat_rsi", "feat_volume_ratio", "feat_atr_pct", "feat_vwap_distance",
        "feat_adx", "feat_vix", "feat_minutes_from_open",
        "stack_rsi_ob", "stack_cutoff", "stack_excluded", "stack_atr_stop_mult",
        "entry_features",
    ]
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    df[[c for c in export_cols if c in df.columns]].to_csv(args.output, index=False)
    print(f"Exported {len(df)} trades → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
