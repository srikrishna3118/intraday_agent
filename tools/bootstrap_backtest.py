#!/usr/bin/env python3
"""Bootstrap trade journal from historical 15m walk-forward backtest."""

from __future__ import annotations

import argparse
import logging
import sys

from intraday_agent.config import Config
from intraday_agent.learning.backtest import simulate_symbol
from intraday_agent.learning.journal import TradeJournal
from intraday_agent.learning.research_data import (
    init_research_session,
    load_symbol_dfs,
    normalize_source,
    source_label,
)
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import get_strategy, list_strategies
from intraday_agent.universe import NIFTY_50

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed trade journal from backtest")
    parser.add_argument("--days", type=int, default=60, help="History days to fetch")
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Comma-separated symbols (default: full Nifty 50)",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not clear prior backtest rows from journal",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="",
        help=f"Strategy key (default: Config.STRATEGY={Config.STRATEGY}). "
        f"Choices: {', '.join(list_strategies())}",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="",
        help="cache | angel | yahoo (default: RESEARCH_DATA_SOURCE=cache, offline parquet)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logger()

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else list(NIFTY_50)
    )

    source = normalize_source(args.source or None)
    _, broker = init_research_session(source)

    logger.info(
        "Bootstrap backtest: %d symbols, ~%d days, source=%s",
        len(symbols),
        args.days,
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

    journal = TradeJournal()
    if not args.keep_existing:
        removed = journal.clear_source("backtest")
        if removed:
            logger.info("Cleared %d prior backtest rows", removed)

    strategy = get_strategy(args.strategy or None)
    total = 0

    logger.info("Strategy: %s | data: %s", args.strategy or Config.STRATEGY, source_label(source))

    for symbol in symbols:
        df = symbol_dfs.get(symbol.upper())
        if df is None or df.empty:
            logger.warning("No candles for %s — skipping", symbol)
            continue

        trades = simulate_symbol(symbol, df, strategy, journal)
        total += len(trades)
        logger.info("%s: %d simulated trades", symbol, len(trades))

    summary = {
        "symbols": len(symbol_dfs),
        "total_trades": total,
        "journal_path": journal.db_path,
        "journal_count": journal.trade_count(),
        "data_source": source,
    }
    summary.update(journal.summary(source="backtest"))
    logger.info("Done: %s", summary)
    print(f"\n--- Backtest summary ({source_label(source)}) ---")
    print(f"Trades: {summary['total_trades']}")
    print(f"Gross P&L: ₹{summary['gross_pnl_rs']:,.0f}")
    print(f"Est. costs: ₹{summary['total_costs_rs']:,.0f} ({summary['cost_model']})")
    print(f"Net P&L:   ₹{summary['net_pnl_rs']:,.0f}")
    print(f"Avg net/trade: ₹{summary['avg_net_per_trade_rs']:,.1f}")
    print(f"Journal: {summary['journal_path']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
