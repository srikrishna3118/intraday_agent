"""Clock-based NIFTY options strategy planning for paper-first F&O research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from intraday_agent.config import Config
from intraday_agent.instruments_fno import FnOInstrumentRegistry, get_fno_registry


def _parse_entry_times(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass
class FnOEntryPlan:
    strategy_name: str
    underlying: str
    expiry: date
    strike: float
    entry_times: tuple[str, ...]
    exit_time: str
    leg_specs: list[dict[str, Any]]


class TimeBasedStraddleStrategy:
    """Build multi-leg entry plans for scheduled NIFTY short-premium strategies."""

    def __init__(
        self,
        registry: FnOInstrumentRegistry | None = None,
        *,
        underlying: str | None = None,
        weekly_only: bool | None = None,
        lots: int | None = None,
        hedge_wing_points: float | None = None,
        entry_times: tuple[str, ...] | None = None,
        exit_time: str | None = None,
    ):
        self.registry = registry or get_fno_registry()
        self.underlying = underlying or Config.FNO_UNDERLYING
        self.weekly_only = Config.FNO_WEEKLY_ONLY if weekly_only is None else weekly_only
        self.lots = max(1, lots if lots is not None else Config.FNO_LOTS)
        self.hedge_wing_points = max(
            0.0,
            hedge_wing_points if hedge_wing_points is not None else Config.FNO_HEDGE_WING_POINTS,
        )
        self.entry_times = entry_times or _parse_entry_times(Config.FNO_ENTRY_TIMES)
        self.exit_time = exit_time or Config.FNO_EXIT_TIME

    @property
    def strategy_name(self) -> str:
        return "time_based_iron_fly" if self.hedge_wing_points > 0 else "time_based_straddle"

    def select_expiry(self, as_of: date | None = None) -> date | None:
        return self.registry.next_expiry(
            self.underlying,
            weekly_only=self.weekly_only,
            as_of=as_of,
        )

    def build_entry_plan(
        self,
        spot_price: float,
        *,
        as_of: date | None = None,
    ) -> FnOEntryPlan | None:
        expiry = self.select_expiry(as_of=as_of)
        if expiry is None:
            return None

        atm = self.registry.resolve_atm_straddle(self.underlying, expiry, spot_price)
        if atm is None:
            return None

        lot_size = int(atm["CE"]["lotsize"])
        quantity = lot_size * self.lots
        strike = float(atm["strike"])
        leg_specs = [
            {
                "leg_id": "ATM_CE_SHORT",
                "instrument": atm["CE"],
                "side": "SHORT",
                "quantity": quantity,
            },
            {
                "leg_id": "ATM_PE_SHORT",
                "instrument": atm["PE"],
                "side": "SHORT",
                "quantity": quantity,
            },
        ]

        if self.hedge_wing_points > 0:
            lower_strike = self.registry.nearest_strike(
                self.underlying,
                expiry,
                strike - self.hedge_wing_points,
            )
            upper_strike = self.registry.nearest_strike(
                self.underlying,
                expiry,
                strike + self.hedge_wing_points,
            )
            if lower_strike is None or upper_strike is None:
                return None
            if lower_strike >= strike or upper_strike <= strike:
                return None

            hedge_put = self.registry.resolve_option(self.underlying, expiry, lower_strike, "PE")
            hedge_call = self.registry.resolve_option(self.underlying, expiry, upper_strike, "CE")
            if hedge_put is None or hedge_call is None:
                return None

            leg_specs.extend(
                [
                    {
                        "leg_id": "WING_PE_LONG",
                        "instrument": hedge_put,
                        "side": "LONG",
                        "quantity": quantity,
                    },
                    {
                        "leg_id": "WING_CE_LONG",
                        "instrument": hedge_call,
                        "side": "LONG",
                        "quantity": quantity,
                    },
                ]
            )

        return FnOEntryPlan(
            strategy_name=self.strategy_name,
            underlying=self.underlying,
            expiry=expiry,
            strike=strike,
            entry_times=self.entry_times,
            exit_time=self.exit_time,
            leg_specs=leg_specs,
        )