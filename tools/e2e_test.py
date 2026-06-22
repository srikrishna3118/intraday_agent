#!/usr/bin/env python3
"""End-to-end SmartAPI smoke test: login, instruments, candles, LTP, mini backtest."""

from __future__ import annotations

import argparse
import sys

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.instruments import InstrumentRegistry
from intraday_agent.learning.backtest import simulate_symbol
from intraday_agent.learning.journal import TradeJournal
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import get_strategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Angel SmartAPI end-to-end smoke test")
    parser.add_argument("--symbol", default="RELIANCE", help="Symbol to test")
    parser.add_argument("--skip-backtest", action="store_true", help="Skip mini backtest")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logger()
    symbol = args.symbol.upper()

    print("\n" + "=" * 60)
    print("Angel SmartAPI — End-to-End Test")
    print("=" * 60)

    try:
        Config.validate()
        print("[OK]   Config validated")
    except ValueError as exc:
        print(f"[FAIL] Config: {exc}")
        return 1

    try:
        registry = InstrumentRegistry()
        registry.load(force_refresh=True)
        count = len(registry._by_symbol)
        print(f"[OK]   Scrip master loaded ({count} NSE equities)")
    except Exception as exc:
        print(f"[FAIL] Scrip master: {exc}")
        return 1

    inst = registry.resolve(symbol)
    if not inst:
        print(f"[FAIL] Could not resolve symbol: {symbol}")
        return 1
    print(f"[OK]   Resolved {symbol} -> {inst['tradingsymbol']} token {inst['symboltoken']}")

    broker = AngelBroker()
    try:
        if not broker.login():
            print("[FAIL] Angel login rejected")
            return 1
        print("[OK]   Angel login")
    except Exception as exc:
        print(f"[FAIL] Angel login: {exc}")
        return 1

    df = broker.get_candles_for_symbol(symbol, lookback=50)
    if df is None or df.empty:
        print(f"[FAIL] No candle data for {symbol}")
        print("       If error AG8004 'Invalid API Key': regenerate key at")
        print("       https://smartapi.angelbroking.com/ and update ANGEL_API_KEY in .env")
        return 1
    print(f"[OK]   Candles: {len(df)} bars (latest close {df['close'].iloc[-1]:.2f})")

    ltp = broker.get_ltp_for_symbol(symbol)
    if not ltp:
        print(f"[FAIL] No LTP for {symbol}")
        return 1
    print(f"[OK]   LTP: {ltp:.2f}")

    if not args.skip_backtest:
        journal = TradeJournal()
        before = journal.trade_count()
        trades = simulate_symbol(
            symbol,
            df,
            get_strategy(),
            journal,
        )
        print(f"[OK]   Mini backtest on fetched data: {len(trades)} simulated closes")
        print(f"       Journal: {before} -> {journal.trade_count()} rows ({journal.db_path})")

    mode = "LIVE" if Config.LIVE_TRADING else "PAPER"
    print("\n" + "=" * 60)
    print(f"All checks passed [{mode} mode — no real orders placed]")
    print("Next: python run_agent.py --once  (during market hours)")
    print("=" * 60 + "\n")
    broker.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
