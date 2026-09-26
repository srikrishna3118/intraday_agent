#!/usr/bin/env python3
"""Capture live NFO 1-min candles and an ATM IV snapshot (Angel only)."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.instruments_fno import get_fno_registry
from intraday_agent.learning.fno_candle_store import capture_session
from intraday_agent.logging_setup import setup_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture NIFTY option 1-min candles")
    parser.add_argument(
        "--session",
        default="",
        help="Session date YYYY-MM-DD (default: today IST)",
    )
    parser.add_argument(
        "--two-contracts",
        action="store_true",
        help="Only ATM CE and PE (smoke / rate-limit friendly)",
    )
    parser.add_argument(
        "--strike-buffer",
        type=float,
        default=None,
        help="Points around the session range (default FNO_CAPTURE_STRIKE_BUFFER)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logger()
    Config.validate()
    session = (
        date.fromisoformat(args.session)
        if args.session
        else datetime.now().date()
    )
    broker = AngelBroker()
    if not broker.login():
        print("[FAIL] Angel login rejected")
        return 1
    registry = get_fno_registry()
    contracts = None
    if args.two_contracts:
        spot_inst = registry.resolve_underlying_spot(Config.FNO_UNDERLYING)
        spot = broker.get_ltp_for_instrument(spot_inst) if spot_inst else None
        expiry = registry.nearest_expiry(Config.FNO_UNDERLYING, as_of=session)
        if spot is None or expiry is None:
            print("[FAIL] Could not resolve ATM contracts")
            broker.logout()
            return 1
        atm = registry.resolve_atm_straddle(Config.FNO_UNDERLYING, expiry, float(spot))
        if atm is None:
            print("[FAIL] No ATM straddle")
            broker.logout()
            return 1
        contracts = [atm["CE"], atm["PE"]]
        print(f"Two-contract capture: {atm['CE']['tradingsymbol']} + {atm['PE']['tradingsymbol']}")
    try:
        result = capture_session(
            broker,
            session,
            registry=registry,
            strike_buffer=args.strike_buffer,
            contracts=contracts,
        )
        print(result)
        return 0 if result.get("success") else 1
    finally:
        broker.logout()


if __name__ == "__main__":
    sys.exit(main())
