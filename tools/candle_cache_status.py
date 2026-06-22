#!/usr/bin/env python3
"""Report local parquet candle cache coverage (offline research)."""

from __future__ import annotations

import argparse
import json
import os
import sys

from intraday_agent.config import Config
from intraday_agent.learning.candle_store import coverage, export_manifest, list_cached


def _format_row(key: str, cov: tuple, min_bars: int = 0) -> str:
    cmin, cmax, n = cov
    if n == 0:
        return f"  {key:<14} — missing"
    ok = "ok" if n >= min_bars else "thin"
    return f"  {key:<14} {cmin.date()} → {cmax.date()}  ({n:4d} bars) [{ok}]"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect local candle parquet cache")
    parser.add_argument(
        "--source",
        choices=("angel", "yahoo"),
        default="angel",
        help="Parquet store backend (default: angel)",
    )
    parser.add_argument(
        "--bundle",
        type=str,
        default="",
        help="Bundle name under research/bundles/ (e.g. t2_180d)",
    )
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Write data/research/candle_cache_<bundle>.json",
    )
    parser.add_argument("--min-bars", type=int, default=500, help="Flag rows below this bar count")
    return parser.parse_args()


def _load_bundle(name: str) -> dict:
    path = os.path.join("research", "bundles", f"{name}.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Bundle not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    args = parse_args()
    interval = Config.CANDLE_INTERVAL
    keys: list[str]

    if args.bundle:
        bundle = _load_bundle(args.bundle)
        keys = list(bundle.get("symbols", [])) + list(bundle.get("indexes", []))
        print(f"Bundle: {bundle.get('name')} ({len(keys)} keys, {bundle.get('days')}d)")
    else:
        keys = list_cached(data_source=args.source, interval=interval)
        print(f"All cached keys ({args.source}): {len(keys)}")

    missing = []
    for key in keys:
        cov = coverage(key, interval, data_source=args.source)
        print(_format_row(key.upper(), cov, args.min_bars))
        if cov[2] == 0:
            missing.append(key.upper())

    if missing:
        print(f"\nMissing: {', '.join(missing)}")
        print("Prefetch: python tools/fetch_history.py --days 180 --source angel --bundle t2_180d")
        return 1

    if args.write_manifest:
        manifest = export_manifest(
            keys,
            data_source=args.source,
            interval=interval,
            days=_load_bundle(args.bundle).get("days") if args.bundle else None,
            bundle_name=args.bundle or None,
        )
        print(f"\nManifest: {manifest['manifest_path']}")

    print("\nOffline research (no Angel login):")
    print("  python tools/research_validation.py --days 180 --tier t2 --source cache --skip-sizing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
