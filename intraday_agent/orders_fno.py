"""Paper-first multi-leg options position tracking for NIFTY F&O research."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Mapping

from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeJournal, TradeRecord

if TYPE_CHECKING:
    from intraday_agent.broker import AngelBroker

logger = logging.getLogger(__name__)


@dataclass
class OptionLeg:
    leg_id: str
    underlying: str
    tradingsymbol: str
    symboltoken: str
    exchange: str
    expiry: date
    strike: float
    option_type: str
    side: str
    quantity: int
    entry_price: float
    entry_time: datetime = field(default_factory=datetime.now)
    stop_price: float | None = None
    order_id: str | None = None
    paper: bool = True

    def pnl_amount(self, current_price: float) -> float:
        diff = current_price - self.entry_price
        if self.side == "SHORT":
            diff = -diff
        return diff * self.quantity

    def pnl_pct(self, current_price: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        if self.side == "LONG":
            return (current_price - self.entry_price) / self.entry_price * 100
        return (self.entry_price - current_price) / self.entry_price * 100


@dataclass
class OptionPosition:
    position_id: str
    strategy_name: str
    underlying: str
    expiry: date
    legs: dict[str, OptionLeg]
    entry_time: datetime = field(default_factory=datetime.now)
    entry_time_slot: str | None = None
    estimated_margin_required: float | None = None
    paper: bool = True

    def net_entry_cashflow(self) -> float:
        cashflow = 0.0
        for leg in self.legs.values():
            signed = leg.entry_price * leg.quantity
            cashflow += signed if leg.side == "SHORT" else -signed
        return cashflow

    def pnl_amount(self, prices: Mapping[str, float]) -> float:
        pnl = 0.0
        for leg_id, leg in self.legs.items():
            if leg_id not in prices:
                raise KeyError(f"Missing current price for leg {leg_id}")
            pnl += leg.pnl_amount(prices[leg_id])
        return pnl

    def pnl_pct(self, prices: Mapping[str, float]) -> float:
        net_entry_cashflow = self.net_entry_cashflow()
        if abs(net_entry_cashflow) <= 0:
            return 0.0
        return self.pnl_amount(prices) / abs(net_entry_cashflow) * 100.0

    def estimate_margin_required(self) -> float | None:
        """Approximate defined-risk capital for hedged short-premium structures.

        For the default iron-fly style plan, the worst-case loss is approximated as
        the larger wing width times quantity minus the net credit received.
        Returns ``None`` when the structure contains naked short premium and no
        protective wing can be identified.
        """
        short_calls = [leg for leg in self.legs.values() if leg.side == "SHORT" and leg.option_type == "CE"]
        short_puts = [leg for leg in self.legs.values() if leg.side == "SHORT" and leg.option_type == "PE"]
        long_calls = [leg for leg in self.legs.values() if leg.side == "LONG" and leg.option_type == "CE"]
        long_puts = [leg for leg in self.legs.values() if leg.side == "LONG" and leg.option_type == "PE"]

        def protected_call_width(short_leg: OptionLeg) -> float | None:
            candidates = [leg for leg in long_calls if leg.strike > short_leg.strike]
            if not candidates:
                return None
            protector = min(candidates, key=lambda leg: leg.strike)
            return (protector.strike - short_leg.strike) * short_leg.quantity

        def protected_put_width(short_leg: OptionLeg) -> float | None:
            candidates = [leg for leg in long_puts if leg.strike < short_leg.strike]
            if not candidates:
                return None
            protector = max(candidates, key=lambda leg: leg.strike)
            return (short_leg.strike - protector.strike) * short_leg.quantity

        widths: list[float] = []
        for short_leg in short_calls:
            width = protected_call_width(short_leg)
            if width is None:
                return None
            widths.append(width)
        for short_leg in short_puts:
            width = protected_put_width(short_leg)
            if width is None:
                return None
            widths.append(width)

        if not widths:
            return 0.0

        gross_defined_risk = max(widths)
        net_credit = max(0.0, self.net_entry_cashflow())
        return max(0.0, gross_defined_risk - net_credit)

    def leg_ids(self) -> list[str]:
        return list(self.legs)


class FnOOrderManager:
    """Paper-first multi-leg position manager for options strategies.

    Live order placement is intentionally deferred. This module is the state model
    and paper-execution surface needed for weekly NIFTY options research.
    """

    def __init__(self, broker: AngelBroker | None = None, journal: TradeJournal | None = None):
        self.broker = broker
        self.positions: dict[str, OptionPosition] = {}
        self.journal = journal or TradeJournal()

    def position_count(self) -> int:
        return len(self.positions)

    def get_open_positions(self) -> list[OptionPosition]:
        return list(self.positions.values())

    def get_position(self, position_id: str) -> OptionPosition | None:
        return self.positions.get(position_id)

    def estimated_margin_used(self) -> float:
        return sum(position.estimated_margin_required or 0.0 for position in self.positions.values())

    def open_position(
        self,
        *,
        strategy_name: str,
        leg_specs: list[dict[str, Any]],
        position_id: str | None = None,
        entry_time_slot: str | None = None,
    ) -> dict[str, Any]:
        if not leg_specs:
            return {"success": False, "message": "No option legs supplied"}

        if Config.LIVE_TRADING:
            return {
                "success": False,
                "message": "FnO live order placement not implemented yet; use paper mode",
            }

        built_legs: dict[str, OptionLeg] = {}
        underlying = None
        expiry = None
        now = datetime.now()

        for idx, spec in enumerate(leg_specs, start=1):
            instrument = spec.get("instrument") or {}
            side = str(spec.get("side", "")).upper().strip()
            if side not in {"LONG", "SHORT"}:
                return {"success": False, "message": f"Invalid leg side: {side!r}"}

            leg_underlying = str(instrument.get("underlying", "")).upper().strip()
            leg_expiry = instrument.get("expiry")
            if not leg_underlying or not leg_expiry:
                return {"success": False, "message": f"Invalid instrument payload: {instrument}"}

            expiry_date = date.fromisoformat(str(leg_expiry))
            if underlying is None:
                underlying = leg_underlying
            elif underlying != leg_underlying:
                return {"success": False, "message": "All legs must share the same underlying"}

            if expiry is None:
                expiry = expiry_date
            elif expiry != expiry_date:
                return {"success": False, "message": "All legs must share the same expiry"}

            quantity = int(spec.get("quantity") or instrument.get("lotsize") or 0)
            if quantity <= 0:
                return {"success": False, "message": f"Invalid leg quantity for {instrument}"}

            entry_price = spec.get("price")
            if entry_price is None:
                if self.broker is None:
                    return {
                        "success": False,
                        "message": f"No broker attached; explicit price required for {instrument.get('tradingsymbol')}",
                    }
                entry_price = self.broker.get_ltp_for_instrument(instrument)
            if entry_price is None or float(entry_price) <= 0:
                return {
                    "success": False,
                    "message": f"Could not determine entry price for {instrument.get('tradingsymbol')}",
                }

            leg_id = str(spec.get("leg_id") or f"LEG{idx}")
            built_legs[leg_id] = OptionLeg(
                leg_id=leg_id,
                underlying=leg_underlying,
                tradingsymbol=str(instrument.get("tradingsymbol", "")),
                symboltoken=str(instrument.get("symboltoken", "")),
                exchange=str(instrument.get("exchange", "")),
                expiry=expiry_date,
                strike=float(instrument.get("strike", 0.0) or 0.0),
                option_type=str(instrument.get("option_type", "")).upper(),
                side=side,
                quantity=quantity,
                entry_price=float(entry_price),
                entry_time=now,
                stop_price=spec.get("stop_price"),
                order_id=f"PAPER-{strategy_name}-{leg_id}-{now:%H%M%S}",
                paper=True,
            )

        assert underlying is not None
        assert expiry is not None
        position_id = position_id or self._build_position_id(strategy_name, underlying, expiry, now)
        if position_id in self.positions:
            return {"success": False, "message": f"Position already exists: {position_id}"}

        position = OptionPosition(
            position_id=position_id,
            strategy_name=strategy_name,
            underlying=underlying,
            expiry=expiry,
            legs=built_legs,
            entry_time=now,
            entry_time_slot=entry_time_slot,
            estimated_margin_required=None,
            paper=True,
        )

        estimated_margin_required = position.estimate_margin_required()
        margin_limit = self._margin_limit()
        current_margin_used = self.estimated_margin_used()
        if margin_limit is not None:
            if estimated_margin_required is None:
                return {
                    "success": False,
                    "message": "Cannot estimate margin for this F&O structure; disable margin guard only if you intentionally want unbounded paper risk",
                }
            projected_margin_used = current_margin_used + estimated_margin_required
            if projected_margin_used > margin_limit:
                return {
                    "success": False,
                    "message": (
                        "Estimated F&O margin limit exceeded: "
                        f"projected Rs {projected_margin_used:.0f} > limit Rs {margin_limit:.0f}"
                    ),
                }

        position.estimated_margin_required = estimated_margin_required
        self.positions[position_id] = position
        logger.info(
            "PAPER FNO OPEN %s %s expiry=%s legs=%d cashflow=%.2f est_margin=%s",
            strategy_name,
            underlying,
            expiry.isoformat(),
            len(built_legs),
            position.net_entry_cashflow(),
            f"{estimated_margin_required:.2f}" if estimated_margin_required is not None else "n/a",
        )
        return {
            "success": True,
            "position_id": position_id,
            "net_entry_cashflow": position.net_entry_cashflow(),
            "estimated_margin_required": estimated_margin_required,
            "estimated_margin_used": self.estimated_margin_used(),
            "leg_ids": position.leg_ids(),
        }

    def current_prices(
        self,
        position_id: str,
        price_overrides: Mapping[str, float] | None = None,
    ) -> dict[str, float] | None:
        position = self.positions.get(position_id)
        if position is None:
            return None

        prices: dict[str, float] = {}
        for leg_id, leg in position.legs.items():
            if price_overrides and leg_id in price_overrides:
                prices[leg_id] = float(price_overrides[leg_id])
                continue
            if self.broker is None:
                return None
            price = self.broker.get_ltp_for_instrument(
                {
                    "tradingsymbol": leg.tradingsymbol,
                    "symboltoken": leg.symboltoken,
                    "exchange": leg.exchange,
                }
            )
            if price is None:
                return None
            prices[leg_id] = float(price)
        return prices

    def position_pnl(
        self,
        position_id: str,
        price_overrides: Mapping[str, float] | None = None,
    ) -> float | None:
        position = self.positions.get(position_id)
        if position is None:
            return None
        prices = self.current_prices(position_id, price_overrides=price_overrides)
        if prices is None:
            return None
        return position.pnl_amount(prices)

    def position_pnl_pct(
        self,
        position_id: str,
        price_overrides: Mapping[str, float] | None = None,
    ) -> float | None:
        position = self.positions.get(position_id)
        if position is None:
            return None
        prices = self.current_prices(position_id, price_overrides=price_overrides)
        if prices is None:
            return None
        return position.pnl_pct(prices)

    def close_position(
        self,
        position_id: str,
        *,
        exit_reason: str = "manual",
        price_overrides: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        position = self.positions.get(position_id)
        if position is None:
            return {"success": False, "message": f"Unknown position: {position_id}"}

        prices = self.current_prices(position_id, price_overrides=price_overrides)
        if prices is None:
            return {"success": False, "message": f"No current prices for {position_id}"}

        pnl = position.pnl_amount(prices)
        net_entry_cashflow = position.net_entry_cashflow()
        pnl_pct = position.pnl_pct(prices)

        try:
            trade_id = self.journal.record_trade(
                TradeRecord(
                    symbol=position.underlying,
                    side="MULTI",
                    entry_rsi=None,
                    volume_ratio=None,
                    entry_time=position.entry_time,
                    exit_time=datetime.now(),
                    exit_reason=exit_reason,
                    pnl_pct=pnl_pct,
                    pnl_amount=pnl,
                    source="paper_fno" if position.paper else "live_fno",
                    quantity=sum(leg.quantity for leg in position.legs.values()),
                    strategy_name=position.strategy_name,
                    underlying=position.underlying,
                    expiry=position.expiry.isoformat(),
                    structure_type=position.strategy_name,
                    legs_json=json.dumps(
                        [
                            {
                                "leg_id": leg.leg_id,
                                "tradingsymbol": leg.tradingsymbol,
                                "option_type": leg.option_type,
                                "side": leg.side,
                                "quantity": leg.quantity,
                                "entry_price": leg.entry_price,
                                "exit_price": prices.get(leg.leg_id),
                                "strike": leg.strike,
                                "expiry": leg.expiry.isoformat(),
                            }
                            for leg in position.legs.values()
                        ]
                    ),
                    net_entry_cashflow=net_entry_cashflow,
                    entry_time_slot=position.entry_time_slot,
                    estimated_margin_required=position.estimated_margin_required,
                )
            )
            logger.info("Journal recorded F&O trade #%d %s", trade_id, position_id)
        except Exception as exc:
            logger.warning("Failed to record F&O trade in journal: %s", exc)

        del self.positions[position_id]
        logger.info(
            "PAPER FNO CLOSE %s reason=%s pnl=%.2f",
            position_id,
            exit_reason,
            pnl,
        )
        return {
            "success": True,
            "position_id": position_id,
            "exit_reason": exit_reason,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "prices": prices,
        }

    def close_all(
        self,
        *,
        exit_reason: str = "square-off",
        price_overrides: Mapping[str, Mapping[str, float]] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for position_id in list(self.positions):
            overrides = None
            if price_overrides is not None:
                overrides = price_overrides.get(position_id)
            results.append(
                self.close_position(
                    position_id,
                    exit_reason=exit_reason,
                    price_overrides=overrides,
                )
            )
        return results

    @staticmethod
    def _margin_limit() -> float | None:
        max_util_pct = Config.FNO_MAX_MARGIN_UTILIZATION_PCT
        if max_util_pct <= 0:
            return None
        return Config.ACCOUNT_EQUITY * (max_util_pct / 100.0)

    @staticmethod
    def _build_position_id(
        strategy_name: str,
        underlying: str,
        expiry: date,
        now: datetime,
    ) -> str:
        return (
            f"{strategy_name}:{underlying}:{expiry:%Y%m%d}:{now:%H%M%S}"
        )