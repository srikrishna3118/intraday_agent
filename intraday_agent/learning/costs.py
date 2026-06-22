"""Estimated Angel One MIS round-trip costs for net P&L reporting."""

from __future__ import annotations

from typing import Any

import pandas as pd

from intraday_agent.config import Config


def trade_cost(entry_price: float | None = None, quantity: int | None = None) -> float:
    """Estimated all-in cost for one completed trade (entry + exit).

    Uses flat ``ESTIMATED_COST_PER_TRADE`` when > 0, else Angel MIS formula.
    """
    if Config.ESTIMATED_COST_PER_TRADE > 0:
        return Config.ESTIMATED_COST_PER_TRADE

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


def apply_costs(df: pd.DataFrame) -> pd.DataFrame:
    """Add trade_cost_rs and net_pnl_amount columns."""
    out = df.copy()
    if "entry_price" in out.columns and "quantity" in out.columns:
        out["trade_cost_rs"] = out.apply(
            lambda r: trade_cost(r.get("entry_price"), r.get("quantity")),
            axis=1,
        )
    else:
        out["trade_cost_rs"] = trade_cost()
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
            f"flat ₹{Config.ESTIMATED_COST_PER_TRADE}/trade"
            if Config.ESTIMATED_COST_PER_TRADE > 0
            else "angel_mis_formula"
        ),
    }
