"""Scan Nifty 50 for RSI extremes with volume confirmation."""

from __future__ import annotations

import logging
import time

from datetime import datetime, timedelta

import pandas as pd

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.learning.candle_store import load, save
from intraday_agent.strategy import BaseStrategy, ScreenResult, Signal, get_strategy
from intraday_agent.universe import NIFTY_50, is_symbol_excluded

logger = logging.getLogger(__name__)


class Screener:
    def __init__(self, broker: AngelBroker, strategy: BaseStrategy | None = None):
        self.broker = broker
        self.strategy = strategy or get_strategy()
        self._batch_offset = 0
        self._openchart = None
        self._openchart_ok = False
        self._yahoo = None
        self._yahoo_ok = False
        self._yahoo_cache: dict[str, pd.DataFrame] = {}
        if Config.SCREENER_DATA_SOURCE == "openchart":
            from intraday_agent.market_data.openchart_feed import OpenChartFeed

            self._openchart = OpenChartFeed()
            self._openchart_ok = self._openchart.available()
            if self._openchart_ok:
                logger.info(
                    "Screener using OpenChart (fallback=%s)",
                    Config.SCREENER_OPENCHART_FALLBACK,
                )
            else:
                logger.info(
                    "Screener OpenChart disabled — using fallback=%s",
                    Config.SCREENER_OPENCHART_FALLBACK,
                )
        elif Config.SCREENER_DATA_SOURCE == "yahoo":
            from intraday_agent.market_data.yahoo_feed import YahooFeed

            self._yahoo = YahooFeed()
            self._yahoo_ok = self._yahoo.available()
            if self._yahoo_ok:
                logger.info(
                    "Screener using Yahoo Finance (fallback=%s)",
                    Config.SCREENER_OPENCHART_FALLBACK,
                )
            else:
                logger.info(
                    "Screener Yahoo disabled — using fallback=%s",
                    Config.SCREENER_OPENCHART_FALLBACK,
                )

    @staticmethod
    def _cache_fresh(df: pd.DataFrame) -> bool:
        max_age = Config.CANDLE_STORE_MAX_AGE_HOURS
        if max_age <= 0:
            return True
        last = pd.Timestamp(df["datetime"].iloc[-1]).to_pydatetime()
        age = datetime.now() - (last.replace(tzinfo=None) if last.tzinfo else last)
        return age <= timedelta(hours=max_age)

    def _load_cache(self, symbol: str) -> pd.DataFrame | None:
        df = load(symbol, Config.CANDLE_INTERVAL)
        if df is None or df.empty or not self._cache_fresh(df):
            return None
        return df.tail(Config.CANDLE_LOOKBACK).reset_index(drop=True)

    def _fallback_candles(self, symbol: str) -> pd.DataFrame | None:
        fallback = Config.SCREENER_OPENCHART_FALLBACK
        if fallback == "cache":
            return self._load_cache(symbol)
        if fallback == "angel":
            if self.broker.is_candle_paused():
                return None
            return self.broker.get_candles_for_symbol(symbol)
        return None

    def _fetch_candles(self, symbol: str) -> pd.DataFrame | None:
        source = Config.SCREENER_DATA_SOURCE

        if source == "yahoo" and self._yahoo is not None:
            if self._yahoo_ok:
                df = self._yahoo_cache.get(symbol)
                if df is None:
                    df = self._yahoo.fetch(symbol)
                if df is not None and not df.empty:
                    return df
            return self._fallback_candles(symbol)

        if source == "openchart" and self._openchart is not None and not self._openchart_ok:
            fallback = Config.SCREENER_OPENCHART_FALLBACK
            if fallback == "cache":
                cached = self._load_cache(symbol)
                if cached is not None:
                    return cached
            elif fallback == "angel":
                if self.broker.is_candle_paused():
                    return None
                return self.broker.get_candles_for_symbol(symbol)
            return None

        if source == "openchart" and self._openchart is not None and self._openchart_ok:
            df = self._openchart.fetch(symbol)
            if df is not None and not df.empty:
                return df
            fallback = Config.SCREENER_OPENCHART_FALLBACK
            if fallback == "cache":
                cached = self._load_cache(symbol)
                if cached is not None:
                    logger.debug("OpenChart miss — using cache for %s", symbol)
                    return cached
            elif fallback == "angel":
                if self.broker.is_candle_paused():
                    return None
                return self.broker.get_candles_for_symbol(symbol)
            return None

        if self.broker.is_candle_paused():
            return None
        return self.broker.get_candles_for_symbol(symbol)

    @staticmethod
    def uses_angel_candles() -> bool:
        if Config.SCREENER_DATA_SOURCE == "angel":
            return True
        return Config.SCREENER_OPENCHART_FALLBACK == "angel"

    def _external_ok(self) -> bool:
        """True when a non-Angel feed is supplying candles this scan."""
        return self._yahoo_ok or self._openchart_ok

    def _batch_symbols(self, symbols: list[str]) -> list[str]:
        # External batch feeds (Yahoo) fetch the whole universe in one request,
        # so there is no need to chunk to protect an API quota.
        if self._yahoo_ok:
            return list(symbols)
        batch_size = Config.SCREENER_BATCH_SIZE
        if batch_size <= 0 or batch_size >= len(symbols):
            return list(symbols)
        return [
            symbols[(self._batch_offset + i) % len(symbols)]
            for i in range(batch_size)
        ]

    def scan(
        self, symbols: list[str] | None = None,
    ) -> tuple[list[ScreenResult], list[ScreenResult], bool]:
        symbols = symbols or NIFTY_50
        batch = self._batch_symbols(symbols)
        oversold: list[ScreenResult] = []
        overbought: list[ScreenResult] = []
        completed = True
        rsi_high: tuple[str, float] | None = None
        rsi_low: tuple[str, float] | None = None

        if self._yahoo_ok and self._yahoo is not None:
            self._yahoo_cache = self._yahoo.fetch_many(batch)
            logger.info(
                "Yahoo batch fetched %d/%d symbols",
                len(self._yahoo_cache),
                len(batch),
            )

        if len(batch) < len(symbols):
            logger.info(
                "Screener batch %d–%d of %d symbols",
                self._batch_offset + 1,
                self._batch_offset + len(batch),
                len(symbols),
            )

        angel_screener = self.uses_angel_candles()
        for symbol in batch:
            if is_symbol_excluded(symbol):
                continue
            if angel_screener and self.broker.is_candle_paused():
                logger.info(
                    "Screener aborted — candle API paused %.0fs remaining",
                    self.broker.candle_pause_remaining(),
                )
                completed = False
                break
            try:
                df = self._fetch_candles(symbol)
                if (
                    df is None
                    and angel_screener
                    and self.broker.is_candle_paused()
                ):
                    logger.info(
                        "Screener aborted — rate limit hit on %s",
                        symbol,
                    )
                    completed = False
                    break
                if df is not None and not df.empty:
                    try:
                        save(symbol, Config.CANDLE_INTERVAL, df)
                    except Exception as exc:
                        logger.debug("Candle cache save skip %s: %s", symbol, exc)
                result = self.strategy.analyze(df, symbol)
                if result is not None:
                    sym, val = result.symbol, result.rsi
                    if rsi_high is None or val > rsi_high[1]:
                        rsi_high = (sym, val)
                    if rsi_low is None or val < rsi_low[1]:
                        rsi_low = (sym, val)
                if not result or result.signal == Signal.NONE:
                    continue
                if result.signal == Signal.BUY:
                    oversold.append(result)
                elif result.signal == Signal.SELL:
                    overbought.append(result)
            except Exception as exc:
                logger.warning("Screener skip %s: %s", symbol, exc)
            # Only pace per-symbol when each one is a separate Angel API call.
            if angel_screener:
                time.sleep(Config.SCREENER_DELAY_SEC)

        if completed and len(batch) < len(symbols):
            self._batch_offset = (self._batch_offset + len(batch)) % len(symbols)

        oversold.sort(key=lambda r: r.rsi)
        overbought.sort(key=lambda r: r.rsi, reverse=True)
        logger.info(
            "Screener: %d oversold, %d overbought candidates%s",
            len(oversold),
            len(overbought),
            "" if completed else " (incomplete — rate limited)",
        )
        if rsi_high and rsi_low:
            logger.info(
                "Scan complete: best RSI=%.1f (%s), worst=%.1f (%s)",
                rsi_high[1],
                rsi_high[0],
                rsi_low[1],
                rsi_low[0],
            )
        return oversold, overbought, completed
