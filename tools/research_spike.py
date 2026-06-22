#!/usr/bin/env python3
"""Phase A: lean 6-month rsi_mr spike using the local candle store."""

from __future__ import annotations

import argparse
import logging
import sys

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.instruments import get_registry
from intraday_agent.learning.backtest import simulate_symbol
from intraday_agent.learning.candle_store import coverage
from intraday_agent.learning.metrics import evaluate_gate, summarize_trades
from intraday_agent.learning.research_data import (
    build_regime,
    needs_angel_login,
    normalize_source,
    resolve_candles,
    source_label,
)
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import get_strategy

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = "RELIANCE,SBIN,TCS,HDFCBANK,INFY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase A rsi_mr research spike")
    parser.add_argument("--months", type=int, default=6, help="History months (~30d each)")
    parser.add_argument("--symbols", type=str, default=DEFAULT_SYMBOLS)
    parser.add_argument(
        "--source",
        type=str,
        default="",
        help="angel | yahoo | cache (default: RESEARCH_DATA_SOURCE; cache = offline parquet)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Alias for --source cache",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logger()

    source = normalize_source("cache" if args.offline else (args.source or None))
    if needs_angel_login(source):
        Config.validate()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    days = max(30, args.months * 30)
    strategy = get_strategy()

    broker = None
    if needs_angel_login(source):
        get_registry().load()
        broker = AngelBroker()
        broker.login()

    regime = build_regime(days, source, Config.REGIME_FILTER_ENABLED, broker=broker)

    print(f"\n=== Phase A spike (per-symbol edge, NOT portfolio-realistic) ===")
    print(f"Strategy: {Config.STRATEGY} | ~{args.months}mo | symbols: {len(symbols)}")
    print(f"Regime filter: {'on' if Config.REGIME_FILTER_ENABLED else 'off'}")
    print(f"Data: {source_label(source)}\n")

    data_backend = "yahoo" if source == "yahoo" else "angel"
    per_symbol: dict[str, dict] = {}
    all_trades = []

    for symbol in symbols:
        df = resolve_candles(symbol, days, source, broker=broker)
        if df is None or df.empty:
            logger.warning("No data for %s", symbol)
            continue
        trades = simulate_symbol(symbol, df, strategy, journal=None, regime=regime, source="spike")
        stats = summarize_trades(trades)
        per_symbol[symbol] = stats
        all_trades.extend(trades)
        cov = coverage(symbol, data_source=data_backend)
        cov_str = f"{cov[0].date()}→{cov[1].date()}" if cov[2] else "—"
        print(
            f"{symbol:<10} tr={stats['trades']:>3} win={stats.get('win_rate_pct', 0):>5.1f}% "
            f"net=₹{stats['net_pnl_rs']:>7,.0f} sharpe={stats.get('sharpe', 0):>6.3f} "
            f"maxDD=₹{stats.get('max_drawdown_rs', 0):>6,.0f} cache={cov_str}"
        )

    aggregate = summarize_trades(all_trades)
    gate = evaluate_gate(per_symbol, aggregate)

    print("\n--- Aggregate (summed per-symbol trades) ---")
    print(f"Trades: {aggregate['trades']} | Net: ₹{aggregate['net_pnl_rs']:,.0f} | "
          f"Sharpe: {aggregate.get('sharpe', 0):.3f} | PF: {aggregate.get('profit_factor', 0):.2f}")
    print(f"\nGATE: {gate['verdict']}")
    print(f"  positive symbols: {gate['positive_symbols']}/{len(per_symbol)}")
    print()
    return 0 if gate["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
