#!/usr/bin/env python3
"""NIFTY F&O smoke + synthetic checks (paper only, no live orders)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from intraday_agent.config import Config
from intraday_agent.instruments_fno import (
    historical_weekly_expiry,
    trading_dte,
)
from intraday_agent.learning.costs import fno_leg_cost, trade_cost_for_row
from intraday_agent.logging_setup import setup_logger
from intraday_agent.orders_fno import FnOOrderManager, OptionLeg, OptionPosition
from intraday_agent.strategy_fno import (
    forecast_remaining_log_move,
    session_slice,
    strike_distance_points,
    trend_state,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Angel SmartAPI NIFTY F&O smoke test")
    parser.add_argument("--underlying", default="NIFTY", help="Index underlying to test")
    parser.add_argument(
        "--weekly-only",
        action="store_true",
        help="Force weekly expiry listing in the live probe",
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
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run synthetic checks only (no Angel login)",
    )
    parser.add_argument(
        "--skip-capture",
        action="store_true",
        help="Skip the two-contract 1-min capture",
    )
    return parser.parse_args()


def _fail(ok: list[str], errors: list[str], msg: str) -> None:
    errors.append(msg)
    print(f"[FAIL] {msg}")


def _ok(ok: list[str], msg: str) -> None:
    ok.append(msg)
    print(f"[OK]   {msg}")


def run_synthetics() -> tuple[list[str], list[str]]:
    ok: list[str] = []
    errors: list[str] = []

    rows = []
    start = datetime(2026, 3, 3, 9, 15)
    price = 22000.0
    for i in range(30):
        price += 8 if i < 15 else -3
        rows.append(
            {
                "datetime": start + timedelta(minutes=5 * i),
                "open": price - 2,
                "high": price + 4,
                "low": price - 4,
                "close": price,
                "volume": 1000,
            }
        )
    df = pd.DataFrame(rows)
    if trend_state(df, at=datetime(2026, 3, 3, 10, 30)) != "bull":
        _fail(ok, errors, "trend_state did not flag a rising EMA stack as bull")
    else:
        _ok(ok, "trend_state bull on synthetic rising stack")

    bear = df.copy()
    bear["close"] = 23000 - bear.index.to_series() * 12
    bear["open"] = bear["close"] + 2
    bear["high"] = bear["close"] + 3
    bear["low"] = bear["close"] - 3
    if trend_state(bear, at=datetime(2026, 3, 3, 10, 30)) != "bear":
        _fail(ok, errors, "trend_state did not flag a falling stack as bear")
    else:
        _ok(ok, "trend_state bear on synthetic falling stack")

    sliced = session_slice(df, date(2026, 3, 3), datetime.strptime("09:15", "%H:%M").time(), datetime.strptime("10:00", "%H:%M").time())
    day_range = float(df["high"].max() - df["low"].min())
    part_range = float(sliced["high"].max() - sliced["low"].min())
    if day_range <= 0 or part_range <= 0 or part_range > day_range + 1e-9:
        _fail(ok, errors, "session range breakdown invalid")
    else:
        _ok(ok, f"range breakdown 09:15-10:00 / day = {part_range / day_range:.2f}")

    thu = historical_weekly_expiry(date(2025, 8, 25))
    tue = historical_weekly_expiry(date(2026, 9, 22))
    if thu != date(2025, 8, 28) or tue != date(2026, 9, 22):
        _fail(ok, errors, f"historical expiry wrong: thu={thu} tue={tue}")
    elif trading_dte(date(2026, 9, 22), date(2026, 9, 22)) != 0:
        _fail(ok, errors, "trading_dte expiry day is not 0")
    else:
        _ok(ok, "expiry selection / trading_dte (Thu-era + Tue-era + DTE=0)")

    dist = strike_distance_points(25000, 0.0001, min_distance_pct=0.4)
    floor = 25000 * 0.004
    if dist + 1e-6 < floor:
        _fail(ok, errors, f"remaining-vol floor broken: {dist} < {floor}")
    else:
        _ok(ok, f"remaining-vol strike floor {dist:.1f} pts on 25000 spot")
    wide = strike_distance_points(25000, 0.02, min_distance_pct=0.4)
    if wide <= floor:
        _fail(ok, errors, "remaining-vol wide forecast did not exceed the floor")
    else:
        _ok(ok, f"remaining-vol forecast distance {wide:.1f} pts")

    model_move = forecast_remaining_log_move(1e-6, 12.0, {"intercept": 0, "coef_morning_rv": 0.65, "coef_vix": 0.35, "resid_scale": 0.2, "t_crit": 1.28})
    if model_move <= 0:
        _fail(ok, errors, "forecast_remaining_log_move returned non-positive")
    else:
        _ok(ok, "forecast_remaining_log_move positive")

    tmpdir = tempfile.mkdtemp(prefix="fno_smoke_")
    persist = os.path.join(tmpdir, "open.json")
    journal_path = os.path.join(tmpdir, "journal.db")
    from intraday_agent.learning.journal import TradeJournal

    journal = TradeJournal(journal_path)
    mgr = FnOOrderManager(broker=None, journal=journal, persist_path=persist)
    now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    expiry = date.today()
    def _leg(leg_id: str, side: str, opt: str, strike: float, group: str, price: float) -> OptionLeg:
        return OptionLeg(
            leg_id=leg_id,
            underlying="NIFTY",
            tradingsymbol=f"NIFTY{int(strike)}{opt}",
            symboltoken=leg_id,
            exchange="NFO",
            expiry=expiry,
            strike=strike,
            option_type=opt,
            side=side,
            quantity=65,
            entry_price=price,
            entry_time=now,
            stop_pct=20.0,
            stop_kind="short_rise" if side == "SHORT" else None,
            group=group,
        )

    pos = OptionPosition(
        position_id="TESTFLY",
        strategy_name="time_based_iron_fly",
        underlying="NIFTY",
        expiry=expiry,
        legs={
            "ATM_CE_SHORT": _leg("ATM_CE_SHORT", "SHORT", "CE", 25000, "CALL_SIDE", 100),
            "WING_CE_LONG": _leg("WING_CE_LONG", "LONG", "CE", 25200, "CALL_SIDE", 40),
            "ATM_PE_SHORT": _leg("ATM_PE_SHORT", "SHORT", "PE", 25000, "PUT_SIDE", 110),
            "WING_PE_LONG": _leg("WING_PE_LONG", "LONG", "PE", 24800, "PUT_SIDE", 45),
        },
        entry_time=now,
        strategy_key="time_based_straddle",
    )
    if not pos.has_defined_risk():
        _fail(ok, errors, "iron fly should be defined-risk")
    else:
        _ok(ok, "defined-risk iron fly accepted")
    mgr.positions[pos.position_id] = pos
    call_px = {"ATM_CE_SHORT": 125.0, "WING_CE_LONG": 52.0, "ATM_PE_SHORT": 90.0, "WING_PE_LONG": 30.0}
    result = mgr.close_group("TESTFLY", "CALL_SIDE", exit_reason="ATM_CE_SHORT leg stop (20.0%)", price_overrides=call_px)
    if not result.get("success") or not result.get("partial"):
        _fail(ok, errors, f"close_group did not stay partial: {result}")
    elif not pos.is_open():
        _fail(ok, errors, "put side should still be open after call-side stop")
    else:
        ce_pnl = (100 - 125) * 65 + (52 - 40) * 65
        _ok(ok, f"side-group close kept put side; call-side mark PnL {ce_pnl:.0f}")

    rest = {"ATM_CE_SHORT": 125.0, "WING_CE_LONG": 52.0, "ATM_PE_SHORT": 80.0, "WING_PE_LONG": 25.0}
    closed = mgr.close_position("TESTFLY", exit_reason="15:10 time square-off", price_overrides=rest)
    if not closed.get("success"):
        _fail(ok, errors, f"final close failed: {closed}")
    else:
        expected = (100 - 125) * 65 + (52 - 40) * 65 + (110 - 80) * 65 + (25 - 45) * 65
        if abs((closed.get("pnl") or 0) - expected) > 0.01:
            _fail(ok, errors, f"side-group PnL {closed.get('pnl')} != {expected}")
        else:
            _ok(ok, f"side-group full-structure PnL {expected:.0f}")

    trades = journal.fetch_trades(source="paper_fno")
    if not trades:
        _fail(ok, errors, "journal missing paper_fno row")
    else:
        legs = json.loads(trades[0]["legs_json"] or "[]")
        reasons = {leg["leg_id"]: leg.get("exit_reason") for leg in legs}
        if reasons.get("ATM_CE_SHORT") != "ATM_CE_SHORT leg stop (20.0%)":
            _fail(ok, errors, f"per-leg exit missing: {reasons}")
        else:
            _ok(ok, "legs_json stores per-leg exit reasons")

    four = [
        {"side": "SHORT", "quantity": 65, "entry_price": 100, "exit_price": 80},
        {"side": "SHORT", "quantity": 65, "entry_price": 110, "exit_price": 90},
        {"side": "LONG", "quantity": 65, "entry_price": 40, "exit_price": 30},
        {"side": "LONG", "quantity": 65, "entry_price": 45, "exit_price": 35},
    ]
    two = four[:2]
    c4 = trade_cost_for_row({"legs_json": json.dumps(four)})
    c2 = trade_cost_for_row({"legs_json": json.dumps(two)})
    if c4 <= c2 or abs(c4 - sum(fno_leg_cost(leg) for leg in four)) > 0.05:
        _fail(ok, errors, f"F&O cost formula mismatch 4-leg={c4} 2-leg={c2}")
    else:
        _ok(ok, f"F&O costs 4-leg ₹{c4:.0f} vs 2-leg ₹{c2:.0f}")

    yesterday = datetime.now() - timedelta(days=1)
    stale = OptionPosition(
        position_id="STALE1",
        strategy_name="time_based_iron_fly",
        underlying="NIFTY",
        expiry=yesterday.date(),
        legs={"L1": _leg("L1", "LONG", "CE", 25000, "CALL_SIDE", 50)},
        entry_time=yesterday,
        strategy_key="ema920_option_buy",
    )
    stale_path = os.path.join(tmpdir, "stale.json")
    Path(stale_path).write_text(
        json.dumps({"saved_at": yesterday.isoformat(), "positions": [stale.to_json()]}),
        encoding="utf-8",
    )
    stale_journal = TradeJournal(os.path.join(tmpdir, "stale.db"))
    restored = FnOOrderManager(broker=None, journal=stale_journal, persist_path=stale_path)
    if restored.get_open_positions():
        _fail(ok, errors, "stale yesterday position was restored as open")
    else:
        stale_rows = stale_journal.fetch_trades(source="paper_fno")
        if not stale_rows or stale_rows[0].get("exit_reason") != "restart_stale":
            _fail(ok, errors, f"stale close reason wrong: {stale_rows}")
        else:
            _ok(ok, "prior-day persist restore closed as restart_stale")

    same_day = OptionPosition(
        position_id="TODAY1",
        strategy_name="ema920_credit_spread",
        underlying="NIFTY",
        expiry=date.today(),
        legs={"S": _leg("S", "SHORT", "PE", 25000, "PUT_SIDE", 80), "H": _leg("H", "LONG", "PE", 24800, "PUT_SIDE", 30)},
        entry_time=datetime.now(),
        strategy_key="ema920_credit_spread",
    )
    live_path = os.path.join(tmpdir, "live.json")
    Path(live_path).write_text(
        json.dumps({"saved_at": datetime.now().isoformat(), "positions": [same_day.to_json()]}),
        encoding="utf-8",
    )
    live_mgr = FnOOrderManager(broker=None, journal=TradeJournal(os.path.join(tmpdir, "live.db")), persist_path=live_path)
    opened = live_mgr.get_open_positions()
    if len(opened) != 1 or opened[0].position_id != "TODAY1":
        _fail(ok, errors, f"same-day restore failed: {opened}")
    else:
        _ok(ok, "same-day persist restore kept the open structure")

    naked = OptionPosition(
        position_id="NAKED",
        strategy_name="bad",
        underlying="NIFTY",
        expiry=date.today(),
        legs={"S": _leg("S", "SHORT", "CE", 25000, "CALL_SIDE", 90)},
        entry_time=datetime.now(),
    )
    if naked.has_defined_risk():
        _fail(ok, errors, "naked short marked defined-risk")
    else:
        _ok(ok, "naked short rejected by defined-risk check")

    return ok, errors


def run_live(args: argparse.Namespace, ok: list[str], errors: list[str]) -> int:
    from intraday_agent.broker import AngelBroker
    from intraday_agent.instruments_fno import get_fno_registry
    from intraday_agent.strategy_fno import TimeBasedStraddleStrategy

    try:
        Config.validate()
        _ok(ok, "Config validated")
    except ValueError as exc:
        _fail(ok, errors, f"Config: {exc}")
        return 1

    underlying = args.underlying.upper().strip()
    weekly_only = args.weekly_only or Config.FNO_WEEKLY_ONLY
    try:
        registry = get_fno_registry()
        expiries = registry.list_expiries(underlying, weekly_only=weekly_only)[:3]
        nearest = registry.nearest_expiry(underlying)
        if not expiries or nearest is None:
            _fail(ok, errors, f"No expiries found for {underlying}")
            return 1
        _ok(ok, f"Registry {underlying} nearest={nearest.isoformat()} next={', '.join(e.isoformat() for e in expiries)}")
    except Exception as exc:
        _fail(ok, errors, f"F&O registry: {exc}")
        return 1

    spot_inst = registry.resolve_underlying_spot(underlying)
    if not spot_inst:
        _fail(ok, errors, f"No spot instrument for {underlying}")
        return 1
    _ok(ok, f"Spot instrument {spot_inst['tradingsymbol']} token {spot_inst['symboltoken']}")

    broker = AngelBroker()
    try:
        if not broker.login():
            _fail(ok, errors, "Angel login rejected")
            return 1
        _ok(ok, "Angel login")

        spot_price = args.spot or broker.get_ltp_for_instrument(spot_inst)
        if not spot_price:
            _fail(ok, errors, f"No spot LTP for {underlying}")
            return 1
        _ok(ok, f"Spot LTP {spot_price:.2f}")

        strategy = TimeBasedStraddleStrategy(
            registry,
            underlying=underlying,
            weekly_only=weekly_only,
            hedge_wing_points=args.wing_points,
        )
        plan = strategy.build_entry_plan(float(spot_price))
        if plan is None:
            _fail(ok, errors, f"Could not build entry plan for {underlying}")
            return 1
        _ok(ok, f"Entry plan {plan.strategy_name} expiry={plan.expiry.isoformat()} strike={plan.strike:.2f} legs={len(plan.leg_specs)}")

        batch = broker.get_ltp_batch([spec["instrument"] for spec in plan.leg_specs])
        if len(batch) < 2:
            _fail(ok, errors, f"get_ltp_batch returned {len(batch)} tokens")
        else:
            _ok(ok, f"get_ltp_batch {len(batch)} tokens")

        for spec in plan.leg_specs:
            instrument = spec["instrument"]
            ltp = batch.get(str(instrument["symboltoken"])) or broker.get_ltp_for_instrument(instrument)
            if not ltp:
                _fail(ok, errors, f"No LTP for {instrument['tradingsymbol']}")
                return 1
            spec["price"] = float(ltp)
            _ok(ok, f"{spec['leg_id']}: {instrument['tradingsymbol']} {spec['side']} x{spec['quantity']} @ {ltp:.2f}")

        margin = broker.get_basket_margin(plan.leg_specs)
        if margin is None:
            _fail(ok, errors, "get_basket_margin returned None")
        else:
            _ok(ok, f"get_basket_margin ₹{margin:,.0f}")

        greeks = broker.get_option_greeks(underlying, plan.expiry)
        now = datetime.now()
        after_hours = now.weekday() >= 5 or now.time() < datetime.strptime("09:15", "%H:%M").time() or now.time() > datetime.strptime("15:40", "%H:%M").time()
        if not greeks and after_hours:
            _ok(ok, "optionGreek called (no chain after hours — expected)")
        elif not greeks:
            _fail(ok, errors, "optionGreek returned no rows")
        else:
            _ok(ok, f"optionGreek {len(greeks)} rows")

        sample = plan.leg_specs[0]
        formula = fno_leg_cost(
            {
                "side": sample["side"],
                "quantity": sample["quantity"],
                "entry_price": sample.get("price") or 100,
                "exit_price": sample.get("price") or 100,
            }
        )
        charges = broker.estimate_charges(
            [
                {
                    "product_type": "INTRADAY",
                    "transaction_type": "SELL" if sample["side"] == "SHORT" else "BUY",
                    "quantity": str(sample["quantity"]),
                    "price": str(sample.get("price") or 100),
                    "exchange": sample["instrument"].get("exchange", "NFO"),
                    "symbol_name": sample["instrument"].get("tradingsymbol"),
                    "token": sample["instrument"].get("symboltoken"),
                }
            ]
        )
        if charges is None:
            _ok(ok, f"estimateCharges unavailable; formula ₹{formula:.2f}")
        else:
            _ok(ok, f"estimateCharges vs formula ₹{formula:.2f}: {json.dumps(charges)[:180]}")

        if not args.skip_candles:
            spot_df = broker.get_candles_for_instrument(spot_inst, lookback=args.lookback)
            if spot_df is None or spot_df.empty:
                _fail(ok, errors, f"No spot candles for {underlying}")
            else:
                _ok(ok, f"Spot candles {len(spot_df)} bars")
            for spec in plan.leg_specs[:2]:
                instrument = spec["instrument"]
                df = broker.get_candles_for_instrument(instrument, lookback=args.lookback)
                if df is None or df.empty:
                    _fail(ok, errors, f"No candles for {instrument['tradingsymbol']}")
                else:
                    _ok(ok, f"Leg candles {instrument['tradingsymbol']} -> {len(df)} bars")

        if not args.skip_capture:
            from intraday_agent.learning.fno_candle_store import capture_session

            cap = capture_session(
                broker,
                date.today(),
                registry=registry,
                contracts=[plan.leg_specs[0]["instrument"], plan.leg_specs[1]["instrument"]],
            )
            if not cap.get("success"):
                _fail(ok, errors, f"two-contract capture failed: {cap}")
            else:
                _ok(ok, f"two-contract capture {cap.get('summary')}")

        return 0 if not errors else 1
    except Exception as exc:
        _fail(ok, errors, f"live smoke: {exc}")
        return 1
    finally:
        broker.logout()


def main() -> int:
    args = parse_args()
    setup_logger()
    print("\n" + "=" * 60)
    print("Angel SmartAPI — NIFTY F&O Smoke / Synthetic Test")
    print("=" * 60)
    ok, errors = run_synthetics()
    live_rc = 0
    if not args.offline:
        live_rc = run_live(args, ok, errors)
    print("\n" + "=" * 60)
    print(f"{len(ok)} passed, {len(errors)} failed")
    if errors:
        for item in errors:
            print(f"  - {item}")
    else:
        print("All F&O checks passed [no real orders placed]")
        if args.offline:
            print("Offline only. Live probe: python tools/fno_smoke_test.py")
        else:
            print("Next: python run_agent.py --mode both   (market hours, paper)")
    print("=" * 60 + "\n")
    return 1 if errors or live_rc else 0


if __name__ == "__main__":
    sys.exit(main())
