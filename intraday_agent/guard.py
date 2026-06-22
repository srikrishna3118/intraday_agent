"""Anti-overtrading guards: daily trade caps, per-symbol limits,
cooldowns, and daily loss/profit halts.

All limits are opt-in via ``Config`` (a value of ``0`` disables that guard).
Guards only *block* new entries (and, for the daily loss limit, square off
open positions). They never relax existing risk rules.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytz

from intraday_agent.config import Config

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class TradeGuard:
    """Tracks per-day trading activity and enforces overtrading limits.

    Counters reset automatically at the IST day rollover.
    """

    def __init__(self) -> None:
        self._date = None
        self.entries_today = 0
        self.entries_per_symbol: dict[str, int] = {}
        self.realized_pnl = 0.0
        self.last_close: dict[str, tuple[datetime, bool]] = {}
        self.halted = False
        self.force_flat = False
        self.halt_reason = ""

    def _now(self) -> datetime:
        return datetime.now(IST)

    def _roll_day(self) -> None:
        today = self._now().date()
        if self._date != today:
            self._date = today
            self.entries_today = 0
            self.entries_per_symbol = {}
            self.realized_pnl = 0.0
            self.last_close = {}
            self.halted = False
            self.force_flat = False
            self.halt_reason = ""

    def record_entry(self, symbol: str) -> None:
        self._roll_day()
        symbol = symbol.upper()
        self.entries_today += 1
        self.entries_per_symbol[symbol] = self.entries_per_symbol.get(symbol, 0) + 1

    def record_close(self, symbol: str, pnl_amount: float) -> None:
        self._roll_day()
        symbol = symbol.upper()
        self.realized_pnl += pnl_amount
        self.last_close[symbol] = (self._now(), pnl_amount < 0)
        self._check_daily_limits()

    def _check_daily_limits(self) -> None:
        if self.halted:
            return
        if Config.MAX_DAILY_LOSS > 0 and self.realized_pnl <= -Config.MAX_DAILY_LOSS:
            self.halted = True
            self.force_flat = True
            self.halt_reason = f"daily loss limit hit (realized Rs {self.realized_pnl:.0f})"
            logger.warning("Overtrading guard: %s — halting for the day", self.halt_reason)
        elif Config.MAX_DAILY_PROFIT > 0 and self.realized_pnl >= Config.MAX_DAILY_PROFIT:
            self.halted = True
            self.halt_reason = f"daily profit target reached (realized Rs {self.realized_pnl:.0f})"
            logger.info("Overtrading guard: %s — no new entries today", self.halt_reason)

    def can_trade_more(self) -> bool:
        """Global gate — are any new entries allowed this cycle?"""
        self._roll_day()
        self._check_daily_limits()
        if self.halted:
            return False
        if Config.MAX_TRADES_PER_DAY > 0 and self.entries_today >= Config.MAX_TRADES_PER_DAY:
            logger.info(
                "Overtrading guard: daily trade cap reached (%d)", Config.MAX_TRADES_PER_DAY
            )
            return False
        return True

    def remaining_daily_slots(self) -> int | None:
        """Entries left today, or ``None`` if uncapped."""
        if Config.MAX_TRADES_PER_DAY <= 0:
            return None
        return max(0, Config.MAX_TRADES_PER_DAY - self.entries_today)

    def can_enter(self, symbol: str) -> bool:
        """Per-symbol gate: respects per-symbol cap and cooldowns."""
        self._roll_day()
        symbol = symbol.upper()

        if (
            Config.MAX_TRADES_PER_SYMBOL > 0
            and self.entries_per_symbol.get(symbol, 0) >= Config.MAX_TRADES_PER_SYMBOL
        ):
            return False

        last = self.last_close.get(symbol)
        if last:
            closed_at, was_loss = last
            cooldown = Config.SYMBOL_COOLDOWN_MIN
            if was_loss and Config.LOSS_COOLDOWN_MIN > 0:
                cooldown = max(cooldown, Config.LOSS_COOLDOWN_MIN)
            if cooldown > 0 and self._now() - closed_at < timedelta(minutes=cooldown):
                return False

        return True

    def should_force_flat(self) -> bool:
        """True when the daily loss limit requires squaring off open positions."""
        self._roll_day()
        self._check_daily_limits()
        return self.force_flat

    def status(self) -> str:
        parts = [f"entries={self.entries_today}", f"realized=Rs {self.realized_pnl:.0f}"]
        if Config.MAX_TRADES_PER_DAY > 0:
            parts.append(f"cap={Config.MAX_TRADES_PER_DAY}")
        if self.halted:
            parts.append(f"HALTED ({self.halt_reason})")
        return " | ".join(parts)
