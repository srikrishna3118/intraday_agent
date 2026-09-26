"""Paper-first multi-leg options position tracking for NIFTY F&O research."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Mapping

from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeJournal, TradeRecord

if TYPE_CHECKING:
    from intraday_agent.broker import AngelBroker

logger = logging.getLogger(__name__)


def _parse_date(raw: Any) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    return date.fromisoformat(str(raw)[:10])


def _parse_dt(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    return datetime.fromisoformat(str(raw))


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
    stop_pct: float | None = None
    stop_kind: str | None = None
    group: str = ""
    order_id: str | None = None
    paper: bool = True
    exit_price: float | None = None
    exit_time: datetime | None = None
    exit_reason: str | None = None

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    def mark_closed(self, price: float, reason: str, when: datetime | None = None) -> None:
        self.exit_price = float(price)
        self.exit_reason = reason
        self.exit_time = when or datetime.now()

    def pnl_amount(self, current_price: float | None = None) -> float:
        px = self.exit_price if self.exit_price is not None else current_price
        if px is None:
            return 0.0
        diff = px - self.entry_price
        if self.side == "SHORT":
            diff = -diff
        return diff * self.quantity

    def pnl_pct(self, current_price: float | None = None) -> float:
        if self.entry_price <= 0:
            return 0.0
        px = self.exit_price if self.exit_price is not None else current_price
        if px is None:
            return 0.0
        if self.side == "LONG":
            return (px - self.entry_price) / self.entry_price * 100
        return (self.entry_price - px) / self.entry_price * 100

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expiry"] = self.expiry.isoformat()
        payload["entry_time"] = self.entry_time.isoformat()
        if self.exit_time is not None:
            payload["exit_time"] = self.exit_time.isoformat()
        return payload

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> OptionLeg:
        return cls(
            leg_id=raw["leg_id"],
            underlying=raw["underlying"],
            tradingsymbol=raw["tradingsymbol"],
            symboltoken=raw["symboltoken"],
            exchange=raw["exchange"],
            expiry=_parse_date(raw["expiry"]),
            strike=float(raw["strike"]),
            option_type=raw["option_type"],
            side=raw["side"],
            quantity=int(raw["quantity"]),
            entry_price=float(raw["entry_price"]),
            entry_time=_parse_dt(raw["entry_time"]),
            stop_price=raw.get("stop_price"),
            stop_pct=raw.get("stop_pct"),
            stop_kind=raw.get("stop_kind"),
            group=str(raw.get("group") or ""),
            order_id=raw.get("order_id"),
            paper=bool(raw.get("paper", True)),
            exit_price=raw.get("exit_price"),
            exit_time=_parse_dt(raw["exit_time"]) if raw.get("exit_time") else None,
            exit_reason=raw.get("exit_reason"),
        )


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
    entry_features: str | None = None
    strategy_key: str = ""

    def open_legs(self) -> list[OptionLeg]:
        return [leg for leg in self.legs.values() if leg.is_open]

    def is_open(self) -> bool:
        return any(leg.is_open for leg in self.legs.values())

    def net_entry_cashflow(self) -> float:
        cashflow = 0.0
        for leg in self.legs.values():
            signed = leg.entry_price * leg.quantity
            cashflow += signed if leg.side == "SHORT" else -signed
        return cashflow

    def pnl_amount(self, prices: Mapping[str, float] | None = None) -> float:
        pnl = 0.0
        for leg_id, leg in self.legs.items():
            current = None if prices is None else prices.get(leg_id)
            pnl += leg.pnl_amount(current)
        return pnl

    def pnl_pct(self, prices: Mapping[str, float] | None = None) -> float:
        net_entry_cashflow = self.net_entry_cashflow()
        if abs(net_entry_cashflow) <= 0:
            return 0.0
        return self.pnl_amount(prices) / abs(net_entry_cashflow) * 100.0

    def estimate_margin_required(self) -> float | None:
        """Approximate defined-risk capital for hedged short-premium structures."""
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

    def has_defined_risk(self) -> bool:
        shorts = [leg for leg in self.legs.values() if leg.side == "SHORT"]
        if not shorts:
            return True
        longs = [leg for leg in self.legs.values() if leg.side == "LONG"]
        for short in shorts:
            if short.option_type == "CE":
                if not any(
                    long.option_type == "CE" and long.strike > short.strike for long in longs
                ):
                    return False
            elif short.option_type == "PE":
                if not any(
                    long.option_type == "PE" and long.strike < short.strike for long in longs
                ):
                    return False
            else:
                return False
        return True

    def groups(self) -> set[str]:
        return {leg.group or "ALL" for leg in self.legs.values()}

    def legs_in_group(self, group: str) -> list[OptionLeg]:
        return [leg for leg in self.legs.values() if (leg.group or "ALL") == group]

    def leg_ids(self) -> list[str]:
        return list(self.legs)

    def to_json(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "strategy_name": self.strategy_name,
            "strategy_key": self.strategy_key,
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat(),
            "entry_time": self.entry_time.isoformat(),
            "entry_time_slot": self.entry_time_slot,
            "estimated_margin_required": self.estimated_margin_required,
            "paper": self.paper,
            "entry_features": self.entry_features,
            "legs": {leg_id: leg.to_json() for leg_id, leg in self.legs.items()},
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> OptionPosition:
        legs = {leg_id: OptionLeg.from_json(payload) for leg_id, payload in raw.get("legs", {}).items()}
        return cls(
            position_id=raw["position_id"],
            strategy_name=raw["strategy_name"],
            underlying=raw["underlying"],
            expiry=_parse_date(raw["expiry"]),
            legs=legs,
            entry_time=_parse_dt(raw["entry_time"]),
            entry_time_slot=raw.get("entry_time_slot"),
            estimated_margin_required=raw.get("estimated_margin_required"),
            paper=bool(raw.get("paper", True)),
            entry_features=raw.get("entry_features"),
            strategy_key=str(raw.get("strategy_key") or ""),
        )


class FnOOrderManager:
    """Paper-first multi-leg position manager for options strategies.

    Live order placement is intentionally deferred. This module is the state model
    and paper-execution surface needed for weekly NIFTY options research.
    """

    def __init__(
        self,
        broker: AngelBroker | None = None,
        journal: TradeJournal | None = None,
        persist_path: str | None = None,
    ):
        self.broker = broker
        self.positions: dict[str, OptionPosition] = {}
        self.journal = journal or TradeJournal()
        self.persist_path = persist_path or Config.FNO_OPEN_POSITIONS_PATH
        self.restore_on_start()

    def position_count(self, strategy_key: str | None = None) -> int:
        if strategy_key is None:
            return sum(1 for pos in self.positions.values() if pos.is_open())
        return sum(
            1
            for pos in self.positions.values()
            if pos.is_open() and pos.strategy_key == strategy_key
        )

    def get_open_positions(self, strategy_key: str | None = None) -> list[OptionPosition]:
        out = [pos for pos in self.positions.values() if pos.is_open()]
        if strategy_key is not None:
            out = [pos for pos in out if pos.strategy_key == strategy_key]
        return out

    def get_position(self, position_id: str) -> OptionPosition | None:
        return self.positions.get(position_id)

    def estimated_margin_used(self) -> float:
        return sum(position.estimated_margin_required or 0.0 for position in self.get_open_positions())

    def persist(self) -> None:
        path = self.persist_path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {
            "saved_at": datetime.now().isoformat(),
            "positions": [pos.to_json() for pos in self.positions.values() if pos.is_open()],
        }
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)

    def restore_on_start(self) -> None:
        path = self.persist_path
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not restore F&O paper positions: %s", exc)
            return
        today = datetime.now().date()
        for raw in payload.get("positions") or []:
            try:
                position = OptionPosition.from_json(raw)
            except Exception as exc:
                logger.warning("Skip unreadable F&O snapshot: %s", exc)
                continue
            if position.entry_time.date() != today:
                prices = {
                    leg.leg_id: float(leg.exit_price or leg.entry_price)
                    for leg in position.legs.values()
                }
                self.positions[position.position_id] = position
                self.close_position(
                    position.position_id,
                    exit_reason="restart_stale",
                    price_overrides=prices,
                )
                continue
            self.positions[position.position_id] = position
            logger.info("Restored same-day paper F&O %s", position.position_id)

    def open_position(
        self,
        *,
        strategy_name: str,
        leg_specs: list[dict[str, Any]],
        position_id: str | None = None,
        entry_time_slot: str | None = None,
        entry_features: str | dict[str, Any] | None = None,
        strategy_key: str = "",
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

            expiry_date = _parse_date(leg_expiry)
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
                stop_pct=spec.get("stop_pct"),
                stop_kind=spec.get("stop_kind"),
                group=str(spec.get("group") or ""),
                order_id=f"PAPER-{strategy_name}-{leg_id}-{now:%H%M%S}",
                paper=True,
            )

        assert underlying is not None
        assert expiry is not None
        position_id = position_id or self._build_position_id(strategy_name, underlying, expiry, now)
        if position_id in self.positions:
            return {"success": False, "message": f"Position already exists: {position_id}"}

        features = entry_features
        if isinstance(features, dict):
            features = json.dumps(features)

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
            entry_features=features,
            strategy_key=strategy_key or strategy_name,
        )

        if Config.FNO_DEFINED_RISK_ONLY and not position.has_defined_risk():
            return {
                "success": False,
                "message": "Unhedged short legs blocked (FNO_DEFINED_RISK_ONLY)",
            }

        basket_margin = None
        if self.broker is not None:
            basket_margin = self.broker.get_basket_margin(leg_specs)
        estimated_margin_required = basket_margin
        if estimated_margin_required is None:
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
        self.persist()
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
        missing: list[OptionLeg] = []
        for leg_id, leg in position.legs.items():
            if not leg.is_open:
                prices[leg_id] = float(leg.exit_price or 0.0)
                continue
            if price_overrides and leg_id in price_overrides:
                prices[leg_id] = float(price_overrides[leg_id])
                continue
            missing.append(leg)

        if missing and self.broker is not None:
            batch = self.broker.get_ltp_batch(
                [
                    {
                        "tradingsymbol": leg.tradingsymbol,
                        "symboltoken": leg.symboltoken,
                        "exchange": leg.exchange,
                    }
                    for leg in missing
                ]
            )
            for leg in missing:
                px = batch.get(leg.symboltoken)
                if px is None:
                    px = self.broker.get_ltp_for_instrument(
                        {
                            "tradingsymbol": leg.tradingsymbol,
                            "symboltoken": leg.symboltoken,
                            "exchange": leg.exchange,
                        }
                    )
                if px is None:
                    return None
                prices[leg.leg_id] = float(px)
        elif missing:
            return None
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

    def close_group(
        self,
        position_id: str,
        group: str,
        *,
        exit_reason: str,
        price_overrides: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        position = self.positions.get(position_id)
        if position is None:
            return {"success": False, "message": f"Unknown position: {position_id}"}
        prices = self.current_prices(position_id, price_overrides=price_overrides)
        if prices is None:
            return {"success": False, "message": f"No current prices for {position_id}"}
        now = datetime.now()
        closed = 0
        for leg in position.legs_in_group(group):
            if not leg.is_open:
                continue
            px = prices.get(leg.leg_id)
            if px is None:
                continue
            leg.mark_closed(px, exit_reason, now)
            closed += 1
        if closed == 0:
            return {"success": False, "message": f"No open legs in group {group}"}
        if position.is_open():
            self.persist()
            return {
                "success": True,
                "position_id": position_id,
                "partial": True,
                "group": group,
                "exit_reason": exit_reason,
            }
        return self.close_position(
            position_id,
            exit_reason=exit_reason,
            price_overrides=prices,
        )

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

        now = datetime.now()
        for leg in position.legs.values():
            if leg.is_open:
                px = prices.get(leg.leg_id)
                if px is None:
                    return {"success": False, "message": f"Missing price for {leg.leg_id}"}
                leg.mark_closed(px, exit_reason, now)

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
                    exit_time=now,
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
                                "exit_price": leg.exit_price,
                                "strike": leg.strike,
                                "expiry": leg.expiry.isoformat(),
                                "group": leg.group,
                                "exit_reason": leg.exit_reason,
                                "exit_time": leg.exit_time.isoformat() if leg.exit_time else None,
                            }
                            for leg in position.legs.values()
                        ]
                    ),
                    net_entry_cashflow=net_entry_cashflow,
                    entry_time_slot=position.entry_time_slot,
                    estimated_margin_required=position.estimated_margin_required,
                    entry_features=position.entry_features,
                )
            )
            logger.info("Journal recorded F&O trade #%d %s", trade_id, position_id)
        except Exception as exc:
            logger.warning("Failed to record F&O trade in journal: %s", exc)

        del self.positions[position_id]
        self.persist()
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
        strategy_key: str | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for position in list(self.get_open_positions(strategy_key)):
            overrides = None
            if price_overrides is not None:
                overrides = price_overrides.get(position.position_id)
            results.append(
                self.close_position(
                    position.position_id,
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
        capital = Config.FNO_CAPITAL if Config.FNO_CAPITAL > 0 else Config.ACCOUNT_EQUITY
        return capital * (max_util_pct / 100.0)

    @staticmethod
    def _build_position_id(
        strategy_name: str,
        underlying: str,
        expiry: date,
        now: datetime,
    ) -> str:
        return f"{strategy_name}:{underlying}:{expiry:%Y%m%d}:{now:%H%M%S}"
