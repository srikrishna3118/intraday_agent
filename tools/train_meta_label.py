#!/usr/bin/env python3
"""Train and evaluate logistic meta-label filter on trade journal labels."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeJournal
from intraday_agent.learning.meta_label import (
    build_dataset,
    save_meta_model,
    train_meta_model,
    walk_forward_evaluate,
)
from intraday_agent.logging_setup import setup_logger

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train meta-label filter from trade journal")
    parser.add_argument(
        "--source",
        type=str,
        default="paper,backtest",
        help="Comma journal sources (paper weighted highest in workflow docs)",
    )
    parser.add_argument("--min-samples", type=int, default=80)
    parser.add_argument("--C", type=float, default=0.1, help="Logistic inverse regularization")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Model path (default: META_LABEL_MODEL_PATH)",
    )
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Run time-split walk-forward OOS evaluation (no save unless --train)",
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help="Fit on all filtered rows and save model artifact",
    )
    parser.add_argument("--folds", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logger()

    journal = TradeJournal()
    df = build_dataset(journal, source_filter=args.source, min_trades=args.min_samples)
    if df.empty:
        print(f"Error: no journal trades for sources={args.source}", file=sys.stderr)
        return 1

    paper_n = len(df[df["source"] == "paper"]) if "source" in df.columns else 0
    print(f"Journal samples: {len(df)} (paper={paper_n}, min={args.min_samples})")

    report: dict = {
        "samples": len(df),
        "paper_samples": paper_n,
        "sources": args.source,
        "min_samples": args.min_samples,
        "threshold": Config.META_LABEL_THRESHOLD,
    }

    if len(df) < args.min_samples:
        print(
            f"Warning: {len(df)} samples < --min-samples {args.min_samples}. "
            "Accumulate more paper trades before enabling META_LABEL_ENABLED.",
        )
        report["ready_for_live"] = False
    else:
        report["ready_for_live"] = False  # set after evaluate pass

    if args.evaluate:
        wf = walk_forward_evaluate(df, n_splits=args.folds, C=args.C)
        report["walk_forward"] = wf
        print("\n=== Walk-forward OOS meta-label ===")
        if wf.get("error"):
            print(f"  Error: {wf['error']}")
        else:
            print(
                f"  Baseline: {wf['baseline_trades']} trades | "
                f"net ₹{wf['baseline_net_pnl_rs']:,.0f} | Sharpe {wf['baseline_sharpe']:.3f}"
            )
            print(
                f"  Filtered: {wf['filtered_trades']} trades ({wf['keep_ratio']:.0%} kept) | "
                f"net ₹{wf['filtered_net_pnl_rs']:,.0f} | Sharpe {wf['filtered_sharpe']:.3f}"
            )
            print(f"  Pass (keep≥30%, Sharpe↑, net≥90% baseline): {wf.get('pass')}")
            print(
                "\n  Compare vs hand filters: "
                "python tools/research_validation.py --meta-label --skip-rolling --skip-sizing"
            )
            if wf.get("pass") and len(df) >= args.min_samples and paper_n >= 20:
                report["ready_for_live"] = True
                print("\n  Recommendation: OOS pass + paper samples — consider META_LABEL_ENABLED=true.")
            elif len(df) < args.min_samples or paper_n < 20:
                print(
                    f"\n  Recommendation: keep META_LABEL_ENABLED=false "
                    f"(need ≥{args.min_samples} total, ≥20 paper; have {len(df)}/{paper_n})."
                )
            else:
                print("\n  Recommendation: keep META_LABEL_ENABLED=false; OOS criteria not met.")

    if args.train:
        if df["label"].nunique() < 2:
            print("Error: need both wins and losses to train", file=sys.stderr)
            return 1
        pipeline, meta = train_meta_model(df, C=args.C)
        out_path = args.output or Config.META_LABEL_MODEL_PATH
        save_meta_model(out_path, pipeline, meta)
        report["model_path"] = out_path
        report["train_samples"] = meta["train_samples"]
        print(f"\nSaved model → {out_path}")

    if not args.train and not args.evaluate:
        print("Nothing to do — pass --train and/or --evaluate", file=sys.stderr)
        return 1

    os.makedirs(os.path.join(Config.DATA_DIR, "research"), exist_ok=True)
    report_path = os.path.join(Config.DATA_DIR, "research", "meta_label_report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
