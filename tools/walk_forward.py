#!/usr/bin/env python3
"""Walk-forward IS/OOS validation — same params, split calendar windows."""

from __future__ import annotations

import argparse
import logging
import sys

from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeJournal
from intraday_agent.learning.research_data import (
    build_regime,
    init_research_session,
    load_symbol_dfs,
    normalize_source,
    source_label,
)
from intraday_agent.learning.walk_forward import format_report, run_walk_forward
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import get_strategy, list_strategies
from intraday_agent.universe import NIFTY_50

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward validation: in-sample vs out-of-sample net P&L",
    )
    parser.add_argument("--days", type=int, default=60, help="Total history days to fetch")
    parser.add_argument("--train-days", type=int, default=40, help="In-sample trading days")
    parser.add_argument("--test-days", type=int, default=20, help="Out-of-sample trading days")
    parser.add_argument("--warmup-days", type=int, default=5, help="Warmup bars before each window")
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Comma-separated symbols (default: full Nifty 50)",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not clear prior walkforward_is/oos journal rows",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="",
        help=f"Strategy key (default: Config.STRATEGY). Choices: {', '.join(list_strategies())}",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="",
        help="cache | angel | yahoo (default: RESEARCH_DATA_SOURCE=cache)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logger()

    if args.train_days + args.test_days > args.days:
        print(
            f"Error: train-days ({args.train_days}) + test-days ({args.test_days}) "
            f"exceed --days ({args.days})",
            file=sys.stderr,
        )
        return 1

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else list(NIFTY_50)
    )

    source = normalize_source(args.source or None)
    _, broker = init_research_session(source)

    logger.info(
        "Walk-forward: %d symbols, %d train + %d test days, source=%s",
        len(symbols),
        args.train_days,
        args.test_days,
        source,
    )

    symbol_dfs = load_symbol_dfs(symbols, args.days, source, broker=broker)
    if not symbol_dfs:
        print(
            f"Error: no candle data (source={source}). "
            "Prefetch: python tools/fetch_history.py --bundle t2_180d --source angel",
            file=sys.stderr,
        )
        return 1

    regime = build_regime(args.days, source, Config.REGIME_FILTER_ENABLED, broker=broker)
    if regime is not None:
        snap = regime.snapshot()
        logger.info(
            "Regime filter: VIX=%s NIFTY=%s EMA%s=%s (%s)",
            snap.get("vix"),
            snap.get("nifty_close"),
            Config.NIFTY_EMA_PERIOD,
            snap.get("nifty_ema"),
            source_label(source),
        )

    strategy = get_strategy(args.strategy or None)
    logger.info("Strategy: %s", args.strategy or Config.STRATEGY)

    try:
        result = run_walk_forward(
            symbol_dfs,
            train_days=args.train_days,
            test_days=args.test_days,
            strategy=strategy,
            journal=TradeJournal(),
            warmup_days=args.warmup_days,
            clear_existing=not args.keep_existing,
            regime=regime,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    report = format_report(result)
    print(report)
    logger.info("Walk-forward complete: %s", result["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
