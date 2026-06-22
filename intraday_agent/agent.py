"""Main intraday agent loop: screen, enter, manage, square off."""

from __future__ import annotations

import logging
import time
from datetime import datetime, time as dtime

import pytz

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.guard import TradeGuard
from intraday_agent.instruments import get_registry
from intraday_agent.learning.ranker import AdaptiveRanker
from intraday_agent.market_regime import MarketRegime
from intraday_agent.learning.meta_label import MetaLabelFilter
from intraday_agent.learning.entry_features import build_entry_features, features_to_json
from intraday_agent.orders import OrderManager
from intraday_agent.screener import Screener
from intraday_agent.strategy import Signal, entry_time_allowed, get_strategy
from intraday_agent.universe import is_symbol_excluded

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class IntradayAgent:
    def __init__(self):
        Config.validate()
        get_registry().load()
        self.broker = AngelBroker()
        self.broker.login()
        self.orders = OrderManager(self.broker)
        self.strategy = get_strategy()
        self.screener = Screener(self.broker, self.strategy)
        self.ranker = AdaptiveRanker()
        self.guard = TradeGuard()
        self.meta_filter = MetaLabelFilter()
        self.regime: MarketRegime | None = None
        self._regime_fetched_at: float = 0.0
        self._last_screener_at: float = 0.0
        self._candle_api_healthy: bool = Config.SCREENER_DATA_SOURCE == "openchart"

    @staticmethod
    def now_ist() -> datetime:
        return datetime.now(IST)

    def is_market_open(self) -> bool:
        now = self.now_ist()
        if now.weekday() >= 5:
            return False
        t = now.time()
        return dtime(9, 15) <= t <= dtime(15, 30)

    def is_square_off_time(self) -> bool:
        now = self.now_ist()
        hh, mm = Config.SQUARE_OFF_TIME.split(":")
        cutoff = dtime(int(hh), int(mm))
        return now.time() >= cutoff

    def should_idle_shutdown(self) -> bool:
        """Stop the loop after entry cutoff when there is nothing left to manage."""
        if not Config.ENTRY_CUTOFF_TIME:
            return False
        if entry_time_allowed(self.now_ist()):
            return False
        return self.orders.position_count() == 0

    def manage_positions(self) -> None:
        for pos in self.orders.get_open_positions():
            df = self.broker.get_candles_for_symbol(pos.symbol)
            ltp = self.broker.get_ltp_for_symbol(pos.symbol)
            if not ltp:
                continue

            bar_high = bar_low = ltp
            bar_close = ltp
            if df is not None and len(df):
                bar_high = float(df["high"].iloc[-1])
                bar_low = float(df["low"].iloc[-1])
                bar_close = float(df["close"].iloc[-1])

            extreme = pos.trail_extreme or pos.entry_price
            extreme = self.strategy.update_trail_extreme(
                pos.side, extreme, bar_high, bar_low,
                close=bar_close,
                atr=self.strategy.current_atr(df) if df is not None and len(df) else None,
            )
            pos.trail_extreme = extreme

            reason = self.strategy.exit_reason(
                df,
                pos.side,
                pos.entry_price,
                ltp,
                pos.entry_atr,
                trail_extreme=extreme,
            )

            if reason:
                logger.info("Closing %s: %s", pos.symbol, reason)
                res = self.orders.close_position(pos.symbol, ltp, exit_reason=reason)
                if res.get("success"):
                    self.guard.record_close(pos.symbol, res.get("pnl", 0.0))

    def _refresh_regime(self) -> MarketRegime | None:
        if not Config.REGIME_FILTER_ENABLED:
            return None
        now = time.time()
        if (
            self.regime is not None
            and (now - self._regime_fetched_at) < Config.REGIME_REFRESH_SEC
        ):
            return self.regime
        # Prefer the screener's external feed (Yahoo) — keeps regime off Angel quota.
        feed = getattr(self.screener, "_yahoo", None)
        if feed is not None and getattr(self.screener, "_yahoo_ok", False):
            self.regime = MarketRegime.from_feed(feed)
            self._regime_fetched_at = now
            return self.regime
        if self.broker.is_candle_paused():
            return self.regime
        if not self._candle_api_healthy:
            return self.regime
        self.regime = MarketRegime.from_broker(self.broker)
        self._regime_fetched_at = now
        return self.regime

    def try_entries(self) -> None:
        if not entry_time_allowed(self.now_ist()):
            logger.debug("Past entry cutoff %s — no new entries", Config.ENTRY_CUTOFF_TIME)
            return

        if (
            Screener.uses_angel_candles()
            and self.broker.is_candle_paused()
        ):
            logger.info(
                "Skipping entry scan — candle API paused %.0fs remaining (streak %d)",
                self.broker.candle_pause_remaining(),
                self.broker.rate_limit_streak,
            )
            return

        if not self.guard.can_trade_more():
            if self.guard.halted:
                logger.info("No new entries — %s", self.guard.halt_reason)
            return

        slots = Config.MAX_POSITIONS - self.orders.position_count()
        daily_left = self.guard.remaining_daily_slots()
        if daily_left is not None:
            slots = min(slots, daily_left)
        if slots <= 0:
            return

        now = time.time()
        if (now - self._last_screener_at) < Config.SCREENER_INTERVAL_SEC:
            return

        regime = self._refresh_regime()
        if regime is not None:
            block = regime.block_reason("SHORT", self.now_ist())
            if block:
                logger.info("Regime filter blocks shorts: %s", block)
                return

        oversold, overbought, completed = self.screener.scan()
        if completed:
            self._last_screener_at = now
            if Screener.uses_angel_candles():
                self._candle_api_healthy = True
                self.broker.mark_candle_api_healthy()

        def blocked(symbol: str) -> bool:
            return self.orders.has_position(symbol) or not self.guard.can_enter(symbol)

        candidates = self.ranker.rank(
            oversold,
            overbought,
            slots,
            blocked,
        )

        for side, result in candidates:
            if is_symbol_excluded(result.symbol):
                logger.debug("Skip excluded symbol %s", result.symbol)
                continue
            bar_dt = result.bar_dt or self.now_ist().replace(tzinfo=None)
            if self.meta_filter.enabled:
                take, prob = self.meta_filter.should_take(
                    side, result, self.strategy, None, regime, bar_dt,
                )
                if not take:
                    logger.info(
                        "Meta-label skip %s %s (P=%.3f < %.3f)",
                        side,
                        result.symbol,
                        prob or 0.0,
                        self.meta_filter.threshold,
                    )
                    continue

            vol_ratio = (
                result.volume / result.volume_ma if result.volume_ma > 0 else None
            )
            feats = build_entry_features(
                side, result, self.strategy, None, regime, bar_dt,
            )
            logger.info(
                "Entry signal %s %s RSI=%.1f vol=%.0f vol_ma=%.0f vwap=%s atr=%s",
                side,
                result.symbol,
                result.rsi,
                result.volume,
                result.volume_ma,
                f"{result.vwap:.2f}" if result.vwap else "n/a",
                f"{result.atr:.2f}" if result.atr else "n/a",
            )
            res = self.orders.open_position(
                result.symbol,
                side,
                result.close,
                entry_rsi=result.rsi,
                volume_ratio=vol_ratio,
                entry_atr=result.atr,
                entry_features=features_to_json(feats),
            )
            if res.get("success"):
                self.guard.record_entry(result.symbol)

    def run_once(self) -> None:
        if self.is_square_off_time():
            if self.orders.position_count():
                logger.info("Square-off time — closing all positions")
                self._close_all("EOD square-off")
            return

        self.manage_positions()

        if self.guard.should_force_flat() and self.orders.position_count():
            logger.warning("Daily loss limit — squaring off all positions")
            self._close_all("daily loss limit")
            return

        self.try_entries()

    def _close_all(self, reason: str) -> None:
        for res in self.orders.close_all(exit_reason=reason):
            if res.get("success"):
                self.guard.record_close(res.get("symbol", ""), res.get("pnl", 0.0))

    def run(self) -> None:
        mode = "LIVE" if Config.LIVE_TRADING else "PAPER"
        logger.info("Starting IntradayAgent [%s mode] strategy=%s", mode, Config.STRATEGY)
        logger.info(
            "RSI(%d) OB=%s OS=%s | Vol MA len=%d mult=%s | max_pos=%d | learning=%s",
            Config.RSI_PERIOD,
            Config.RSI_OVERBOUGHT,
            Config.RSI_OVERSOLD,
            Config.VOLUME_MA_LEN,
            Config.VOLUME_MA_MULT,
            Config.MAX_POSITIONS,
            Config.LEARNING_ENABLED,
        )
        logger.info(
            "Overtrading guards: max/day=%s max/symbol=%s cooldown=%smin loss_cooldown=%smin "
            "daily_loss=Rs %s daily_profit=Rs %s",
            Config.MAX_TRADES_PER_DAY or "off",
            Config.MAX_TRADES_PER_SYMBOL or "off",
            Config.SYMBOL_COOLDOWN_MIN,
            Config.LOSS_COOLDOWN_MIN,
            Config.MAX_DAILY_LOSS or "off",
            Config.MAX_DAILY_PROFIT or "off",
        )

        logger.info(
            "Paper stack: RSI>%s cutoff=%s excluded=%s ATR_stop=%s",
            Config.RSI_OVERBOUGHT,
            Config.ENTRY_CUTOFF_TIME,
            ",".join(sorted(Config.EXCLUDED_SYMBOLS)) or "none",
            Config.ATR_STOP_MULT,
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
                        "Past entry cutoff %s with no open positions — shutting down",
                        Config.ENTRY_CUTOFF_TIME,
                    )
                    break
                time.sleep(Config.CHECK_INTERVAL)
            except KeyboardInterrupt:
                logger.info("Stopped by user")
                if self.orders.position_count():
                    logger.warning(
                        "Open positions: %s — square off manually if needed",
                        [p.symbol for p in self.orders.get_open_positions()],
                    )
                break
            except Exception as exc:
                logger.exception("Agent loop error: %s", exc)
                time.sleep(60)
