"""Estimated Angel One MIS round-trip costs for net P&L reporting."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from intraday_agent.config import Config


def trade_cost(
    entry_price: float | None = None,
    quantity: int | None = None,
    *,
    units: int = 1,
) -> float:
    """Estimated all-in cost for one completed trade (entry + exit).

    Uses flat ``ESTIMATED_COST_PER_TRADE`` when > 0, else Angel MIS formula.
    """
    if Config.ESTIMATED_COST_PER_TRADE > 0:
        return Config.ESTIMATED_COST_PER_TRADE * max(1, int(units))

    notional = max(0.0, float(entry_price or 0) * float(quantity or 0))
    if notional <= 0:
        return 0.0

    # Angel intraday: lower of ₹20 or 0.1% per order, min ₹5 (Nov 2025 schedule)
    per_order = min(20.0, notional * 0.001)
    per_order = max(5.0, per_order)
    brokerage = 2 * per_order
    stt = notional * 0.00025  # sell side
    exchange = notional * 0.0000345 * 2
    stamp = notional * 0.00003  # buy side (approx)
    subtotal = brokerage + stt + exchange + stamp
    gst = subtotal * 0.18
    return round(subtotal + gst, 2)


def _parse_legs_json(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [leg for leg in raw if isinstance(leg, dict)]
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [leg for leg in parsed if isinstance(leg, dict)]


def trade_cost_for_row(row: dict[str, Any] | Any) -> float:
    """Estimated round-trip cost for a journal row.

    Multi-leg F&O trades use ``legs_json`` and sum one round-trip estimate per
    leg, which keeps flat-cost and formula-cost modes from undercounting a
    2-leg or 4-leg structure as a single stock trade.
    """
    get = row.get if isinstance(row, dict) else getattr
    legs = _parse_legs_json(get("legs_json") if isinstance(row, dict) else get(row, "legs_json", None))
    if legs:
        total = 0.0
        for leg in legs:
            total += trade_cost(leg.get("entry_price"), leg.get("quantity"), units=1)
        return round(total, 2)

    if isinstance(row, dict):
        return trade_cost(row.get("entry_price"), row.get("quantity"), units=1)
    return trade_cost(get(row, "entry_price", None), get(row, "quantity", None), units=1)


def apply_costs(df: pd.DataFrame) -> pd.DataFrame:
    """Add trade_cost_rs and net_pnl_amount columns."""
    out = df.copy()
    out["trade_cost_rs"] = out.apply(trade_cost_for_row, axis=1)
    out["net_pnl_amount"] = out["pnl_amount"] - out["trade_cost_rs"]
    return out


def summarize_pnl(rows: list[dict[str, Any]] | pd.DataFrame) -> dict[str, Any]:
    """Gross and net totals from journal rows."""
    df = pd.DataFrame(rows) if isinstance(rows, list) else rows.copy()
    if df.empty:
        return {
            "trades": 0,
            "gross_pnl_rs": 0,
            "total_costs_rs": 0,
            "net_pnl_rs": 0,
            "avg_cost_per_trade_rs": trade_cost(),
            "avg_net_per_trade_rs": 0,
        }

    df["pnl_amount"] = pd.to_numeric(df["pnl_amount"], errors="coerce").fillna(0)
    df = apply_costs(df)
    gross = float(df["pnl_amount"].sum())
    costs = float(df["trade_cost_rs"].sum())
    net = float(df["net_pnl_amount"].sum())
    n = len(df)
    return {
        "trades": n,
        "gross_pnl_rs": round(gross, 0),
        "total_costs_rs": round(costs, 0),
        "net_pnl_rs": round(net, 0),
        "avg_cost_per_trade_rs": round(costs / n, 1) if n else trade_cost(),
        "avg_gross_per_trade_rs": round(gross / n, 1) if n else 0,
        "avg_net_per_trade_rs": round(net / n, 1) if n else 0,
        "cost_model": (
            f"flat ₹{Config.ESTIMATED_COST_PER_TRADE}/round-trip leg (MULTI rows sum legs)"
            if Config.ESTIMATED_COST_PER_TRADE > 0
            else "angel_mis_formula"
        ),
    }
