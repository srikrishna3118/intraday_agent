#!/usr/bin/env python3
"""Orchestrate Nifty 250 research: cache status → Sprint 4/5 → Quadapt bake-off."""

from __future__ import annotations

import argparse
import subprocess
import sys

from intraday_agent.universe import nifty250_symbols, symbols_for_tier


def _run(cmd: list[str], *, label: str) -> int:
    print(f"\n>>> {label}\n$ {' '.join(cmd)}\n")
    return subprocess.call(cmd)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rerun research on Nifty 250 universe")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--source", type=str, default="cache")
    p.add_argument("--skip-prefetch", action="store_true")
    p.add_argument("--prefetch-only", action="store_true")
    p.add_argument("--min-cached", type=int, default=200, help="Min symbols before sim (of ~260)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    py = sys.executable
    root_cmds = ["cd", "/home/acharya/trading/Auto_trading"]  # noqa: for doc only

    if not args.skip_prefetch:
        rc = _run(
            [py, "tools/fetch_history.py", "--bundle", "t250_180d", "--source", "angel"],
            label="Prefetch Angel 15m cache (t250_180d bundle)",
        )
        if rc != 0:
            print("Prefetch failed — fix Angel login / rate limits and retry.")
            return rc
        if args.prefetch_only:
            return 0

    # Coverage check
    from intraday_agent.learning.research_data import load_symbol_dfs, normalize_source

    syms = symbols_for_tier("t250")
    dfs = load_symbol_dfs(syms, args.days, normalize_source(args.source), broker=None)
    print(f"\nCache coverage: {len(dfs)}/{len(syms)} symbols")
    if len(dfs) < args.min_cached:
        print(
            f"Need ≥{args.min_cached} cached symbols for reliable t250 sim "
            f"(have {len(dfs)}). Run prefetch or lower --min-cached."
        )
        return 1

    out4j = "data/research/phase4_findings_t250.json"
    out4m = "data/research/PHASE4_FINDINGS_T250.md"
    out5j = "data/research/phase5_findings_t250.json"
    out5m = "data/research/PHASE5_FINDINGS_T250.md"

    for phase, outj, outm in ((4, out4j, out4m), (5, out5j, out5m)):
        base = [
            py,
            "tools/research_phases.py",
            "--phase",
            str(phase),
            "--tier",
            "t250",
            "--days",
            str(args.days),
            "--source",
            args.source,
        ]
        if phase == 4:
            base.extend(["--output-json-4", outj, "--output-md-4", outm])
        else:
            base.extend(["--output-json-5", outj, "--output-md-5", outm])
        rc = _run(base, label=f"Sprint {phase} on Nifty 250")
        if rc != 0:
            return rc

    rc = _run(
        [
            py,
            "tools/strategy_bakeoff.py",
            "--tier",
            "t250",
            "--days",
            str(args.days),
            "--source",
            args.source,
            "--candidates",
            "rsi_mr_paper_stack,quadapt_ml_consensus,quadapt_ml_short",
            "--skip-rolling",
            "--output",
            "data/research/quadapt_bakeoff_t250.json",
            "--verdict-path",
            "data/research/quadapt_ml_bakeoff_verdict_t250.md",
        ],
        label="Quadapt vs rsi_mr bake-off (t250)",
    )
    if rc != 0:
        return rc

    print("\n=== Nifty 250 research complete ===")
    print(f"  {out4m}")
    print(f"  {out5m}")
    print("  data/research/quadapt_ml_bakeoff_verdict_t250.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
