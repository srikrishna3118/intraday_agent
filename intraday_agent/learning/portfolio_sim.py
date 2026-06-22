"""Portfolio-level backtest with MAX_POSITIONS, TradeGuard, and ranker."""

from __future__ import annotations

import logging
from datetime import date, datetime, time as dtime
from typing import Any

import pandas as pd
import pytz

from intraday_agent.config import Config
from intraday_agent.guard import TradeGuard
from intraday_agent.learning.backtest import (
    _bar_date,
    _compute_quantity,
    _eod_square_off_due,
    _parse_square_off,
    _pnl_amount,
    _pnl_pct,
    _precompute_indicators,
    _session_rolled,
)
from intraday_agent.learning.entry_features import build_entry_features, features_to_json
from intraday_agent.learning.journal import TradeJournal, TradeRecord
from intraday_agent.learning.meta_label import MetaLabelFilter
from intraday_agent.learning.sim_filters import SimEntryFilter
from intraday_agent.universe import is_symbol_excluded
from intraday_agent.learning.ranker import AdaptiveRanker
from intraday_agent.market_regime import MarketRegime
from intraday_agent.strategy import BaseStrategy, ScreenResult, Signal, entry_time_allowed, get_strategy

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class SimulatedTradeGuard(TradeGuard):
    """TradeGuard driven by simulated bar timestamps instead of wall clock."""

    def __init__(self) -> None:
        super().__init__()
        self._sim_now: datetime | None = None

    def set_sim_time(self, dt: datetime) -> None:
        if hasattr(dt, "to_pydatetime"):
            dt = dt.to_pydatetime()
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        else:
            dt = dt.astimezone(IST)
        self._sim_now = dt

    def _now(self) -> datetime:
        if self._sim_now is not None:
            return self._sim_now
        return super()._now()


def _to_datetime(bar_dt) -> datetime:
    if hasattr(bar_dt, "to_pydatetime"):
        return bar_dt.to_pydatetime()
    return bar_dt


def _build_timeline(symbol_dfs: dict[str, pd.DataFrame], min_bars: int) -> list[tuple[datetime, str, int]]:
    events: list[tuple[datetime, str, int]] = []
    for symbol, df in symbol_dfs.items():
        if df is None or len(df) < min_bars + 1:
            continue
        for i in range(min_bars, len(df)):
            bar_dt = _to_datetime(df.iloc[i]["datetime"])
            events.append((bar_dt, symbol.upper(), i))
    events.sort(key=lambda x: (x[0], x[1]))
    return events


def _close_position(
    symbol: str,
    position: dict[str, Any],
    bar_dt: datetime,
    close: float,
    reason: str,
    source: str,
) -> TradeRecord:
    side = position["side"]
    entry = position["entry_price"]
    qty = position["quantity"]
    return TradeRecord(
        symbol=symbol,
        side=side,
        entry_rsi=position.get("entry_rsi"),
        volume_ratio=position.get("volume_ratio"),
        entry_price=entry,
        exit_price=close,
        quantity=qty,
        entry_time=position["entry_time"],
        exit_time=bar_dt,
        exit_reason=reason,
        pnl_pct=_pnl_pct(side, entry, close),
        pnl_amount=_pnl_amount(side, entry, close, qty),
        source=source,
        entry_features=position.get("entry_features"),
    )


def simulate_portfolio(
    symbol_dfs: dict[str, pd.DataFrame],
    strategy: BaseStrategy | None = None,
    journal: TradeJournal | None = None,
    entry_from: date | None = None,
    entry_to: date | None = None,
    source: str = "portfolio_sim",
    regime: MarketRegime | None = None,
    meta_filter: MetaLabelFilter | None = None,
    entry_filter: SimEntryFilter | None = None,
) -> list[TradeRecord]:
    """Walk a merged timeline; enforce portfolio caps and guards."""
    strategy = strategy or get_strategy()
    journal = journal or TradeJournal()
    min_bars = strategy.min_bars()
    symbol_dfs = {
        sym: strategy.precompute_df(_precompute_indicators(df.copy()))
        for sym, df in symbol_dfs.items()
        if df is not None and not df.empty
    }
    square_off = _parse_square_off()
    guard = SimulatedTradeGuard()
    ranker = AdaptiveRanker(journal=TradeJournal())  # empty journal → legacy RSI rank

    open_positions: dict[str, dict[str, Any]] = {}
    trades: list[TradeRecord] = []
    timeline = _build_timeline(symbol_dfs, min_bars)
    if not timeline:
        return trades

    idx = 0
    while idx < len(timeline):
        bar_dt, _, _ = timeline[idx]
        batch_end = idx
        while batch_end < len(timeline) and timeline[batch_end][0] == bar_dt:
            batch_end += 1

        guard.set_sim_time(bar_dt)

        # Exits first
        for pos_idx in range(idx, batch_end):
            _, symbol, bar_i = timeline[pos_idx]
            if symbol not in open_positions:
                continue
            df = symbol_dfs[symbol]
            slice_df = df.iloc[: bar_i + 1]
            bar = df.iloc[bar_i]
            close = float(bar["close"])
            high = float(bar["high"])
            low = float(bar["low"])
            position = open_positions[symbol]
            side = position["side"]
            entry = position["entry_price"]
            extreme = strategy.update_trail_extreme(
                side,
                position.get("trail_extreme", entry),
                high,
                low,
                close=close,
                atr=strategy.current_atr(slice_df),
            )
            position["trail_extreme"] = extreme

            reason = strategy.exit_reason(
                slice_df,
                side,
                entry,
                close,
                position.get("entry_atr"),
                trail_extreme=extreme,
            )
            if reason is None and _session_rolled(position["entry_time"], bar_dt):
                reason = "EOD square-off"
            if reason is None and _eod_square_off_due(bar_dt, square_off):
                reason = "EOD square-off"

            if reason:
                record = _close_position(symbol, position, _to_datetime(bar_dt), close, reason, source)
                trades.append(record)
                if journal is not None:
                    journal.record_trade(record)
                guard.record_close(symbol, record.pnl_amount or 0.0)
                del open_positions[symbol]

        # Entries at this timestamp
        if guard.can_trade_more() and not guard.should_force_flat():
            slots = Config.MAX_POSITIONS - len(open_positions)
            daily_left = guard.remaining_daily_slots()
            if daily_left is not None:
                slots = min(slots, daily_left)

            if slots > 0 and entry_time_allowed(_to_datetime(bar_dt)):
                bar_date = _bar_date(bar_dt)
                if (not entry_from or bar_date >= entry_from) and (not entry_to or bar_date <= entry_to):
                    oversold: list[ScreenResult] = []
                    overbought: list[ScreenResult] = []

                    for pos_idx in range(idx, batch_end):
                        _, symbol, bar_i = timeline[pos_idx]
                        if symbol in open_positions:
                            continue
                        if not guard.can_enter(symbol):
                            continue
                        if is_symbol_excluded(symbol):
                            continue
                        if entry_filter is not None and symbol.upper() in entry_filter.exclude_symbols:
                            continue

                        df = symbol_dfs[symbol]
                        slice_df = df.iloc[: bar_i + 1]
                        result = strategy.analyze(slice_df, symbol)
                        if not result or result.signal == Signal.NONE:
                            continue
                        if entry_filter is not None and not entry_filter.allows(result, bar_dt):
                            continue
                        if result.signal == Signal.BUY:
                            if Config.ALLOW_LONG:
                                oversold.append(result)
                        elif result.signal == Signal.SELL:
                            if Config.ALLOW_SHORT:
                                overbought.append(result)

                    def blocked(sym: str) -> bool:
                        return sym in open_positions or not guard.can_enter(sym)

                    bar_index_at_ts = {s: i for _, s, i in timeline[idx:batch_end]}
                    picks = ranker.rank(oversold, overbought, slots, blocked)
                    for side, result in picks:
                        if regime is not None:
                            block = regime.block_reason(side, _to_datetime(bar_dt))
                            if block:
                                continue
                        if side == "LONG" and not Config.ALLOW_LONG:
                            continue
                        if side == "SHORT" and not Config.ALLOW_SHORT:
                            continue

                        symbol = result.symbol.upper()
                        if symbol in open_positions:
                            continue
                        bar_i = bar_index_at_ts.get(symbol)
                        if bar_i is None:
                            continue
                        df = symbol_dfs[symbol]
                        slice_df = df.iloc[: bar_i + 1]

                        if meta_filter is not None and meta_filter.enabled:
                            take, _ = meta_filter.should_take(
                                side, result, strategy, slice_df, regime, _to_datetime(bar_dt),
                            )
                            if not take:
                                continue

                        bar = df.iloc[bar_i]
                        close = float(bar["close"])
                        vol_ratio = (
                            result.volume / result.volume_ma if result.volume_ma > 0 else None
                        )
                        feats = build_entry_features(
                            side, result, strategy, slice_df, regime, _to_datetime(bar_dt),
                        )
                        open_positions[symbol] = {
                            "side": side,
                            "entry_price": close,
                            "entry_time": _to_datetime(bar_dt),
                            "entry_rsi": result.rsi,
                            "volume_ratio": vol_ratio,
                            "quantity": _compute_quantity(close),
                            "entry_atr": result.atr,
                            "trail_extreme": close,
                            "entry_features": features_to_json(feats),
                        }
                        guard.record_entry(symbol)

        idx = batch_end

    # Square off remaining at last bar for each open position
    for symbol, position in list(open_positions.items()):
        df = symbol_dfs[symbol]
        bar = df.iloc[-1]
        bar_dt = _to_datetime(bar["datetime"])
        close = float(bar["close"])
        record = _close_position(symbol, position, bar_dt, close, "window end square-off", source)
        trades.append(record)
        if journal is not None:
            journal.record_trade(record)

    return trades
