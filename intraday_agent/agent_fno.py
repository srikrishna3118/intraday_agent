"""Paper-first intraday NIFTY options agent loop."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, time as dtime

import pytz

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.guard import TradeGuard
from intraday_agent.instruments_fno import get_fno_registry
from intraday_agent.orders_fno import FnOOrderManager, OptionPosition
from intraday_agent.strategy_fno import TimeBasedStraddleStrategy

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def _parse_hhmm(value: str) -> dtime:
    hh, mm = value.split(":", 1)
    return dtime(int(hh), int(mm))


class IntradayAgentFnO:
    """Separate paper-first options loop built on the existing broker/guard shell."""

    def __init__(
        self,
        *,
        broker: AngelBroker | None = None,
        order_manager: FnOOrderManager | None = None,
        strategy: TimeBasedStraddleStrategy | None = None,
        guard: TradeGuard | None = None,
    ):
        Config.validate()
        self.registry = get_fno_registry()
        self.broker = broker or AngelBroker()
        if broker is None:
            self.broker.login()
            if Config.STREAM_ENABLED:
                self.broker.connect_stream()
        self.strategy = strategy or TimeBasedStraddleStrategy(self.registry)
        self.orders = order_manager or FnOOrderManager(self.broker)
        self.guard = guard or TradeGuard()
        self._entry_slots_today: set[str] = set()
        self._entry_slot_date: date | None = None

    @staticmethod
    def now_ist() -> datetime:
        return datetime.now(IST)

    def _roll_day(self) -> None:
        today = self.now_ist().date()
        if self._entry_slot_date != today:
            self._entry_slot_date = today
            self._entry_slots_today = set()

    def is_market_open(self) -> bool:
        now = self.now_ist()
        if now.weekday() >= 5:
            return False
        t = now.time()
        return dtime(9, 15) <= t <= dtime(15, 30)

    def is_square_off_time(self) -> bool:
        return self.now_ist().time() >= _parse_hhmm(Config.FNO_EXIT_TIME)

    def should_idle_shutdown(self) -> bool:
        if self.orders.position_count() > 0:
            return False
        now = self.now_ist().time()
        last_entry = max(_parse_hhmm(slot) for slot in self.strategy.entry_times)
        return now > last_entry

    def _due_entry_slot(self) -> str | None:
        self._roll_day()
        now = self.now_ist().strftime("%H:%M")
        for slot in self.strategy.entry_times:
            if slot == now and slot not in self._entry_slots_today:
                return slot
        return None

    def _spot_instrument(self) -> dict | None:
        return self.registry.resolve_underlying_spot(self.strategy.underlying)

    def _build_position_id(self, slot: str, expiry: date) -> str:
        return (
            f"{self.strategy.strategy_name}:{self.strategy.underlying}:"
            f"{expiry:%Y%m%d}:{slot.replace(':', '')}"
        )

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

    def _exit_reason(self, position: OptionPosition, prices: dict[str, float]) -> str | None:
        combined = self._combined_exit_reason(position, prices)
        if combined is not None:
            return combined
        stop_pct = Config.FNO_LEG_STOP_LOSS_PCT
        if stop_pct <= 0:
            return None
        multiple = 1.0 + (stop_pct / 100.0)
        for leg_id, leg in position.legs.items():
            if leg.side != "SHORT":
                continue
            current = prices.get(leg_id)
            if current is None:
                continue
            if current >= leg.entry_price * multiple:
                return f"{leg_id} leg stop ({stop_pct:.1f}%)"
        return None

    def manage_positions(self) -> None:
        for position in self.orders.get_open_positions():
            prices = self.orders.current_prices(position.position_id)
            if prices is None:
                continue
            reason = self._exit_reason(position, prices)
            if reason is None:
                continue
            result = self.orders.close_position(
                position.position_id,
                exit_reason=reason,
                price_overrides=prices,
            )
            if result.get("success"):
                self.guard.record_close(position.underlying, result.get("pnl", 0.0))

    def try_entries(self) -> None:
        slot = self._due_entry_slot()
        if slot is None:
            return
        if not self.guard.can_trade_more():
            if self.guard.halted:
                logger.info("F&O entries halted: %s", self.guard.halt_reason)
            return
        if self.orders.position_count() >= Config.MAX_POSITIONS:
            return
        if not self.guard.can_enter(self.strategy.underlying):
            return

        spot_instrument = self._spot_instrument()
        if not spot_instrument:
            logger.warning("No spot instrument found for %s", self.strategy.underlying)
            return
        spot_price = self.broker.get_ltp_for_instrument(spot_instrument)
        if spot_price is None:
            logger.warning("Could not fetch spot LTP for %s", self.strategy.underlying)
            return

        plan = self.strategy.build_entry_plan(spot_price, as_of=self.now_ist().date())
        if plan is None:
            logger.warning(
                "Could not build %s entry plan for %s at %.2f",
                self.strategy.strategy_name,
                self.strategy.underlying,
                spot_price,
            )
            return

        result = self.orders.open_position(
            strategy_name=plan.strategy_name,
            leg_specs=plan.leg_specs,
            position_id=self._build_position_id(slot, plan.expiry),
            entry_time_slot=slot,
        )
        if result.get("success"):
            self._entry_slots_today.add(slot)
            self.guard.record_entry(self.strategy.underlying)
            logger.info(
                "Opened %s %s expiry=%s strike=%.2f slot=%s",
                plan.strategy_name,
                plan.underlying,
                plan.expiry.isoformat(),
                plan.strike,
                slot,
            )

    def run_once(self) -> None:
        if self.is_square_off_time():
            if self.orders.position_count():
                logger.info("F&O square-off time — closing all positions")
                self._close_all("F&O time square-off")
            return

        self.manage_positions()

        if self.guard.should_force_flat() and self.orders.position_count():
            logger.warning("F&O daily loss limit — squaring off all positions")
            self._close_all("F&O daily loss limit")
            return

        self.try_entries()

    def _close_all(self, reason: str) -> None:
        for position in list(self.orders.get_open_positions()):
            prices = self.orders.current_prices(position.position_id)
            result = self.orders.close_position(
                position.position_id,
                exit_reason=reason,
                price_overrides=prices,
            )
            if result.get("success"):
                self.guard.record_close(position.underlying, result.get("pnl", 0.0))

    def run(self) -> None:
        logger.info(
            "Starting IntradayAgentFnO [PAPER mode] strategy=%s underlying=%s entry_times=%s exit=%s",
            self.strategy.strategy_name,
            self.strategy.underlying,
            ",".join(self.strategy.entry_times),
            Config.FNO_EXIT_TIME,
        )
        while True:
            try:
                if not self.is_market_open():
                    logger.info("Market closed — sleeping 5 min")
                    time.sleep(300)
                    continue

                self.run_once()
                if self.should_idle_shutdown():
                    logger.info(
                        "Past last F&O entry slot with no open positions — shutting down"
                    )
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