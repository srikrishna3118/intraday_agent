#!/usr/bin/env python3
"""Prefetch historical candles into the local parquet store."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.instruments import get_registry
from intraday_agent.learning.candle_store import coverage, export_manifest
from intraday_agent.learning.research_data import (
    needs_angel_login,
    normalize_source,
    prefetch_for_research,
    source_label,
)
from intraday_agent.logging_setup import setup_logger
from intraday_agent.universe import NIFTY_50, nifty200_symbols, nifty250_symbols

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = "RELIANCE,SBIN,TCS,HDFCBANK,INFY"
BUNDLE_DIR = os.path.join("research", "bundles")


def _load_bundle(name: str) -> dict:
    path = os.path.join(BUNDLE_DIR, f"{name}.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Bundle not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prefetch OHLCV history into parquet cache")
    parser.add_argument("--days", type=int, default=180, help="Calendar days of history")
    parser.add_argument(
        "--source",
        type=str,
        default="",
        help=f"Data source: angel | yahoo (default: RESEARCH_DATA_SOURCE={Config.RESEARCH_DATA_SOURCE})",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Comma-separated symbols (default: T1 list if neither --symbols nor --index)",
    )
    parser.add_argument(
        "--index",
        type=str,
        default="",
        help="Comma-separated index keys: NIFTY, INDIAVIX",
    )
    parser.add_argument(
        "--bundle",
        type=str,
        default="",
        help="Named bundle from research/bundles/ (e.g. t2_180d)",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="",
        help=f"Candle interval (default: {Config.CANDLE_INTERVAL})",
    )
    parser.add_argument(
        "--all-nifty",
        action="store_true",
        help="Prefetch all Nifty 50 symbols",
    )
    parser.add_argument(
        "--all-nifty200",
        action="store_true",
        help="Prefetch Nifty 200 universe (100+100)",
    )
    parser.add_argument(
        "--all-nifty250",
        action="store_true",
        help="Prefetch legacy Nifty 250 universe (~260 symbols)",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="With --bundle: fetch only symbols with thin/missing cache (<500 bars)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds between symbol fetches (rate-limit friendly; default: SCREENER_DELAY_SEC)",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Skip writing data/research/candle_cache manifest",
    )
    return parser.parse_args()


def _format_coverage(key: str, cov: tuple) -> str:
    cmin, cmax, n = cov
    if n == 0:
        return f"{key:<14} — no data"
    return f"{key:<14} {cmin.date()} → {cmax.date()}  ({n} bars)"


def main() -> int:
    args = parse_args()
    setup_logger()
    source = normalize_source(args.source or None)
    if needs_angel_login(source):
        Config.validate()

    interval = args.interval or Config.CANDLE_INTERVAL
    symbols: list[str] = []
    bundle_name: str | None = None
    days = args.days

    if args.bundle:
        bundle = _load_bundle(args.bundle)
        bundle_name = bundle.get("name", args.bundle)
        days = int(bundle.get("days", days))
        symbols.extend(bundle.get("symbols", []))
        symbols.extend(bundle.get("indexes", []))
        logger.info("Loaded bundle %s (%d keys, %dd)", bundle_name, len(symbols), days)

    if args.index:
        symbols.extend(s.strip().upper() for s in args.index.split(",") if s.strip())
    if args.symbols:
        symbols.extend(s.strip().upper() for s in args.symbols.split(",") if s.strip())
    elif args.all_nifty:
        symbols.extend(NIFTY_50)
    elif args.all_nifty200:
        symbols.extend(nifty200_symbols())
    elif args.all_nifty250:
        symbols.extend(nifty250_symbols())
    elif not symbols:
        symbols.extend(s.strip().upper() for s in DEFAULT_SYMBOLS.split(",") if s.strip())

    # Dedupe while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for s in symbols:
        key = s.upper()
        if key not in seen:
            seen.add(key)
            unique.append(key)
    symbols = unique

    if args.only_missing and symbols:
        interval_key = interval
        data_src = "yahoo" if source == "yahoo" else "angel"
        missing: list[str] = []
        for s in symbols:
            cov = coverage(s, interval_key, data_source=data_src)
            if cov[2] < 500:
                missing.append(s)
        logger.info("Only-missing filter: %d / %d symbols need fetch", len(missing), len(symbols))
        symbols = missing

    broker = None
    if needs_angel_login(source):
        get_registry().load()
        broker = AngelBroker()
        broker.login()

    store_note = "data/candles/yahoo" if source == "yahoo" else Config.CANDLE_STORE_DIR
    logger.info(
        "Prefetch %d symbols/indexes, %d days, source=%s → %s",
        len(symbols),
        days,
        source,
        store_note,
    )

    summary = prefetch_for_research(
        symbols,
        days,
        source,
        broker=broker,
        interval=interval,
        sleep_sec=args.delay if args.delay > 0 else None,
    )

    print(f"\n=== Candle store coverage ({source_label(source)}) ===")
    for key in symbols:
        key = key.upper()
        cov = summary.get(key) or (None, None, 0)
        print(_format_coverage(key, cov))
    if source == "yahoo":
        print("\nNote: Yahoo 15m history is capped at ~59 calendar days.")

    if not args.no_manifest:
        data_src = "yahoo" if source == "yahoo" else "angel"
        manifest = export_manifest(
            [s.upper() for s in symbols],
            data_source=data_src,
            interval=interval,
            days=days,
            bundle_name=bundle_name,
        )
        print(f"\nManifest saved: {manifest['manifest_path']}")
        print("Offline research: python tools/research_validation.py --days 180 --tier t2 --source cache --skip-sizing")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
