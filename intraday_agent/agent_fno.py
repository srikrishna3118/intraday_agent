"""Paper-first multi-arm NIFTY options agent loop."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, time as dtime
from typing import Any

import pandas as pd
import pytz

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.guard import TradeGuard
from intraday_agent.instruments_fno import expiry_cycle_day, get_fno_registry
from intraday_agent.learning.candle_store import load as load_index_candles
from intraday_agent.orders_fno import FnOOrderManager, OptionPosition
from intraday_agent.strategy_fno import (
    FnOStrategy,
    PremiumOrbShortStrategy,
    build_fno_strategies,
    trend_state,
)

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def _parse_hhmm(value: str) -> dtime:
    hh, mm = value.split(":", 1)
    return dtime(int(hh), int(mm))


def _make_fno_guard() -> TradeGuard:
    return TradeGuard(
        max_daily_loss=Config.FNO_MAX_DAILY_LOSS,
        max_daily_profit=0,
        max_trades_per_day=0,
        max_trades_per_symbol=0,
        symbol_cooldown_min=0,
        loss_cooldown_min=0,
    )


class IntradayAgentFnO:
    """Paper-only options loop: independent arms, shared Angel session."""

    def __init__(
        self,
        *,
        broker: AngelBroker | None = None,
        order_manager: FnOOrderManager | None = None,
        strategies: list[FnOStrategy] | None = None,
        guard: TradeGuard | None = None,
    ):
        Config.validate()
        self.registry = get_fno_registry()
        self.broker = broker or AngelBroker()
        if broker is None:
            self.broker.login()
            if Config.STREAM_ENABLED:
                self.broker.connect_stream()
        self.strategies = strategies or build_fno_strategies(self.registry)
        self.orders = order_manager or FnOOrderManager(self.broker)
        self.guards: dict[str, TradeGuard] = {
            strategy.name: (guard if guard is not None and len(self.strategies) == 1 else _make_fno_guard())
            for strategy in self.strategies
        }
        if guard is not None and len(self.strategies) == 1:
            self.guards[self.strategies[0].name] = guard
        self._slots_today: dict[str, set[str]] = {s.name: set() for s in self.strategies}
        self._slot_date: date | None = None
        self._spot_5m: pd.DataFrame | None = None
        self._spot_5m_at: float = 0.0
        self._vix_ltp: float | None = None
        self._vix_at: float = 0.0
        self._greeks: list[dict[str, Any]] = []
        self._greeks_at: float = 0.0
        self._last_iv_snap: float = 0.0
        self._captured_date: date | None = None
        self._chain_prices: dict[tuple[float, str], float] = {}
        self._chain_at: float = 0.0

    @staticmethod
    def now_ist() -> datetime:
        return datetime.now(IST)

    def _roll_day(self) -> None:
        today = self.now_ist().date()
        if self._slot_date != today:
            self._slot_date = today
            self._slots_today = {s.name: set() for s in self.strategies}

    def is_market_open(self) -> bool:
        now = self.now_ist()
        if now.weekday() >= 5:
            return False
        t = now.time()
        return dtime(9, 15) <= t <= dtime(15, 30)

    def is_square_off_time(self) -> bool:
        return self.now_ist().time() >= _parse_hhmm(Config.FNO_EXIT_TIME)

    def is_past_entry_cutoff(self) -> bool:
        return self.now_ist().time() > _parse_hhmm(Config.FNO_ENTRY_CUTOFF)

    def should_idle_shutdown(self) -> bool:
        if self.orders.position_count() > 0:
            return False
        now = self.now_ist()
        if now.time() < _parse_hhmm(Config.FNO_EXIT_TIME):
            return False
        if Config.FNO_CAPTURE_ON_EXIT and self._captured_date != now.date():
            return False
        return True

    def _slots_for(self, strategy: FnOStrategy) -> set[str]:
        self._roll_day()
        return self._slots_today.setdefault(strategy.name, set())

    def _spot_instrument(self) -> dict | None:
        underlying = Config.FNO_UNDERLYING
        if self.strategies:
            underlying = self.strategies[0].underlying
        return self.registry.resolve_underlying_spot(underlying)

    def _refresh_spot_5m(self) -> pd.DataFrame | None:
        now = time.time()
        if self._spot_5m is not None and now - self._spot_5m_at < 45:
            return self._spot_5m
        inst = self._spot_instrument()
        if not inst:
            return self._spot_5m
        df = self.broker.get_candles_for_instrument(
            inst, interval="FIVE_MINUTE", lookback=80
        )
        if df is not None and not df.empty:
            self._spot_5m = df
            self._spot_5m_at = now
        return self._spot_5m

    def _india_vix(self) -> float | None:
        now = time.time()
        if self._vix_ltp is not None and now - self._vix_at < 60:
            return self._vix_ltp
        from intraday_agent.market_regime import INDIA_VIX

        px = self.broker.get_ltp_for_instrument(INDIA_VIX)
        if px is not None:
            self._vix_ltp = float(px)
            self._vix_at = now
        return self._vix_ltp

    def _prior_vix(self) -> float | None:
        df = load_index_candles("INDIAVIX", "ONE_DAY")
        if df is None or df.empty:
            df = self.broker.get_index_candles("INDIAVIX", interval="ONE_DAY", lookback=8)
        if df is None or df.empty:
            return self._india_vix()
        today = self.now_ist().date()
        work = df.copy()
        work["datetime"] = pd.to_datetime(work["datetime"])
        prior = work[work["datetime"].dt.date < today]
        if prior.empty:
            return float(work.iloc[-1]["close"])
        return float(prior.iloc[-1]["close"])

    def _greeks_chain(self, expiry: date) -> list[dict[str, Any]]:
        now = time.time()
        if self._greeks and now - self._greeks_at < 50:
            return self._greeks
        rows = self.broker.get_option_greeks(Config.FNO_UNDERLYING, expiry)
        if rows:
            self._greeks = rows
            self._greeks_at = now
            time.sleep(1.05)
        return self._greeks

    def _atm_iv(self, expiry: date, strike: float) -> float | None:
        best = None
        best_dist = None
        for row in self._greeks_chain(expiry):
            raw_strike = row.get("strikePrice") or row.get("strike") or row.get("strikeprice")
            try:
                row_strike = float(raw_strike)
            except (TypeError, ValueError):
                continue
            if row_strike > 10000:
                row_strike = row_strike / 100.0
            dist = abs(row_strike - strike)
            iv = row.get("impliedVolatility") or row.get("iv") or row.get("impliedvolatility")
            if iv is None:
                continue
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = float(iv)
        return best

    def _option_prices_near(
        self,
        expiry: date,
        spot: float,
        width: float = 1500,
    ) -> dict[tuple[float, str], float]:
        now = time.time()
        if self._chain_prices and now - self._chain_at < 30:
            return self._chain_prices
        strikes = [
            s
            for s in self.registry.available_strikes(Config.FNO_UNDERLYING, expiry)
            if abs(s - spot) <= width
        ]
        instruments = []
        lookup: dict[str, tuple[float, str]] = {}
        for strike in strikes:
            for option_type in ("CE", "PE"):
                inst = self.registry.resolve_option(
                    Config.FNO_UNDERLYING, expiry, strike, option_type
                )
                if inst is None:
                    continue
                instruments.append(inst)
                lookup[str(inst["symboltoken"])] = (float(strike), option_type)
        if not instruments:
            return {}
        batch = self.broker.get_ltp_batch(instruments)
        prices: dict[tuple[float, str], float] = {}
        for token, key in lookup.items():
            px = batch.get(token)
            if px is not None:
                prices[key] = float(px)
        if prices:
            self._chain_prices = prices
            self._chain_at = now
        return prices

    def _atm_straddle_premium(self, expiry: date, spot: float) -> float | None:
        atm = self.registry.resolve_atm_straddle(Config.FNO_UNDERLYING, expiry, spot)
        if atm is None:
            return None
        prices = self._option_prices_near(expiry, spot)
        strike = float(atm["strike"])
        call_px = prices.get((strike, "CE"))
        put_px = prices.get((strike, "PE"))
        if call_px is None:
            call_px = self.broker.get_ltp_for_instrument(atm["CE"])
        if put_px is None:
            put_px = self.broker.get_ltp_for_instrument(atm["PE"])
        if call_px is None or put_px is None:
            return None
        return float(call_px) + float(put_px)

    def _entry_context(
        self,
        strategy: FnOStrategy,
        plan,
        spot: float,
        candles_5m: pd.DataFrame | None,
    ) -> dict[str, Any]:
        session = self.now_ist().date()
        features = dict(plan.entry_features or {})
        features.setdefault("expiry_cycle_day", expiry_cycle_day(plan.expiry, session))
        features.setdefault("vix", self._india_vix())
        features.setdefault("ema_state", trend_state(candles_5m, at=self.now_ist()))
        features.setdefault(
            "atm_straddle_premium",
            self._atm_straddle_premium(plan.expiry, spot),
        )
        features.setdefault("atm_iv", self._atm_iv(plan.expiry, plan.strike or spot))
        features.setdefault("spot", spot)
        features.setdefault("strategy_key", strategy.name)
        return features

    def _orb_candles(self, strategy: PremiumOrbShortStrategy) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for pick in strategy._picks.values():
            inst = pick.get("instrument") or {}
            key = inst.get("tradingsymbol")
            if not key:
                continue
            df = self.broker.get_candles_for_instrument(
                inst, interval="FIVE_MINUTE", lookback=80
            )
            if df is not None and not df.empty:
                out[key] = df
        return out

    def _exit_time_for(self, position: OptionPosition) -> str:
        for strategy in self.strategies:
            if strategy.name == position.strategy_key or strategy.strategy_name == position.strategy_name:
                return strategy.exit_time
        return Config.FNO_EXIT_TIME

    def _combined_exit_reason(
        self,
        position: OptionPosition,
        prices: dict[str, float],
    ) -> str | None:
        stop_pct = Config.FNO_COMBINED_STOP_LOSS_PCT
        if stop_pct <= 0:
            return None
        pnl_pct = position.pnl_pct(prices)
        if pnl_pct <= -stop_pct:
            return f"combined stop ({pnl_pct:.2f}%)"
        return None

    def _group_stop(
        self,
        position: OptionPosition,
        prices: dict[str, float],
    ) -> tuple[str, str] | None:
        for group in position.groups():
            for leg in position.legs_in_group(group):
                if not leg.is_open:
                    continue
                current = prices.get(leg.leg_id)
                if current is None:
                    continue
                stop_pct = leg.stop_pct
                if stop_pct is None or stop_pct <= 0:
                    continue
                kind = (leg.stop_kind or "").lower()
                if kind == "short_rise" or (not kind and leg.side == "SHORT"):
                    if current >= leg.entry_price * (1.0 + stop_pct / 100.0):
                        return group, f"{leg.leg_id} leg stop ({stop_pct:.1f}%)"
                if kind == "long_drop" or (not kind and leg.side == "LONG"):
                    if current <= leg.entry_price * (1.0 - stop_pct / 100.0):
                        return group, f"{leg.leg_id} long stop ({stop_pct:.1f}%)"
        return None

    def _record_close(self, position: OptionPosition, result: dict[str, Any]) -> None:
        if not result.get("success"):
            return
        guard = self.guards.get(position.strategy_key)
        if guard is None:
            return
        guard.record_close(position.underlying, result.get("pnl", 0.0))

    def manage_positions(self) -> None:
        now_t = self.now_ist().time()
        for position in list(self.orders.get_open_positions()):
            prices = self.orders.current_prices(position.position_id)
            if prices is None:
                continue
            exit_hhmm = self._exit_time_for(position)
            if now_t >= _parse_hhmm(exit_hhmm):
                result = self.orders.close_position(
                    position.position_id,
                    exit_reason=f"{exit_hhmm} time square-off",
                    price_overrides=prices,
                )
                self._record_close(position, result)
                continue
            combined = self._combined_exit_reason(position, prices)
            if combined is not None:
                result = self.orders.close_position(
                    position.position_id,
                    exit_reason=combined,
                    price_overrides=prices,
                )
                self._record_close(position, result)
                continue
            group_hit = self._group_stop(position, prices)
            if group_hit is None:
                continue
            group, reason = group_hit
            result = self.orders.close_group(
                position.position_id,
                group,
                exit_reason=reason,
                price_overrides=prices,
            )
            self._record_close(position, result)

    def try_entries(self) -> None:
        if self.is_past_entry_cutoff():
            return
        now = self.now_ist()
        spot_instrument = self._spot_instrument()
        if not spot_instrument:
            logger.warning("No spot instrument found for %s", Config.FNO_UNDERLYING)
            return
        spot_price = self.broker.get_ltp_for_instrument(spot_instrument)
        if spot_price is None:
            logger.warning("Could not fetch spot LTP for %s", Config.FNO_UNDERLYING)
            return
        candles_5m = self._refresh_spot_5m()
        prior_vix = None

        for strategy in self.strategies:
            slots = self._slots_for(strategy)
            if not strategy.should_consider(now, slots):
                continue
            guard = self.guards[strategy.name]
            if not guard.can_trade_more():
                if guard.halted:
                    logger.info("%s entries halted: %s", strategy.name, guard.halt_reason)
                continue
            if self.orders.position_count(strategy.name) >= Config.FNO_MAX_POSITIONS_PER_STRATEGY:
                continue
            if not guard.can_enter(strategy.underlying):
                continue

            option_prices = None
            option_candles = None
            expiry = strategy.select_expiry(as_of=now.date())
            needs_chain = strategy.name in {
                "ema920_option_buy",
                "premium_orb_short",
            }
            if needs_chain and expiry is not None:
                option_prices = self._option_prices_near(expiry, float(spot_price))
            if isinstance(strategy, PremiumOrbShortStrategy) and strategy._picks:
                option_candles = self._orb_candles(strategy)
            if strategy.name == "expiry_vol_strangle" and prior_vix is None:
                prior_vix = self._prior_vix()

            plan = strategy.build_entry_plan(
                float(spot_price),
                as_of=now.date(),
                now=now,
                slots_used=slots,
                candles_5m=candles_5m,
                option_prices=option_prices,
                option_candles=option_candles,
                prior_vix=prior_vix,
            )
            if plan is None:
                continue
            if not plan.leg_specs:
                slots.add(plan.slot_id or "PICK")
                logger.info("%s recorded slot %s (no legs)", strategy.name, plan.slot_id)
                continue

            features = self._entry_context(strategy, plan, float(spot_price), candles_5m)
            position_id = (
                f"{plan.strategy_name}:{plan.underlying}:"
                f"{plan.expiry:%Y%m%d}:{(plan.slot_id or now.strftime('%H:%M')).replace(':', '')}"
            )
            result = self.orders.open_position(
                strategy_name=plan.strategy_name,
                leg_specs=plan.leg_specs,
                position_id=position_id,
                entry_time_slot=plan.slot_id,
                entry_features=features,
                strategy_key=strategy.name,
            )
            if result.get("success"):
                slots.add(plan.slot_id or now.strftime("%H:%M"))
                guard.record_entry(strategy.underlying)
                if result.get("estimated_margin_required") is not None:
                    features["basket_margin"] = result.get("estimated_margin_required")
                    position = self.orders.get_position(position_id)
                    if position is not None:
                        import json

                        position.entry_features = json.dumps(features)
                        self.orders.persist()
                logger.info(
                    "Opened %s %s expiry=%s strike=%.2f slot=%s",
                    plan.strategy_name,
                    plan.underlying,
                    plan.expiry.isoformat(),
                    plan.strike,
                    plan.slot_id,
                )

    def _maybe_iv_snapshot(self) -> None:
        interval_sec = max(60, Config.FNO_IV_SNAPSHOT_MIN * 60)
        now = time.time()
        if now - self._last_iv_snap < interval_sec:
            return
        expiry = self.registry.nearest_expiry(Config.FNO_UNDERLYING, as_of=self.now_ist().date())
        if expiry is None:
            return
        try:
            from intraday_agent.learning.fno_candle_store import record_iv_snapshot

            record_iv_snapshot(
                self.broker,
                Config.FNO_UNDERLYING,
                expiry,
                as_of=self.now_ist(),
            )
            self._last_iv_snap = now
        except Exception as exc:
            logger.warning("IV snapshot failed: %s", exc)

    def _maybe_capture(self) -> None:
        if not Config.FNO_CAPTURE_ON_EXIT:
            self._captured_date = self.now_ist().date()
            return
        today = self.now_ist().date()
        if self._captured_date == today:
            return
        if self.now_ist().time() < _parse_hhmm(Config.FNO_EXIT_TIME):
            return
        if self.orders.position_count() > 0:
            return
        try:
            from intraday_agent.learning.fno_candle_store import capture_session

            result = capture_session(
                self.broker,
                today,
                registry=self.registry,
            )
            logger.info("F&O capture finished: %s", result.get("summary", result))
            self._captured_date = today
        except Exception as exc:
            logger.warning("F&O capture failed: %s", exc)
            self._captured_date = today

    def _close_all(self, reason: str, *, strategy_key: str | None = None) -> None:
        for position in list(self.orders.get_open_positions(strategy_key)):
            prices = self.orders.current_prices(position.position_id)
            result = self.orders.close_position(
                position.position_id,
                exit_reason=reason,
                price_overrides=prices,
            )
            self._record_close(position, result)

    def run_once(self) -> None:
        self._roll_day()
        if self.is_square_off_time():
            if self.orders.position_count():
                logger.info("F&O square-off time — closing remaining positions")
                self._close_all("F&O time square-off")
            self._maybe_capture()
            return

        self.manage_positions()

        for strategy in self.strategies:
            guard = self.guards[strategy.name]
            if guard.should_force_flat() and self.orders.position_count(strategy.name):
                logger.warning("%s daily loss limit — squaring that arm", strategy.name)
                self._close_all("F&O daily loss limit", strategy_key=strategy.name)

        if not self.is_past_entry_cutoff():
            self.try_entries()
        self._maybe_iv_snapshot()

    def run(self) -> None:
        names = ",".join(s.name for s in self.strategies) or "(none)"
        logger.info(
            "Starting IntradayAgentFnO [PAPER mode] strategies=%s exit=%s cutoff=%s",
            names,
            Config.FNO_EXIT_TIME,
            Config.FNO_ENTRY_CUTOFF,
        )
        while True:
            try:
                if not self.is_market_open():
                    logger.info("Market closed — sleeping 5 min")
                    time.sleep(300)
                    continue

                self.run_once()
                if self.should_idle_shutdown():
                    logger.info("F&O session complete (flat + capture) — shutting down")
                    break
                time.sleep(Config.FNO_CHECK_INTERVAL_SEC)
            except KeyboardInterrupt:
                logger.info("Stopped by user")
                if self.orders.position_count():
                    logger.warning(
                        "Open F&O positions: %s",
                        [p.position_id for p in self.orders.get_open_positions()],
                    )
                break
            except Exception as exc:
                logger.exception("F&O agent loop error: %s", exc)
                time.sleep(max(5, Config.FNO_CHECK_INTERVAL_SEC))
