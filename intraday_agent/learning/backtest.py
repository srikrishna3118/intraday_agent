"""Walk-forward backtest to seed the trade journal."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, time as dtime
from typing import Any

import pandas as pd

from intraday_agent.config import Config
from intraday_agent.learning.entry_features import build_entry_features, features_to_json
from intraday_agent.learning.journal import TradeJournal, TradeRecord
from intraday_agent.market_regime import MarketRegime
from intraday_agent.learning.meta_label import MetaLabelFilter
from intraday_agent.strategy import BaseStrategy, get_strategy, list_strategies, Signal, entry_time_allowed
from intraday_agent.universe import to_ist

logger = logging.getLogger(__name__)


def _parse_square_off() -> dtime:
    hh, mm = Config.SQUARE_OFF_TIME.split(":")
    return dtime(int(hh), int(mm))


def _bar_time(dt: datetime) -> dtime:
    """Bar clock time in IST (Angel cache candles are naive UTC)."""
    return to_ist(dt).time()


def _compute_quantity(price: float) -> int:
    if price <= 0:
        return 0
    qty = math.floor(Config.CAPITAL_PER_TRADE / price)
    return max(1, min(qty, Config.MAX_QUANTITY))


def _pnl_pct(side: str, entry: float, price: float) -> float:
    if side == "LONG":
        return (price - entry) / entry * 100
    return (entry - price) / entry * 100


def _pnl_amount(side: str, entry: float, price: float, qty: int) -> float:
    diff = price - entry
    if side == "SHORT":
        diff = -diff
    return diff * qty


def _bar_date(bar_dt: datetime) -> date:
    """Session calendar date in IST."""
    return to_ist(bar_dt).date()


def _session_rolled(entry_time: datetime, bar_dt: datetime) -> bool:
    return _bar_date(entry_time) != _bar_date(bar_dt)


def _eod_square_off_due(bar_dt: datetime, square_off: dtime) -> bool:
    return _bar_time(bar_dt) >= square_off


def _precompute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Precompute indicator columns once for faster bar-by-bar simulation."""
    from intraday_agent.strategy import (
        compute_adx,
        compute_atr,
        compute_rsi,
        compute_session_pivot_points,
        compute_session_vwap,
        precompute_rsi_div_signals,
    )

    out = df.copy()
    out["rsi"] = compute_rsi(out["close"])
    out["rsi_div"] = compute_rsi(out["close"], Config.RSI_DIV_PERIOD)
    out["rsi2"] = compute_rsi(out["close"], Config.RSI_FAST_PERIOD)
    out["atr"] = compute_atr(out)
    out["vwap"] = compute_session_vwap(out)
    out["vol_ma"] = out["volume"].rolling(Config.VOLUME_MA_LEN).mean()
    out["adx"] = compute_adx(out)
    out = compute_session_pivot_points(out)
    out = precompute_rsi_div_signals(out)
    return out


def simulate_symbol(
    symbol: str,
    df: pd.DataFrame,
    strategy: BaseStrategy | None = None,
    journal: TradeJournal | None = None,
    entry_from: date | None = None,
    entry_to: date | None = None,
    source: str = "backtest",
    regime: MarketRegime | None = None,
    meta_filter: MetaLabelFilter | None = None,
) -> list[TradeRecord]:
    """Walk bar-by-bar; one position at a time per symbol."""
    strategy = strategy or get_strategy()
    journal = journal or TradeJournal()
    min_bars = strategy.min_bars()
    if df is None or len(df) < min_bars + 1:
        return []

    df = _precompute_indicators(df)
    df = strategy.precompute_df(df)
    square_off = _parse_square_off()
    trades: list[TradeRecord] = []
    position: dict[str, Any] | None = None

    for i in range(min_bars, len(df)):
        slice_df = df.iloc[: i + 1]
        bar = df.iloc[i]
        bar_dt = bar["datetime"]
        close = float(bar["close"])

        if position:
            side = position["side"]
            entry = position["entry_price"]
            high = float(bar["high"])
            low = float(bar["low"])
            extreme = position.get("trail_extreme", entry)
            extreme = strategy.update_trail_extreme(
                side, extreme, high, low,
                close=close,
                atr=strategy.current_atr(slice_df),
            )
            position["trail_extreme"] = extreme

            pnl_pct = _pnl_pct(side, entry, close)
            reason = strategy.exit_reason(
                slice_df,
                side,
                entry,
                close,
                position.get("entry_atr"),
                trail_extreme=extreme,
            )
            if reason is None and i == len(df) - 1:
                reason = "window end square-off"
            if reason is None and position and _session_rolled(position["entry_time"], bar_dt):
                reason = "EOD square-off"
            if reason is None and _eod_square_off_due(bar_dt, square_off):
                reason = "EOD square-off"

            if reason:
                qty = position["quantity"]
                record = TradeRecord(
                    symbol=symbol.upper(),
                    side=side,
                    entry_rsi=position["entry_rsi"],
                    volume_ratio=position["volume_ratio"],
                    entry_price=entry,
                    exit_price=close,
                    quantity=qty,
                    entry_time=position["entry_time"],
                    exit_time=bar_dt.to_pydatetime() if hasattr(bar_dt, "to_pydatetime") else bar_dt,
                    exit_reason=reason,
                    pnl_pct=pnl_pct,
                    pnl_amount=_pnl_amount(side, entry, close, qty),
                    source=source,
                    entry_features=position.get("entry_features"),
                )
                if journal is not None:
                    journal.record_trade(record)
                trades.append(record)
                position = None
                continue

        if position is not None:
            continue

        bar_time = bar_dt.to_pydatetime() if hasattr(bar_dt, "to_pydatetime") else bar_dt
        bar_date = _bar_date(bar_dt)
        if entry_from and bar_date < entry_from:
            continue
        if entry_to and bar_date > entry_to:
            continue
        if not entry_time_allowed(bar_time):
            continue

        result = strategy.analyze(slice_df, symbol)
        if not result or result.signal == Signal.NONE:
            continue

        side = "LONG" if result.signal == Signal.BUY else "SHORT"
        if regime is not None:
            block = regime.block_reason(side, bar_time)
            if block:
                continue
        if side == "LONG" and not Config.ALLOW_LONG:
            continue
        if side == "SHORT" and not Config.ALLOW_SHORT:
            continue

        if meta_filter is not None and meta_filter.enabled:
            take, prob = meta_filter.should_take(
                side, result, strategy, slice_df, regime, bar_time,
            )
            if not take:
                continue

        vol_ratio = result.volume / result.volume_ma if result.volume_ma > 0 else None
        feats = build_entry_features(side, result, strategy, slice_df, regime, bar_time)
        position = {
            "side": side,
            "entry_price": close,
            "entry_time": bar_dt.to_pydatetime() if hasattr(bar_dt, "to_pydatetime") else bar_dt,
            "entry_rsi": result.rsi,
            "volume_ratio": vol_ratio,
            "quantity": _compute_quantity(close),
            "entry_atr": result.atr,
            "trail_extreme": close,
            "entry_features": features_to_json(feats),
        }

    return trades


def run_backtest(
    broker,
    symbols: list[str],
    days: int = 60,
    journal: TradeJournal | None = None,
    clear_existing: bool = True,
) -> dict[str, Any]:
    """Fetch history and simulate each symbol."""
    strategy = get_strategy()
    journal = journal or TradeJournal()

    if clear_existing:
        removed = journal.clear_source("backtest")
        if removed:
            logger.info("Cleared %d prior backtest journal rows", removed)

    lookback = max(Config.CANDLE_LOOKBACK, days * 26)
    total_trades = 0
    per_symbol: dict[str, int] = {}

    for symbol in symbols:
        df = broker.get_candles_for_symbol(symbol, lookback=lookback)
        if df is None or df.empty:
            logger.warning("No candles for %s — skipping", symbol)
            per_symbol[symbol] = 0
            continue

        trades = simulate_symbol(symbol, df, strategy, journal)
        per_symbol[symbol] = len(trades)
        total_trades += len(trades)
        logger.info("%s: %d simulated trades", symbol, len(trades))

    return {
        "symbols": len(symbols),
        "total_trades": total_trades,
        "per_symbol": per_symbol,
        "journal_path": journal.db_path,
        "journal_count": journal.trade_count(),
    }
