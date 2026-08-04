"""Angel scrip master cache and NFO index option resolution."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from intraday_agent.config import Config
from intraday_agent.instruments import get_registry

logger = logging.getLogger(__name__)

_EXCHANGE_NFO = "NFO"
_EXCHANGE_NSE = "NSE"
_INSTRUMENT_OPTIDX = "OPTIDX"
_INSTRUMENT_AMXIDX = "AMXIDX"
_OPTION_TYPES = frozenset({"CE", "PE"})


def _parse_expiry(raw: Any) -> date | None:
    text = str(raw or "").strip().upper()
    if not text:
        return None
    return datetime.strptime(text, "%d%b%Y").date()


def _parse_scaled_price(raw: Any) -> float:
    try:
        return float(raw or 0.0) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _last_tuesday_of_month(day: date) -> date:
    cursor = day.replace(day=28) + timedelta(days=4)
    cursor -= timedelta(days=cursor.day)
    while cursor.weekday() != 1:
        cursor -= timedelta(days=1)
    return cursor


def is_monthly_expiry(day: date) -> bool:
    return day == _last_tuesday_of_month(day)


@dataclass(frozen=True)
class FnOContract:
    underlying: str
    tradingsymbol: str
    symboltoken: str
    exchange: str
    instrument_type: str
    expiry: date
    strike: float
    option_type: str
    lot_size: int
    tick_size: float

    def as_instrument(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying,
            "tradingsymbol": self.tradingsymbol,
            "symboltoken": self.symboltoken,
            "exchange": self.exchange,
            "instrumenttype": self.instrument_type,
            "expiry": self.expiry.isoformat(),
            "strike": self.strike,
            "option_type": self.option_type,
            "lotsize": self.lot_size,
            "tick_size": self.tick_size,
        }


class FnOInstrumentRegistry:
    """Resolve Angel NFO option contracts by underlying, expiry, strike, and side."""

    def __init__(self, cache_path: str | None = None):
        self.cache_path = cache_path or Config.INSTRUMENTS_CACHE
        self._loaded = False
        self._by_contract: dict[tuple[str, date, float, str], FnOContract] = {}
        self._expiries: dict[str, set[date]] = {}
        self._strikes: dict[tuple[str, date], set[float]] = {}
        self._spot_by_underlying: dict[str, dict[str, Any]] = {}

    def load(self, force_refresh: bool = False) -> None:
        if self._loaded and not force_refresh:
            return

        # Reuse the existing Angel scrip-master download/cache flow.
        get_registry().load(force_refresh=force_refresh)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)

        self._build_index(rows)
        self._loaded = True
        logger.info("Loaded %d NFO option contracts", len(self._by_contract))

    def _build_index(self, rows: list[dict[str, Any]]) -> None:
        self._by_contract.clear()
        self._expiries.clear()
        self._strikes.clear()
        self._spot_by_underlying.clear()

        for row in rows:
            underlying = str(row.get("name", "")).upper().strip()
            if not underlying:
                continue

            exch_seg = str(row.get("exch_seg", "")).upper().strip()
            instrument_type = str(row.get("instrumenttype", "")).upper().strip()

            if exch_seg == _EXCHANGE_NSE and instrument_type == _INSTRUMENT_AMXIDX:
                self._spot_by_underlying[underlying] = {
                    "underlying": underlying,
                    "tradingsymbol": row.get("symbol", ""),
                    "symboltoken": str(row.get("token", "")),
                    "exchange": exch_seg,
                    "instrumenttype": instrument_type,
                    "tick_size": _parse_scaled_price(row.get("tick_size")),
                    "lotsize": int(row.get("lotsize", 1) or 1),
                }
                continue

            if exch_seg != _EXCHANGE_NFO or instrument_type != _INSTRUMENT_OPTIDX:
                continue

            option_type = str(row.get("symbol", ""))[-2:].upper()
            expiry = _parse_expiry(row.get("expiry"))
            if option_type not in _OPTION_TYPES or expiry is None:
                continue

            strike = _parse_scaled_price(row.get("strike"))
            contract = FnOContract(
                underlying=underlying,
                tradingsymbol=str(row.get("symbol", "")),
                symboltoken=str(row.get("token", "")),
                exchange=exch_seg,
                instrument_type=instrument_type,
                expiry=expiry,
                strike=strike,
                option_type=option_type,
                lot_size=int(row.get("lotsize", 1) or 1),
                tick_size=_parse_scaled_price(row.get("tick_size")),
            )
            key = (underlying, expiry, strike, option_type)
            self._by_contract[key] = contract
            self._expiries.setdefault(underlying, set()).add(expiry)
            self._strikes.setdefault((underlying, expiry), set()).add(strike)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def resolve_underlying_spot(self, underlying: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return self._spot_by_underlying.get(underlying.upper().strip())

    def list_expiries(
        self,
        underlying: str,
        *,
        weekly_only: bool = False,
        include_expired: bool = False,
        as_of: date | None = None,
    ) -> list[date]:
        self._ensure_loaded()
        ref = as_of or date.today()
        expiries = sorted(self._expiries.get(underlying.upper().strip(), set()))
        if not include_expired:
            expiries = [expiry for expiry in expiries if expiry >= ref]
        if weekly_only:
            expiries = [expiry for expiry in expiries if not is_monthly_expiry(expiry)]
        return expiries

    def next_expiry(
        self,
        underlying: str,
        *,
        weekly_only: bool = False,
        as_of: date | None = None,
    ) -> date | None:
        expiries = self.list_expiries(
            underlying,
            weekly_only=weekly_only,
            include_expired=False,
            as_of=as_of,
        )
        return expiries[0] if expiries else None

    def available_strikes(self, underlying: str, expiry: date) -> list[float]:
        self._ensure_loaded()
        return sorted(self._strikes.get((underlying.upper().strip(), expiry), set()))

    def nearest_strike(self, underlying: str, expiry: date, spot_price: float) -> float | None:
        strikes = self.available_strikes(underlying, expiry)
        if not strikes:
            return None
        return min(strikes, key=lambda strike: (abs(strike - spot_price), strike))

    def resolve_option(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        option_type: str,
    ) -> dict[str, Any] | None:
        self._ensure_loaded()
        normalized_type = option_type.upper().strip()
        key = (underlying.upper().strip(), expiry, float(strike), normalized_type)
        contract = self._by_contract.get(key)
        return contract.as_instrument() if contract else None

    def resolve_atm_straddle(
        self,
        underlying: str,
        expiry: date,
        spot_price: float,
    ) -> dict[str, dict[str, Any]] | None:
        strike = self.nearest_strike(underlying, expiry, spot_price)
        if strike is None:
            return None
        call_leg = self.resolve_option(underlying, expiry, strike, "CE")
        put_leg = self.resolve_option(underlying, expiry, strike, "PE")
        if call_leg is None or put_leg is None:
            return None
        return {"strike": strike, "CE": call_leg, "PE": put_leg}


_fno_registry: FnOInstrumentRegistry | None = None


def get_fno_registry() -> FnOInstrumentRegistry:
    global _fno_registry
    if _fno_registry is None:
        _fno_registry = FnOInstrumentRegistry()
        _fno_registry.load()
    return _fno_registry


def resolve_nifty_atm_straddle(spot_price: float, expiry: date | None = None) -> dict[str, Any] | None:
    registry = get_fno_registry()
    chosen_expiry = expiry or registry.next_expiry("NIFTY", weekly_only=True)
    if chosen_expiry is None:
        return None
    return registry.resolve_atm_straddle("NIFTY", chosen_expiry, spot_price)