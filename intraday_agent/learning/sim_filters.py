"""Optional entry filters for portfolio backtests (research only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from intraday_agent.strategy import ScreenResult, Signal
from intraday_agent.universe import to_ist


def bar_hour_ist(bar_dt: datetime | Any) -> int | None:
    if bar_dt is None:
        return None
    return to_ist(bar_dt).hour


@dataclass(frozen=True)
class SimEntryFilter:
    """Gate entries before ranker picks (research ablations)."""

    max_entry_hour: int | None = None  # allow hour < max (e.g. 14 → 09–13)
    min_rsi: float | None = None  # short: RSI must be > min_rsi
    max_volume_ratio: float | None = None  # volume/MA must be < max
    exclude_symbols: frozenset[str] = field(default_factory=frozenset)

    def allows(self, result: ScreenResult, bar_dt: datetime | Any) -> bool:
        sym = result.symbol.upper()
        if sym in self.exclude_symbols:
            return False
        hour = bar_hour_ist(bar_dt)
        if self.max_entry_hour is not None and hour is not None and hour >= self.max_entry_hour:
            return False
        if result.signal == Signal.SELL and self.min_rsi is not None:
            if result.rsi is None or result.rsi <= self.min_rsi:
                return False
        vol_ratio = None
        if result.volume_ma and result.volume_ma > 0:
            vol_ratio = result.volume / result.volume_ma
        if self.max_volume_ratio is not None and vol_ratio is not None:
            if vol_ratio >= self.max_volume_ratio:
                return False
        return True
