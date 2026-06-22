"""Risk and performance metrics from trade records."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

import pandas as pd

from intraday_agent.config import Config
from intraday_agent.learning.costs import apply_costs, summarize_pnl
from intraday_agent.learning.journal import TradeRecord

TRADING_DAYS_PER_YEAR = 252


def _rows_from_trades(trades: list[TradeRecord] | list[dict[str, Any]]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    if isinstance(trades[0], TradeRecord):
        rows = [asdict(t) for t in trades]
    else:
        rows = trades
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df["pnl_amount"] = pd.to_numeric(df.get("pnl_amount"), errors="coerce").fillna(0)
    return apply_costs(df)


def daily_net_series(trades: list[TradeRecord] | list[dict[str, Any]]) -> pd.Series:
    """Daily net P&L indexed by calendar date; zero-trade days filled with 0."""
    df = _rows_from_trades(trades)
    if df.empty:
        return pd.Series(dtype=float)

    df = df.dropna(subset=["exit_time"])
    df["day"] = df["exit_time"].dt.date
    grouped = df.groupby("day")["net_pnl_amount"].sum()

    start = min(grouped.index)
    end = max(grouped.index)
    all_days = pd.date_range(start=start, end=end, freq="D")
    daily = pd.Series(0.0, index=[d.date() for d in all_days])
    for day, val in grouped.items():
        daily[day] = float(val)
    return daily


def max_drawdown_rs(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    peak = equity_curve.cummax()
    dd = equity_curve - peak
    return float(abs(dd.min()))


def profit_factor(trades: list[TradeRecord] | list[dict[str, Any]]) -> float:
    df = _rows_from_trades(trades)
    if df.empty:
        return 0.0
    wins = df.loc[df["net_pnl_amount"] > 0, "net_pnl_amount"].sum()
    losses = abs(df.loc[df["net_pnl_amount"] < 0, "net_pnl_amount"].sum())
    if losses <= 0:
        return float(wins) if wins > 0 else 0.0
    return float(wins / losses)


def sharpe_daily(
    trades: list[TradeRecord] | list[dict[str, Any]],
    *,
    use_returns: bool = False,
    capital_base: float | None = None,
) -> float:
    """Sharpe from daily net P&L (or daily returns if use_returns=True)."""
    daily = daily_net_series(trades)
    if len(daily) < 2:
        return 0.0

    if use_returns:
        base = capital_base or (Config.MAX_POSITIONS * Config.CAPITAL_PER_TRADE)
        if base <= 0:
            return 0.0
        series = daily / base
    else:
        series = daily

    std = float(series.std())
    if std <= 0:
        return 0.0
    return float(series.mean() / std * (TRADING_DAYS_PER_YEAR ** 0.5))


def summarize_trades(
    trades: list[TradeRecord] | list[dict[str, Any]],
    *,
    use_return_sharpe: bool = False,
    capital_base: float | None = None,
) -> dict[str, Any]:
    """Combine P&L totals with Sharpe, drawdown, profit factor."""
    stats = summarize_pnl(_rows_from_trades(trades).to_dict("records") if trades else [])
    if not trades:
        stats.update({
            "sharpe": 0.0,
            "max_drawdown_rs": 0.0,
            "profit_factor": 0.0,
            "expectancy_rs": 0.0,
            "win_rate_pct": 0.0,
        })
        return stats

    df = _rows_from_trades(trades)
    wins = int((df["net_pnl_amount"] > 0).sum())
    stats["win_rate_pct"] = round(100 * wins / len(df), 1)
    stats["expectancy_rs"] = round(float(df["net_pnl_amount"].mean()), 1)
    stats["profit_factor"] = round(profit_factor(trades), 2)

    daily = daily_net_series(trades)
    equity = daily.cumsum()
    stats["max_drawdown_rs"] = round(max_drawdown_rs(equity), 0)
    stats["sharpe"] = round(
        sharpe_daily(trades, use_returns=use_return_sharpe, capital_base=capital_base),
        3,
    )
    return stats


def evaluate_gate(
    per_symbol_stats: dict[str, dict[str, Any]],
    aggregate: dict[str, Any],
    *,
    min_positive_symbols: int = 3,
) -> dict[str, Any]:
    """Phase A GO/NO-GO gate from spike results."""
    positive_symbols = sum(
        1 for s in per_symbol_stats.values() if s.get("net_pnl_rs", 0) > 0
    )
    passed = (
        aggregate.get("net_pnl_rs", 0) > 0
        and positive_symbols >= min_positive_symbols
        and aggregate.get("sharpe", 0) > 0
    )
    return {
        "passed": passed,
        "positive_symbols": positive_symbols,
        "aggregate_net": aggregate.get("net_pnl_rs", 0),
        "aggregate_sharpe": aggregate.get("sharpe", 0),
        "verdict": "GO — proceed to Phase B" if passed else "NO-GO — stop entry research",
    }
