"""In-sample / out-of-sample walk-forward validation."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date
from typing import Any

import pandas as pd

from intraday_agent.config import Config
from intraday_agent.learning.backtest import simulate_symbol
from intraday_agent.learning.costs import summarize_pnl
from intraday_agent.learning.journal import TradeJournal, TradeRecord
from intraday_agent.market_regime import MarketRegime
from intraday_agent.strategy import BaseStrategy, get_strategy

logger = logging.getLogger(__name__)

SOURCE_IS = "walkforward_is"
SOURCE_OOS = "walkforward_oos"


def unique_trading_dates(df: pd.DataFrame) -> list[date]:
    return sorted(pd.to_datetime(df["datetime"]).dt.date.unique())


def prepare_window(
    df: pd.DataFrame,
    day_start_idx: int,
    day_end_idx: int,
    warmup_days: int = 5,
) -> tuple[pd.DataFrame, date, date]:
    """Slice candles with warmup bars before the entry window."""
    dates = unique_trading_dates(df)
    if day_end_idx > len(dates):
        raise ValueError(
            f"Window end index {day_end_idx} exceeds available trading days ({len(dates)})",
        )
    if day_start_idx >= day_end_idx:
        raise ValueError("Window start must be before window end")

    warm_idx = max(0, day_start_idx - warmup_days)
    selected = set(dates[warm_idx:day_end_idx])
    out = df[pd.to_datetime(df["datetime"]).dt.date.isin(selected)].copy()
    return out.reset_index(drop=True), dates[day_start_idx], dates[day_end_idx - 1]


def _summarize_trades(trades: list[TradeRecord]) -> dict[str, Any]:
    if not trades:
        empty = summarize_pnl([])
        empty["win_rate_pct"] = 0.0
        return empty
    rows = [asdict(t) for t in trades]
    stats = summarize_pnl(rows)
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    stats["win_rate_pct"] = round(100 * wins / len(trades), 1)
    return stats


def run_walk_forward(
    symbol_dfs: dict[str, pd.DataFrame],
    train_days: int,
    test_days: int,
    strategy: BaseStrategy | None = None,
    journal: TradeJournal | None = None,
    warmup_days: int = 5,
    clear_existing: bool = True,
    regime: MarketRegime | None = None,
) -> dict[str, Any]:
    """Run the same strategy on IS then OOS calendar splits (no param tuning)."""
    strategy = strategy or get_strategy()
    journal = journal or TradeJournal()

    if clear_existing:
        for src in (SOURCE_IS, SOURCE_OOS):
            removed = journal.clear_source(src)
            if removed:
                logger.info("Cleared %d prior %s rows", removed, src)

    sample = next(iter(symbol_dfs.values()))
    dates = unique_trading_dates(sample)
    needed = train_days + test_days
    available = len(dates)
    if available < needed:
        orig_train, orig_test = train_days, test_days
        train_days = max(1, int(available * orig_train / needed))
        test_days = available - train_days
        logger.warning(
            "Only %d trading days available (wanted %d); using %d IS + %d OOS",
            available,
            needed,
            train_days,
            test_days,
        )

    is_end = train_days
    oos_end = train_days + test_days
    is_range = (dates[0], dates[is_end - 1])
    oos_range = (dates[is_end], dates[oos_end - 1])

    is_trades: list[TradeRecord] = []
    oos_trades: list[TradeRecord] = []

    for symbol, df in symbol_dfs.items():
        if df is None or df.empty:
            logger.warning("No candles for %s — skipping", symbol)
            continue

        window_df, entry_from, entry_to = prepare_window(df, 0, is_end, warmup_days)
        trades = simulate_symbol(
            symbol,
            window_df,
            strategy,
            journal=None,
            entry_from=entry_from,
            entry_to=entry_to,
            source=SOURCE_IS,
            regime=regime,
        )
        is_trades.extend(trades)
        for t in trades:
            journal.record_trade(t)
        logger.info("%s IS: %d trades (%s → %s)", symbol, len(trades), entry_from, entry_to)

        window_df, entry_from, entry_to = prepare_window(df, is_end, oos_end, warmup_days)
        trades = simulate_symbol(
            symbol,
            window_df,
            strategy,
            journal=None,
            entry_from=entry_from,
            entry_to=entry_to,
            source=SOURCE_OOS,
            regime=regime,
        )
        oos_trades.extend(trades)
        for t in trades:
            journal.record_trade(t)
        logger.info("%s OOS: %d trades (%s → %s)", symbol, len(trades), entry_from, entry_to)

    is_stats = _summarize_trades(is_trades)
    oos_stats = _summarize_trades(oos_trades)
    oos_degradation = None
    if is_stats["net_pnl_rs"]:
        oos_degradation = round(
            (oos_stats["net_pnl_rs"] - is_stats["net_pnl_rs"]) / abs(is_stats["net_pnl_rs"]) * 100,
            1,
        )

    return {
        "train_days": train_days,
        "test_days": test_days,
        "warmup_days": warmup_days,
        "is_range": is_range,
        "oos_range": oos_range,
        "is": is_stats,
        "oos": oos_stats,
        "oos_net_vs_is_pct": oos_degradation,
        "journal_path": journal.db_path,
        "verdict": _verdict(is_stats, oos_stats),
        "regime_filter": _regime_label(),
    }


def _regime_label() -> str:
    if not Config.REGIME_FILTER_ENABLED:
        return "off"
    parts = []
    if Config.VIX_MAX > 0:
        parts.append(f"VIX≤{Config.VIX_MAX:g}")
    if Config.NIFTY_REGIME_ENABLED:
        parts.append(f"NIFTY<{Config.NIFTY_EMA_PERIOD}EMA")
    return ", ".join(parts) if parts else "on"


def _verdict(is_stats: dict[str, Any], oos_stats: dict[str, Any]) -> str:
    is_net = is_stats["net_pnl_rs"]
    oos_net = oos_stats["net_pnl_rs"]
    if is_net <= 0 and oos_net <= 0:
        return "fail — negative net on both IS and OOS"
    if is_net > 0 and oos_net > 0:
        return "pass — positive net on both IS and OOS"
    if is_net > 0 and oos_net <= 0:
        return "overfit risk — IS profitable but OOS net negative"
    return "mixed — OOS profitable but IS net negative (unusual; check sample size)"


def format_report(result: dict[str, Any]) -> str:
    is_r = result["is_range"]
    oos_r = result["oos_range"]
    is_s = result["is"]
    oos_s = result["oos"]
    lines = [
        "",
        "=== Walk-forward validation ===",
        f"Config: {result['train_days']}d in-sample + {result['test_days']}d out-of-sample "
        f"(warmup {result['warmup_days']}d, same .env params — no tuning)",
    ]
    if result.get("regime_filter") and result["regime_filter"] != "off":
        lines.append(f"Regime filter: {result['regime_filter']}")
    lines.append("")
    lines.extend([
        f"In-sample  ({is_r[0]} → {is_r[1]}):",
        f"  Trades: {is_s['trades']}  |  Win rate: {is_s.get('win_rate_pct', 0)}%",
        f"  Gross: ₹{is_s['gross_pnl_rs']:,.0f}  |  Costs: ₹{is_s['total_costs_rs']:,.0f}",
        f"  Net:   ₹{is_s['net_pnl_rs']:,.0f}  |  Avg net/trade: ₹{is_s['avg_net_per_trade_rs']:,.1f}",
        "",
        f"Out-of-sample ({oos_r[0]} → {oos_r[1]}):",
        f"  Trades: {oos_s['trades']}  |  Win rate: {oos_s.get('win_rate_pct', 0)}%",
        f"  Gross: ₹{oos_s['gross_pnl_rs']:,.0f}  |  Costs: ₹{oos_s['total_costs_rs']:,.0f}",
        f"  Net:   ₹{oos_s['net_pnl_rs']:,.0f}  |  Avg net/trade: ₹{oos_s['avg_net_per_trade_rs']:,.1f}",
        "",
        f"Verdict: {result['verdict']}",
        f"Journal: {result['journal_path']} (sources: {SOURCE_IS}, {SOURCE_OOS})",
        "",
    ])
    return "\n".join(lines)
