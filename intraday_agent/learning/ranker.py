"""Adaptive ranking of screener candidates using journal stats."""

from __future__ import annotations

import logging

from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeJournal
from intraday_agent.learning.stats import StatsEngine
from intraday_agent.strategy import ScreenResult

logger = logging.getLogger(__name__)


class AdaptiveRanker:
    def __init__(
        self,
        journal: TradeJournal | None = None,
        stats: StatsEngine | None = None,
    ):
        self.journal = journal or TradeJournal()
        self.stats = stats or StatsEngine(self.journal)

    def _legacy_rank(
        self,
        oversold: list[ScreenResult],
        overbought: list[ScreenResult],
        slots: int,
        has_position,
    ) -> list[tuple[str, ScreenResult]]:
        candidates: list[tuple[str, ScreenResult]] = []
        if Config.ALLOW_LONG:
            for r in sorted(oversold, key=lambda x: x.rsi):
                if not has_position(r.symbol):
                    candidates.append(("LONG", r))
        if Config.ALLOW_SHORT:
            for r in sorted(overbought, key=lambda x: x.rsi, reverse=True):
                if not has_position(r.symbol):
                    candidates.append(("SHORT", r))
        return candidates[:slots]

    def _rsi_extremity(self, side: str, result: ScreenResult) -> float:
        if side == "LONG":
            return Config.RSI_OVERSOLD - result.rsi
        return result.rsi - Config.RSI_OVERBOUGHT

    def score(self, side: str, result: ScreenResult) -> float:
        extremity = self._rsi_extremity(side, result)
        sym_stats = self.stats.get_symbol_stats(result.symbol)
        win_rate = sym_stats.win_rate if sym_stats.trade_count else self.stats.get_global_win_rate()
        learned = Config.LEARNING_SYMBOL_WEIGHT * (win_rate - 0.5)
        return extremity + learned

    def rank(
        self,
        oversold: list[ScreenResult],
        overbought: list[ScreenResult],
        slots: int,
        has_position,
    ) -> list[tuple[str, ScreenResult]]:
        if not Config.LEARNING_ENABLED or self.journal.trade_count() == 0:
            return self._legacy_rank(oversold, overbought, slots, has_position)

        scored: list[tuple[float, str, ScreenResult]] = []

        for r in oversold:
            if has_position(r.symbol):
                continue
            if not Config.ALLOW_LONG:
                continue
            if self.stats.should_skip(r.symbol):
                logger.debug("Learning skip %s (low win rate)", r.symbol)
                continue
            scored.append((self.score("LONG", r), "LONG", r))

        if Config.ALLOW_SHORT:
            for r in overbought:
                if has_position(r.symbol):
                    continue
                if self.stats.should_skip(r.symbol):
                    logger.debug("Learning skip %s (low win rate)", r.symbol)
                    continue
                scored.append((self.score("SHORT", r), "SHORT", r))

        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [(side, r) for _, side, r in scored[:slots]]

        if picked:
            logger.info(
                "Adaptive rank picked: %s",
                [(s, r.symbol, round(self.score(s, r), 2)) for s, r in picked],
            )
        return picked
