#!/usr/bin/env python3
"""Orchestrate Nifty 200 research: cache status → Sprint 4/5 → Quadapt bake-off."""

from __future__ import annotations

import argparse
import subprocess
import sys

from intraday_agent.universe import symbols_for_tier


def _run(cmd: list[str], *, label: str) -> int:
    print(f"\n>>> {label}\n$ {' '.join(cmd)}\n")
    return subprocess.call(cmd)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rerun research on Nifty 200 universe")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--source", type=str, default="cache")
    p.add_argument("--skip-prefetch", action="store_true")
    p.add_argument("--prefetch-only", action="store_true")
    p.add_argument("--min-cached", type=int, default=150, help="Min symbols before sim (of 200)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    py = sys.executable

    if not args.skip_prefetch:
        rc = _run(
            [py, "tools/fetch_history.py", "--bundle", "t200_180d", "--source", "angel"],
            label="Prefetch Angel 15m cache (t200_180d bundle)",
        )
        if rc != 0:
            print("Prefetch failed — fix Angel login / rate limits and retry.")
            return rc
        if args.prefetch_only:
            return 0

    from intraday_agent.learning.research_data import load_symbol_dfs, normalize_source

    syms = symbols_for_tier("t200")
    dfs = load_symbol_dfs(syms, args.days, normalize_source(args.source), broker=None)
    print(f"\nCache coverage: {len(dfs)}/{len(syms)} symbols")
    if len(dfs) < args.min_cached:
        print(
            f"Need ≥{args.min_cached} cached symbols (have {len(dfs)}). "
            "Run: python tools/fetch_history.py --bundle t200_180d --only-missing --delay 3.0"
        )
        return 1

    out4j = "data/research/phase4_findings_t200.json"
    out4m = "data/research/PHASE4_FINDINGS_T200.md"
    out5j = "data/research/phase5_findings_t200.json"
    out5m = "data/research/PHASE5_FINDINGS_T200.md"

    for phase, outj, outm in ((4, out4j, out4m), (5, out5j, out5m)):
        base = [
            py, "tools/research_phases.py", "--phase", str(phase),
            "--tier", "t200", "--days", str(args.days), "--source", args.source,
        ]
        if phase == 4:
            base.extend(["--output-json-4", outj, "--output-md-4", outm])
        else:
            base.extend(["--output-json-5", outj, "--output-md-5", outm])
        rc = _run(base, label=f"Sprint {phase} on Nifty 200")
        if rc != 0:
            return rc

    rc = _run(
        [
            py, "tools/strategy_bakeoff.py", "--tier", "t200",
            "--days", str(args.days), "--source", args.source,
            "--candidates", "rsi_mr_paper_stack,quadapt_ml_consensus,quadapt_ml_short",
            "--skip-rolling",
            "--output", "data/research/quadapt_bakeoff_t200.json",
            "--verdict-path", "data/research/quadapt_ml_bakeoff_verdict_t200.md",
        ],
        label="Quadapt vs rsi_mr bake-off (t200)",
    )
    if rc != 0:
        return rc

    print("\n=== Nifty 200 research complete ===")
    print(f"  {out4m}\n  {out5m}\n  data/research/quadapt_ml_bakeoff_verdict_t200.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
