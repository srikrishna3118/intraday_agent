"""Order execution (paper/live) and position tracking."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeJournal, TradeRecord
from intraday_agent.logging_setup import log_trade
from intraday_agent.universe import is_symbol_excluded

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    side: str  # LONG or SHORT
    quantity: int
    entry_price: float
    entry_time: datetime = field(default_factory=datetime.now)
    entry_rsi: float | None = None
    volume_ratio: float | None = None
    entry_atr: float | None = None
    trail_extreme: float | None = None
    entry_features: str | None = None
    order_id: str | None = None
    paper: bool = True

    def pnl_pct(self, current_price: float) -> float:
        if self.side == "LONG":
            return (current_price - self.entry_price) / self.entry_price * 100
        return (self.entry_price - current_price) / self.entry_price * 100

    def pnl_amount(self, current_price: float) -> float:
        diff = current_price - self.entry_price
        if self.side == "SHORT":
            diff = -diff
        return diff * self.quantity


class OrderManager:
    def __init__(self, broker: AngelBroker, journal: TradeJournal | None = None):
        self.broker = broker
        self.positions: dict[str, Position] = {}
        self.journal = journal or TradeJournal()

    def position_count(self) -> int:
        return len(self.positions)

    def has_position(self, symbol: str) -> bool:
        return symbol.upper() in self.positions

    def compute_quantity(self, price: float) -> int:
        if price <= 0:
            return 0
        qty = math.floor(Config.CAPITAL_PER_TRADE / price)
        return max(1, min(qty, Config.MAX_QUANTITY))

    def open_position(
        self,
        symbol: str,
        side: str,
        price: float | None = None,
        entry_rsi: float | None = None,
        volume_ratio: float | None = None,
        entry_atr: float | None = None,
        entry_features: str | None = None,
    ) -> dict[str, Any]:
        symbol = symbol.upper()
        if is_symbol_excluded(symbol):
            return {"success": False, "message": f"Symbol excluded: {symbol}"}
        if self.has_position(symbol):
            return {"success": False, "message": f"Already in position: {symbol}"}

        if side == "LONG" and not Config.ALLOW_LONG:
            return {"success": False, "message": "Long entries disabled"}

        if side == "SHORT" and not Config.ALLOW_SHORT:
            return {"success": False, "message": "Short selling disabled"}

        ltp = price or self.broker.get_ltp_for_symbol(symbol)
        if not ltp:
            return {"success": False, "message": f"Could not get LTP for {symbol}"}

        quantity = self.compute_quantity(ltp)
        action = "BUY" if side == "LONG" else "SELL"

        if Config.LIVE_TRADING:
            result = self.broker.place_order(symbol, action, quantity)
            if not result.get("success"):
                return result
            order_id = result.get("order_id")
        else:
            result = {
                "success": True,
                "order_id": f"PAPER-{symbol}-{datetime.now():%H%M%S}",
                "message": "Paper trade",
            }
            order_id = result["order_id"]
            logger.info(
                "PAPER %s %s x%d @ %.2f",
                action,
                symbol,
                quantity,
                ltp,
            )

        self.positions[symbol] = Position(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=ltp,
            entry_rsi=entry_rsi,
            volume_ratio=volume_ratio,
            entry_atr=entry_atr,
            entry_features=entry_features,
            trail_extreme=ltp,
            order_id=order_id,
            paper=not Config.LIVE_TRADING,
        )
        log_trade(action, symbol, quantity, ltp, result)
        return result

    def close_position(
        self,
        symbol: str,
        price: float | None = None,
        exit_reason: str = "manual",
    ) -> dict[str, Any]:
        symbol = symbol.upper()
        pos = self.positions.get(symbol)
        if not pos:
            return {"success": False, "message": f"No position for {symbol}"}

        ltp = price or self.broker.get_ltp_for_symbol(symbol)
        if not ltp:
            return {"success": False, "message": f"Could not get LTP for {symbol}"}

        action = "SELL" if pos.side == "LONG" else "BUY"
        pnl = pos.pnl_amount(ltp)

        if Config.LIVE_TRADING:
            result = self.broker.place_order(symbol, action, pos.quantity)
        else:
            result = {
                "success": True,
                "order_id": f"PAPER-CLOSE-{symbol}",
                "message": "Paper close",
            }
            logger.info(
                "PAPER CLOSE %s %s x%d @ %.2f | PnL Rs %.2f (%.2f%%)",
                action,
                symbol,
                pos.quantity,
                ltp,
                pnl,
                pos.pnl_pct(ltp),
            )

        if result.get("success"):
            pnl_pct = pos.pnl_pct(ltp)
            source = "live" if Config.LIVE_TRADING else "paper"
            try:
                trade_id = self.journal.record_trade(
                    TradeRecord(
                        symbol=symbol,
                        side=pos.side,
                        entry_rsi=pos.entry_rsi,
                        volume_ratio=pos.volume_ratio,
                        entry_price=pos.entry_price,
                        exit_price=ltp,
                        quantity=pos.quantity,
                        entry_time=pos.entry_time,
                        exit_time=datetime.now(),
                        exit_reason=exit_reason,
                        pnl_pct=pnl_pct,
                        pnl_amount=pnl,
                        source=source,
                        entry_features=pos.entry_features,
                    )
                )
                logger.info("Journal recorded trade #%d %s %s", trade_id, symbol, exit_reason)
            except Exception as exc:
                logger.warning("Failed to record trade in journal: %s", exc)

            del self.positions[symbol]
            result["symbol"] = symbol
            result["pnl"] = pnl
            result["pnl_pct"] = pnl_pct
            log_trade(action, symbol, pos.quantity, ltp, result)

        return result

    def close_all(self, exit_reason: str = "square-off") -> list[dict[str, Any]]:
        results = []
        for symbol in list(self.positions.keys()):
            results.append(self.close_position(symbol, exit_reason=exit_reason))
        return results

    def get_open_positions(self) -> list[Position]:
        return list(self.positions.values())
