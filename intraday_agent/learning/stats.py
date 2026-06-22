"""Rolling symbol statistics from trade journal."""

from __future__ import annotations

from dataclasses import dataclass

from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeJournal


@dataclass
class SymbolStats:
    symbol: str
    trade_count: int
    win_rate: float
    avg_pnl_pct: float


class StatsEngine:
    def __init__(self, journal: TradeJournal | None = None):
        self.journal = journal or TradeJournal()

    def _rows_for_symbol(self, symbol: str) -> list[dict]:
        return self.journal.fetch_trades(
            symbol=symbol.upper(),
            lookback_days=Config.LEARNING_LOOKBACK_DAYS,
        )

    def get_symbol_stats(self, symbol: str) -> SymbolStats:
        rows = self._rows_for_symbol(symbol)
        if not rows:
            global_wr = self.get_global_win_rate()
            return SymbolStats(symbol.upper(), 0, global_wr, 0.0)

        wins = sum(1 for r in rows if r["pnl_pct"] > 0)
        count = len(rows)
        win_rate = wins / count if count else 0.5
        avg_pnl = sum(r["pnl_pct"] for r in rows) / count
        return SymbolStats(symbol.upper(), count, win_rate, avg_pnl)

    def get_global_win_rate(self) -> float:
        rows = self.journal.fetch_trades(lookback_days=Config.LEARNING_LOOKBACK_DAYS)
        if not rows:
            return 0.5
        wins = sum(1 for r in rows if r["pnl_pct"] > 0)
        return wins / len(rows)

    def should_skip(self, symbol: str) -> bool:
        stats = self.get_symbol_stats(symbol)
        if stats.trade_count < Config.LEARNING_MIN_TRADES:
            return False
        return stats.win_rate < Config.LEARNING_SKIP_WIN_RATE
