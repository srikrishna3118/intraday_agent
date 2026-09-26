"""Shared Angel session for equity paper + F&O paper in one process."""

from __future__ import annotations

import logging
import time

from intraday_agent.agent import IntradayAgent
from intraday_agent.agent_fno import IntradayAgentFnO
from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config

logger = logging.getLogger(__name__)


class DualAgentRunner:
    """One login, two loops: F&O every ``FNO_CHECK_INTERVAL_SEC``, equity every ``CHECK_INTERVAL``."""

    def __init__(self, broker: AngelBroker | None = None):
        Config.validate()
        if broker is None:
            self.broker = AngelBroker()
            self.broker.login()
            if Config.STREAM_ENABLED:
                self.broker.connect_stream()
        else:
            self.broker = broker
        self.equity = IntradayAgent(broker=self.broker)
        self.fno = IntradayAgentFnO(broker=self.broker)
        self._last_equity = 0.0
        self._last_fno = 0.0

    def is_market_open(self) -> bool:
        return self.equity.is_market_open() or self.fno.is_market_open()

    def should_idle_shutdown(self) -> bool:
        return self.equity.should_idle_shutdown() and self.fno.should_idle_shutdown()

    def run_once(self) -> None:
        now = time.time()
        if now - self._last_fno >= Config.FNO_CHECK_INTERVAL_SEC:
            self.fno.run_once()
            self._last_fno = now
        if now - self._last_equity >= Config.CHECK_INTERVAL:
            self.equity.run_once()
            self._last_equity = now

    def run(self) -> None:
        logger.info(
            "Starting DualAgentRunner [PAPER] equity_interval=%ss fno_interval=%ss",
            Config.CHECK_INTERVAL,
            Config.FNO_CHECK_INTERVAL_SEC,
        )
        # First cycle always runs both paths.
        self.fno.run_once()
        self.equity.run_once()
        self._last_fno = time.time()
        self._last_equity = time.time()
        while True:
            try:
                if not self.is_market_open():
                    logger.info("Market closed — sleeping 5 min")
                    time.sleep(300)
                    continue
                self.run_once()
                if self.should_idle_shutdown():
                    logger.info("Equity and F&O both idle — shutting down")
                    break
                sleep_for = min(Config.FNO_CHECK_INTERVAL_SEC, Config.CHECK_INTERVAL, 15)
                time.sleep(max(1, sleep_for))
            except KeyboardInterrupt:
                logger.info("Stopped by user")
                break
            except Exception as exc:
                logger.exception("Dual runner error: %s", exc)
                time.sleep(5)
