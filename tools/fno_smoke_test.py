#!/usr/bin/env python3
"""NIFTY F&O smoke test: login, resolve weekly contracts, fetch LTP, fetch candles."""

from __future__ import annotations

import argparse
import sys

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.instruments_fno import get_fno_registry
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy_fno import TimeBasedStraddleStrategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Angel SmartAPI NIFTY F&O smoke test")
    parser.add_argument("--underlying", default="NIFTY", help="Index underlying to test")
    parser.add_argument(
        "--weekly-only",
        action="store_true",
        help="Force weekly expiry selection (default follows config)",
    )
    parser.add_argument(
        "--wing-points",
        type=float,
        default=Config.FNO_HEDGE_WING_POINTS,
        help="Wing distance for the hedged plan preview",
    )
    parser.add_argument(
        "--spot",
        type=float,
        default=0.0,
        help="Optional spot override; if omitted, fetches LTP from broker",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=20,
        help="Candle lookback for spot and ATM legs",
    )
    parser.add_argument(
        "--skip-candles",
        action="store_true",
        help="Skip candle fetches and only validate contract/LTP resolution",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logger()

    print("\n" + "=" * 60)
    print("Angel SmartAPI — NIFTY F&O Smoke Test")
    print("=" * 60)

    try:
        Config.validate()
        print("[OK]   Config validated")
    except ValueError as exc:
        print(f"[FAIL] Config: {exc}")
        return 1

    underlying = args.underlying.upper().strip()
    weekly_only = args.weekly_only or Config.FNO_WEEKLY_ONLY

    try:
        registry = get_fno_registry()
        expiries = registry.list_expiries(underlying, weekly_only=weekly_only)[:3]
        if not expiries:
            print(f"[FAIL] No expiries found for {underlying}")
            return 1
        print(f"[OK]   Loaded F&O registry for {underlying} (next expiries: {', '.join(exp.isoformat() for exp in expiries)})")
    except Exception as exc:
        print(f"[FAIL] F&O registry: {exc}")
        return 1

    spot_inst = registry.resolve_underlying_spot(underlying)
    if not spot_inst:
        print(f"[FAIL] No spot instrument found for {underlying}")
        return 1
    print(f"[OK]   Spot instrument: {spot_inst['tradingsymbol']} token {spot_inst['symboltoken']}")

    broker = AngelBroker()
    try:
        if not broker.login():
            print("[FAIL] Angel login rejected")
            return 1
        print("[OK]   Angel login")

        spot_price = args.spot or broker.get_ltp_for_instrument(spot_inst)
        if not spot_price:
            print(f"[FAIL] Could not fetch spot LTP for {underlying}")
            return 1
        print(f"[OK]   Spot LTP: {spot_price:.2f}")

        strategy = TimeBasedStraddleStrategy(
            registry,
            underlying=underlying,
            weekly_only=weekly_only,
            hedge_wing_points=args.wing_points,
        )
        plan = strategy.build_entry_plan(float(spot_price))
        if plan is None:
            print(f"[FAIL] Could not build entry plan for {underlying}")
            return 1
        print(
            f"[OK]   Entry plan: {plan.strategy_name} expiry={plan.expiry.isoformat()} strike={plan.strike:.2f} legs={len(plan.leg_specs)}"
        )

        for spec in plan.leg_specs:
            instrument = spec["instrument"]
            ltp = broker.get_ltp_for_instrument(instrument)
            if not ltp:
                print(f"[FAIL] No LTP for {instrument['tradingsymbol']}")
                return 1
            print(
                f"[OK]   {spec['leg_id']}: {instrument['tradingsymbol']} {spec['side']} x{spec['quantity']} @ {ltp:.2f}"
            )

        if not args.skip_candles:
            spot_df = broker.get_candles_for_instrument(spot_inst, lookback=args.lookback)
            if spot_df is None or spot_df.empty:
                print(f"[FAIL] No spot candles for {underlying}")
                return 1
            print(f"[OK]   Spot candles: {len(spot_df)} bars")

            for spec in plan.leg_specs[:2]:
                instrument = spec["instrument"]
                df = broker.get_candles_for_instrument(instrument, lookback=args.lookback)
                if df is None or df.empty:
                    print(f"[FAIL] No candles for {instrument['tradingsymbol']}")
                    return 1
                print(f"[OK]   Leg candles: {instrument['tradingsymbol']} -> {len(df)} bars")

        print("\n" + "=" * 60)
        print("All F&O checks passed [no real orders placed]")
        print("Next: python run_agent.py --mode fno --once  (during market hours)")
        print("=" * 60 + "\n")
        return 0
    except Exception as exc:
        print(f"[FAIL] F&O smoke test: {exc}")
        return 1
    finally:
        broker.logout()


if __name__ == "__main__":
    sys.exit(main())