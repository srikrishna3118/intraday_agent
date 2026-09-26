"""Intraday NIFTY options plans for the paper F&O research track."""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

import pandas as pd
import pytz

from intraday_agent.config import Config
from intraday_agent.instruments_fno import (
    FnOInstrumentRegistry,
    get_fno_registry,
    trading_dte,
)

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

GROUP_CALL = "CALL_SIDE"
GROUP_PUT = "PUT_SIDE"


def _parse_hhmm(value: str) -> dtime:
    hh, mm = value.split(":", 1)
    return dtime(int(hh), int(mm))


def _parse_entry_times(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def to_ist_naive(series: pd.Series, naive_tz: str | None = None) -> pd.Series:
    """Convert candle datetimes to naive IST (Angel cache is UTC-naive)."""
    naive_tz = (naive_tz or Config.CANDLE_NAIVE_TZ).lower()
    ts = pd.to_datetime(series)
    if getattr(ts.dt, "tz", None) is not None:
        return ts.dt.tz_convert(IST).dt.tz_localize(None)
    if naive_tz == "utc":
        return ts.dt.tz_localize("UTC").dt.tz_convert(IST).dt.tz_localize(None)
    return ts


def session_slice(
    df: pd.DataFrame,
    session: date,
    start: dtime,
    end: dtime,
    *,
    naive_tz: str | None = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["ist"] = to_ist_naive(out["datetime"], naive_tz)
    start_ts = datetime.combine(session, start)
    end_ts = datetime.combine(session, end)
    mask = (out["ist"] >= start_ts) & (out["ist"] <= end_ts)
    return out.loc[mask].sort_values("ist").reset_index(drop=True)


def trend_state(
    df_5m: pd.DataFrame | None,
    *,
    fast: int | None = None,
    slow: int | None = None,
    at: datetime | None = None,
    naive_tz: str | None = None,
) -> str:
    """Bull / bear / neutral from the last completed 5-min bar.

    Bull: close > EMA_fast > EMA_slow. Bear: close < EMA_fast < EMA_slow.
    """
    if df_5m is None or df_5m.empty:
        return "neutral"
    fast = fast if fast is not None else Config.FNO_EMA_FAST
    slow = slow if slow is not None else Config.FNO_EMA_SLOW
    out = df_5m.sort_values("datetime").copy()
    out["ist"] = to_ist_naive(out["datetime"], naive_tz)
    out["ema_fast"] = out["close"].ewm(span=fast, adjust=False).mean()
    out["ema_slow"] = out["close"].ewm(span=slow, adjust=False).mean()
    if at is not None:
        cutoff = at.replace(tzinfo=None) if at.tzinfo is None else at.astimezone(IST).replace(tzinfo=None)
        # If `at` is timezone-aware IST wall clock already naive-combined, keep it.
        if at.tzinfo is not None:
            cutoff = at.astimezone(IST).replace(tzinfo=None)
        out = out[out["ist"] <= cutoff]
    if out.empty:
        return "neutral"
    row = out.iloc[-1]
    close = float(row["close"])
    ema_f = float(row["ema_fast"])
    ema_s = float(row["ema_slow"])
    if close > ema_f > ema_s:
        return "bull"
    if close < ema_f < ema_s:
        return "bear"
    return "neutral"


def realized_variance(
    df_5m: pd.DataFrame,
    session: date,
    start: dtime,
    end: dtime,
    *,
    naive_tz: str | None = None,
) -> float | None:
    bars = session_slice(df_5m, session, start, end, naive_tz=naive_tz)
    if len(bars) < 3:
        return None
    closes = pd.to_numeric(bars["close"], errors="coerce")
    rets = (closes / closes.shift(1)).apply(lambda x: math.log(x) if pd.notna(x) and x > 0 else float("nan"))
    rets = rets.dropna()
    if rets.empty:
        return None
    return float((rets ** 2).sum())


def remaining_move_from_rv(remaining_rv: float) -> float:
    """Map remaining realized variance (sum of squared log returns) to |log move|."""
    return math.sqrt(max(0.0, remaining_rv))


def load_expiry_model(path: str | None = None) -> dict[str, Any]:
    path = path or Config.FNO_EXPIRY_MODEL_PATH
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def forecast_remaining_log_move(
    morning_rv: float,
    prior_vix: float,
    model: MappingLike | None = None,
) -> float:
    """Walk-forward OLS: log(remaining_rv) = a + b log(morning_rv) + c log(vix)."""
    model = model or load_expiry_model()
    a = float(model.get("intercept", 0.0))
    b = float(model.get("coef_morning_rv", 0.65))
    c = float(model.get("coef_vix", 0.35))
    resid_scale = float(model.get("resid_scale", 0.45))
    t_crit = float(model.get("t_crit", 1.44))  # ~10% one-sided, df~7
    morning_rv = max(morning_rv, 1e-12)
    prior_vix = max(prior_vix, 1e-6)
    log_pred = a + b * math.log(morning_rv) + c * math.log(prior_vix)
    log_q = log_pred + t_crit * resid_scale
    return remaining_move_from_rv(math.exp(log_q))


# Avoid importing Mapping in the helper annotation at runtime for 3.9
MappingLike = dict


def strike_distance_points(
    spot: float,
    log_move: float,
    *,
    min_distance_pct: float | None = None,
) -> float:
    floor_pct = (
        Config.FNO_EXPIRY_MIN_DISTANCE_PCT if min_distance_pct is None else min_distance_pct
    )
    raw = abs(spot) * (math.exp(abs(log_move)) - 1.0)
    floor = abs(spot) * (floor_pct / 100.0)
    return max(raw, floor)


@dataclass
class FnOEntryPlan:
    strategy_name: str
    underlying: str
    expiry: date
    strike: float
    entry_times: tuple[str, ...]
    exit_time: str
    leg_specs: list[dict[str, Any]]
    slot_id: str = ""
    entry_features: dict[str, Any] = field(default_factory=dict)
    stop_pct: float = 20.0


class FnOStrategy:
    """Build multi-leg paper plans. Indicator math lives here, not in the agent."""

    name = "base"

    def __init__(
        self,
        registry: FnOInstrumentRegistry | None = None,
        *,
        underlying: str | None = None,
        lots: int | None = None,
        hedge_wing_points: float | None = None,
        weekly_only: bool | None = None,
        **kwargs: Any,
    ):
        self.registry = registry or get_fno_registry()
        self.underlying = underlying or Config.FNO_UNDERLYING
        self.lots = max(1, lots if lots is not None else Config.FNO_LOTS)
        self.hedge_wing_points = max(
            0.0,
            hedge_wing_points if hedge_wing_points is not None else Config.FNO_HEDGE_WING_POINTS,
        )
        self.weekly_only = Config.FNO_WEEKLY_ONLY if weekly_only is None else weekly_only
        self.exit_time = Config.FNO_EXIT_TIME
        self.entry_times: tuple[str, ...] = ()
        self._extra = kwargs

    @property
    def strategy_name(self) -> str:
        return self.name

    def select_expiry(self, as_of: date | None = None) -> date | None:
        return self.registry.nearest_expiry(self.underlying, as_of=as_of)

    def lot_quantity(self, instrument: dict[str, Any]) -> int:
        return int(instrument.get("lotsize") or 1) * self.lots

    def _wing_legs(
        self,
        expiry: date,
        short_strike: float,
        option_type: str,
        quantity: int,
        group: str,
    ) -> list[dict[str, Any]] | None:
        if self.hedge_wing_points <= 0:
            return []
        if option_type == "CE":
            wing_strike = self.registry.nearest_strike(
                self.underlying, expiry, short_strike + self.hedge_wing_points
            )
        else:
            wing_strike = self.registry.nearest_strike(
                self.underlying, expiry, short_strike - self.hedge_wing_points
            )
        if wing_strike is None:
            return None
        if option_type == "CE" and wing_strike <= short_strike:
            return None
        if option_type == "PE" and wing_strike >= short_strike:
            return None
        hedge = self.registry.resolve_option(self.underlying, expiry, wing_strike, option_type)
        if hedge is None:
            return None
        return [
            {
                "leg_id": f"WING_{option_type}_LONG",
                "instrument": hedge,
                "side": "LONG",
                "quantity": quantity,
                "group": group,
                "stop_pct": None,
                "stop_kind": None,
            }
        ]

    def should_consider(self, now: datetime, slots_used: set[str]) -> bool:
        return False

    def build_entry_plan(self, spot_price: float, **kwargs: Any) -> FnOEntryPlan | None:
        raise NotImplementedError


class TimeBasedStraddleStrategy(FnOStrategy):
    """09:20 ATM short straddle; wings → iron fly. Per-side 20% stop."""

    def __init__(self, *args, entry_times: tuple[str, ...] | None = None, exit_time: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry_times = entry_times or _parse_entry_times(Config.FNO_ENTRY_TIMES)
        self.exit_time = exit_time or Config.FNO_EXIT_TIME

    @property
    def strategy_name(self) -> str:
        return "time_based_iron_fly" if self.hedge_wing_points > 0 else "time_based_straddle"

    @property
    def name(self) -> str:
        return "time_based_straddle"

    def should_consider(self, now: datetime, slots_used: set[str]) -> bool:
        hhmm = now.strftime("%H:%M")
        now_t = now.time().replace(second=0, microsecond=0)
        for slot in self.entry_times:
            if slot in slots_used:
                continue
            start = _parse_hhmm(slot)
            end_dt = datetime.combine(now.date(), start) + timedelta(minutes=2)
            if start <= now_t <= end_dt.time():
                return True
            if slot == hhmm:
                return True
        return False

    def _due_slot(self, now: datetime, slots_used: set[str]) -> str | None:
        now_t = now.time().replace(second=0, microsecond=0)
        for slot in self.entry_times:
            if slot in slots_used:
                continue
            start = _parse_hhmm(slot)
            end_dt = datetime.combine(now.date(), start) + timedelta(minutes=2)
            if start <= now_t <= end_dt.time():
                return slot
        return None

    def build_entry_plan(
        self,
        spot_price: float,
        *,
        as_of: date | None = None,
        now: datetime | None = None,
        slots_used: set[str] | None = None,
        **kwargs: Any,
    ) -> FnOEntryPlan | None:
        expiry = self.select_expiry(as_of=as_of)
        if expiry is None:
            return None
        atm = self.registry.resolve_atm_straddle(self.underlying, expiry, spot_price)
        if atm is None:
            return None
        quantity = self.lot_quantity(atm["CE"])
        strike = float(atm["strike"])
        stop_pct = Config.FNO_LEG_STOP_LOSS_PCT
        legs = [
            {
                "leg_id": "ATM_CE_SHORT",
                "instrument": atm["CE"],
                "side": "SHORT",
                "quantity": quantity,
                "group": GROUP_CALL,
                "stop_pct": stop_pct,
                "stop_kind": "short_rise",
            },
            {
                "leg_id": "ATM_PE_SHORT",
                "instrument": atm["PE"],
                "side": "SHORT",
                "quantity": quantity,
                "group": GROUP_PUT,
                "stop_pct": stop_pct,
                "stop_kind": "short_rise",
            },
        ]
        call_wings = self._wing_legs(expiry, strike, "CE", quantity, GROUP_CALL)
        put_wings = self._wing_legs(expiry, strike, "PE", quantity, GROUP_PUT)
        if call_wings is None or put_wings is None:
            return None
        legs.extend(call_wings)
        legs.extend(put_wings)
        slot = "09:20"
        if now is not None:
            slot = self._due_slot(now, slots_used or set()) or slot
        return FnOEntryPlan(
            strategy_name=self.strategy_name,
            underlying=self.underlying,
            expiry=expiry,
            strike=strike,
            entry_times=self.entry_times,
            exit_time=self.exit_time,
            leg_specs=legs,
            slot_id=slot,
            stop_pct=stop_pct,
        )


class EmaCreditSpreadStrategy(FnOStrategy):
    """09:20 EMA stack → 2-leg credit spread with a 200-pt wing."""

    name = "ema920_credit_spread"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry_times = (Config.FNO_EMA_ENTRY_TIME,)

    def should_consider(self, now: datetime, slots_used: set[str]) -> bool:
        if "09:20" in slots_used or Config.FNO_EMA_ENTRY_TIME in slots_used:
            return False
        start = _parse_hhmm(Config.FNO_EMA_ENTRY_TIME)
        end_dt = datetime.combine(now.date(), start) + timedelta(minutes=2)
        now_t = now.time().replace(second=0, microsecond=0)
        return start <= now_t <= end_dt.time()

    def build_entry_plan(
        self,
        spot_price: float,
        *,
        as_of: date | None = None,
        candles_5m: pd.DataFrame | None = None,
        now: datetime | None = None,
        **kwargs: Any,
    ) -> FnOEntryPlan | None:
        state = trend_state(candles_5m, at=now)
        if state not in {"bull", "bear"}:
            return None
        expiry = self.select_expiry(as_of=as_of)
        if expiry is None:
            return None
        atm = self.registry.resolve_atm_straddle(self.underlying, expiry, spot_price)
        if atm is None:
            return None
        quantity = self.lot_quantity(atm["CE"])
        strike = float(atm["strike"])
        stop_pct = Config.FNO_LEG_STOP_LOSS_PCT
        if state == "bull":
            option_type, group, short_inst = "PE", GROUP_PUT, atm["PE"]
        else:
            option_type, group, short_inst = "CE", GROUP_CALL, atm["CE"]
        wings = self._wing_legs(expiry, strike, option_type, quantity, group)
        if wings is None or not wings:
            return None
        legs = [
            {
                "leg_id": f"ATM_{option_type}_SHORT",
                "instrument": short_inst,
                "side": "SHORT",
                "quantity": quantity,
                "group": group,
                "stop_pct": stop_pct,
                "stop_kind": "short_rise",
            },
            *wings,
        ]
        plan = FnOEntryPlan(
            strategy_name=self.strategy_name,
            underlying=self.underlying,
            expiry=expiry,
            strike=strike,
            entry_times=self.entry_times,
            exit_time=self.exit_time,
            leg_specs=legs,
            slot_id=Config.FNO_EMA_ENTRY_TIME,
            entry_features={"ema_state": state},
            stop_pct=stop_pct,
        )
        return plan


class EmaOptionBuyStrategy(FnOStrategy):
    """09:20 EMA stack → buy ~₹200 premium option on the signal side."""

    name = "ema920_option_buy"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry_times = (Config.FNO_EMA_ENTRY_TIME,)

    def should_consider(self, now: datetime, slots_used: set[str]) -> bool:
        if Config.FNO_EMA_ENTRY_TIME in slots_used or "09:20" in slots_used:
            return False
        start = _parse_hhmm(Config.FNO_EMA_ENTRY_TIME)
        end_dt = datetime.combine(now.date(), start) + timedelta(minutes=2)
        now_t = now.time().replace(second=0, microsecond=0)
        return start <= now_t <= end_dt.time()

    def _pick_premium(
        self,
        expiry: date,
        option_type: str,
        spot: float,
        prices: dict[float, float],
        target: float,
    ) -> dict[str, Any] | None:
        if not prices:
            return None
        strike = min(prices, key=lambda s: (abs(prices[s] - target), abs(s - spot)))
        return self.registry.resolve_option(self.underlying, expiry, strike, option_type)

    def build_entry_plan(
        self,
        spot_price: float,
        *,
        as_of: date | None = None,
        candles_5m: pd.DataFrame | None = None,
        now: datetime | None = None,
        option_prices: dict[tuple[float, str], float] | None = None,
        **kwargs: Any,
    ) -> FnOEntryPlan | None:
        state = trend_state(candles_5m, at=now)
        if state not in {"bull", "bear"}:
            return None
        expiry = self.select_expiry(as_of=as_of)
        if expiry is None:
            return None
        option_type = "CE" if state == "bull" else "PE"
        group = GROUP_CALL if option_type == "CE" else GROUP_PUT
        prices: dict[float, float] = {}
        if option_prices:
            prices = {k[0]: v for k, v in option_prices.items() if k[1] == option_type}
        instrument = None
        if prices:
            instrument = self._pick_premium(
                expiry, option_type, spot_price, prices, Config.FNO_BUY_PREMIUM_TARGET
            )
        if instrument is None:
            # Fall back to ATM if we have no chain LTPs yet.
            atm = self.registry.resolve_atm_straddle(self.underlying, expiry, spot_price)
            if atm is None:
                return None
            instrument = atm[option_type]
        quantity = self.lot_quantity(instrument)
        legs = [
            {
                "leg_id": f"LONG_{option_type}",
                "instrument": instrument,
                "side": "LONG",
                "quantity": quantity,
                "group": group,
                "stop_pct": Config.FNO_BUY_STOP_PCT,
                "stop_kind": "long_drop",
            }
        ]
        return FnOEntryPlan(
            strategy_name=self.strategy_name,
            underlying=self.underlying,
            expiry=expiry,
            strike=float(instrument.get("strike") or 0),
            entry_times=self.entry_times,
            exit_time=self.exit_time,
            leg_specs=legs,
            slot_id=Config.FNO_EMA_ENTRY_TIME,
            entry_features={"ema_state": state},
            stop_pct=Config.FNO_BUY_STOP_PCT,
        )


class PremiumOrbShortStrategy(FnOStrategy):
    """Sell a ~₹200 option after its 09:15–11:15 range breaks to the downside."""

    name = "premium_orb_short"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry_times = (Config.FNO_ORB_PICK_TIME,)
        self._picks: dict[str, dict[str, Any]] = {}
        self._pick_date: date | None = None

    def _roll(self, session: date) -> None:
        if self._pick_date != session:
            self._pick_date = session
            self._picks = {}

    def should_consider(self, now: datetime, slots_used: set[str]) -> bool:
        now_t = now.time().replace(second=0, microsecond=0)
        pick = _parse_hhmm(Config.FNO_ORB_PICK_TIME)
        range_end = _parse_hhmm(Config.FNO_ORB_RANGE_END)
        cutoff = _parse_hhmm(Config.FNO_ENTRY_CUTOFF)
        if now_t < pick:
            return False
        if now_t < range_end:
            return "PICK" not in slots_used
        return now_t <= cutoff

    def remember_pick(self, option_type: str, instrument: dict[str, Any], ltp: float) -> None:
        self._picks[option_type] = {"instrument": instrument, "entry_ltp": ltp}

    def build_entry_plan(
        self,
        spot_price: float,
        *,
        as_of: date | None = None,
        now: datetime | None = None,
        slots_used: set[str] | None = None,
        option_prices: dict[tuple[float, str], float] | None = None,
        option_candles: dict[str, pd.DataFrame] | None = None,
        **kwargs: Any,
    ) -> FnOEntryPlan | None:
        session = as_of or (now.date() if now else date.today())
        self._roll(session)
        expiry = self.select_expiry(as_of=session)
        if expiry is None or now is None:
            return None
        now_t = now.time().replace(second=0, microsecond=0)
        slots_used = slots_used or set()
        pick_t = _parse_hhmm(Config.FNO_ORB_PICK_TIME)
        range_end = _parse_hhmm(Config.FNO_ORB_RANGE_END)

        if now_t < range_end:
            if "PICK" in slots_used or not option_prices:
                return None
            if pick_t <= now_t <= (datetime.combine(session, pick_t) + timedelta(minutes=4)).time():
                for option_type in ("CE", "PE"):
                    typed = {k[0]: v for k, v in option_prices.items() if k[1] == option_type}
                    if not typed:
                        continue
                    strike = min(
                        typed,
                        key=lambda s: (abs(typed[s] - Config.FNO_ORB_PREMIUM_TARGET), abs(s - spot_price)),
                    )
                    inst = self.registry.resolve_option(self.underlying, expiry, strike, option_type)
                    if inst:
                        self.remember_pick(option_type, inst, typed[strike])
                # Marker plan — agent records the PICK slot without opening.
                return FnOEntryPlan(
                    strategy_name=self.strategy_name,
                    underlying=self.underlying,
                    expiry=expiry,
                    strike=0.0,
                    entry_times=self.entry_times,
                    exit_time=self.exit_time,
                    leg_specs=[],
                    slot_id="PICK",
                    entry_features={"orb_picks": {k: v["instrument"]["strike"] for k, v in self._picks.items()}},
                )
            return None

        option_candles = option_candles or {}
        for option_type, pick in self._picks.items():
            slot = f"ORB_{option_type}"
            if slot in slots_used:
                continue
            inst = pick["instrument"]
            key = inst.get("tradingsymbol", "")
            df = option_candles.get(key)
            if df is None or df.empty:
                continue
            bars = session_slice(df, session, dtime(9, 15), range_end)
            if bars.empty:
                continue
            range_low = float(bars["low"].min())
            live = session_slice(df, session, range_end, now.time().replace(second=0, microsecond=0))
            if live.empty:
                continue
            last = live.iloc[-1]
            if float(last["close"]) >= range_low:
                continue
            quantity = self.lot_quantity(inst)
            group = GROUP_CALL if option_type == "CE" else GROUP_PUT
            strike = float(inst["strike"])
            wings = self._wing_legs(expiry, strike, option_type, quantity, group)
            if wings is None or not wings:
                continue
            legs = [
                {
                    "leg_id": f"ORB_{option_type}_SHORT",
                    "instrument": inst,
                    "side": "SHORT",
                    "quantity": quantity,
                    "group": group,
                    "stop_pct": Config.FNO_LEG_STOP_LOSS_PCT,
                    "stop_kind": "short_rise",
                },
                *wings,
            ]
            return FnOEntryPlan(
                strategy_name=self.strategy_name,
                underlying=self.underlying,
                expiry=expiry,
                strike=strike,
                entry_times=self.entry_times,
                exit_time=self.exit_time,
                leg_specs=legs,
                slot_id=slot,
                entry_features={"orb_range_low": range_low, "orb_side": option_type},
                stop_pct=Config.FNO_LEG_STOP_LOSS_PCT,
            )
        return None


class ExpiryVolStrangleStrategy(FnOStrategy):
    """Expiry-day 11:00 remaining-vol short strangle with 200-pt wings."""

    name = "expiry_vol_strangle"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry_times = (Config.FNO_EXPIRY_ENTRY_TIME,)
        self.exit_time = Config.FNO_EXPIRY_EXIT_TIME
        self._model = load_expiry_model()

    def should_consider(self, now: datetime, slots_used: set[str]) -> bool:
        if Config.FNO_EXPIRY_ENTRY_TIME in slots_used:
            return False
        expiry = self.select_expiry(as_of=now.date())
        if expiry is None or trading_dte(expiry, now.date()) != 0:
            return False
        start = _parse_hhmm(Config.FNO_EXPIRY_ENTRY_TIME)
        end_dt = datetime.combine(now.date(), start) + timedelta(minutes=2)
        now_t = now.time().replace(second=0, microsecond=0)
        return start <= now_t <= end_dt.time()

    def build_entry_plan(
        self,
        spot_price: float,
        *,
        as_of: date | None = None,
        candles_5m: pd.DataFrame | None = None,
        prior_vix: float | None = None,
        **kwargs: Any,
    ) -> FnOEntryPlan | None:
        session = as_of or date.today()
        expiry = self.select_expiry(as_of=session)
        if expiry is None or trading_dte(expiry, session) != 0:
            return None
        morning_rv = realized_variance(
            candles_5m if candles_5m is not None else pd.DataFrame(),
            session,
            dtime(9, 15),
            _parse_hhmm(Config.FNO_EXPIRY_ENTRY_TIME),
        )
        if morning_rv is None or prior_vix is None:
            return None
        log_move = forecast_remaining_log_move(morning_rv, prior_vix, self._model)
        distance = strike_distance_points(spot_price, log_move)
        call_strike = self.registry.nearest_strike(self.underlying, expiry, spot_price + distance)
        put_strike = self.registry.nearest_strike(self.underlying, expiry, spot_price - distance)
        if call_strike is None or put_strike is None:
            return None
        call = self.registry.resolve_option(self.underlying, expiry, call_strike, "CE")
        put = self.registry.resolve_option(self.underlying, expiry, put_strike, "PE")
        if call is None or put is None:
            return None
        quantity = self.lot_quantity(call)
        stop_pct = Config.FNO_EXPIRY_STOP_PCT
        call_wings = self._wing_legs(expiry, call_strike, "CE", quantity, GROUP_CALL)
        put_wings = self._wing_legs(expiry, put_strike, "PE", quantity, GROUP_PUT)
        if call_wings is None or put_wings is None:
            return None
        legs = [
            {
                "leg_id": "VOL_CE_SHORT",
                "instrument": call,
                "side": "SHORT",
                "quantity": quantity,
                "group": GROUP_CALL,
                "stop_pct": stop_pct,
                "stop_kind": "short_rise",
            },
            {
                "leg_id": "VOL_PE_SHORT",
                "instrument": put,
                "side": "SHORT",
                "quantity": quantity,
                "group": GROUP_PUT,
                "stop_pct": stop_pct,
                "stop_kind": "short_rise",
            },
            *call_wings,
            *put_wings,
        ]
        return FnOEntryPlan(
            strategy_name=self.strategy_name,
            underlying=self.underlying,
            expiry=expiry,
            strike=float(call_strike),
            entry_times=self.entry_times,
            exit_time=self.exit_time,
            leg_specs=legs,
            slot_id=Config.FNO_EXPIRY_ENTRY_TIME,
            entry_features={
                "morning_rv": morning_rv,
                "prior_vix": prior_vix,
                "forecast_log_move": log_move,
                "strike_distance": distance,
            },
            stop_pct=stop_pct,
        )


FNO_STRATEGY_REGISTRY: dict[str, type[FnOStrategy]] = {
    "time_based_straddle": TimeBasedStraddleStrategy,
    "time_based_iron_fly": TimeBasedStraddleStrategy,
    "ema920_credit_spread": EmaCreditSpreadStrategy,
    "ema920_option_buy": EmaOptionBuyStrategy,
    "premium_orb_short": PremiumOrbShortStrategy,
    "expiry_vol_strangle": ExpiryVolStrangleStrategy,
}


def get_fno_strategy(name: str, registry: FnOInstrumentRegistry | None = None) -> FnOStrategy:
    cls = FNO_STRATEGY_REGISTRY.get(name.lower().strip())
    if cls is None:
        raise ValueError(f"Unknown FNO strategy: {name}")
    return cls(registry)


def build_fno_strategies(registry: FnOInstrumentRegistry | None = None) -> list[FnOStrategy]:
    reg = registry or get_fno_registry()
    seen: set[str] = set()
    out: list[FnOStrategy] = []
    for name in Config.FNO_STRATEGIES:
        key = name.lower().strip()
        if key in seen or key not in FNO_STRATEGY_REGISTRY:
            continue
        seen.add(key)
        out.append(get_fno_strategy(key, reg))
    return out
