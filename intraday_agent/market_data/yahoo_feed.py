"""Yahoo Finance OHLCV via yfinance — screener data only (not for live orders).

Free, no auth, works from datacenter IPs (unlike NSE charting). Supplies 15-min
NSE bars for the whole Nifty 50 in one batched request, plus index data for the
regime filter (^NSEI = Nifty 50, ^INDIAVIX = India VIX). Consumes zero Angel
getCandleData quota.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

import pandas as pd

from intraday_agent.config import Config

logger = logging.getLogger(__name__)

_ANGEL_TO_YF_INTERVAL = {
    "ONE_MINUTE": "1m",
    "FIVE_MINUTE": "5m",
    "FIFTEEN_MINUTE": "15m",
    "THIRTY_MINUTE": "30m",
    "ONE_HOUR": "60m",
    "ONE_DAY": "1d",
}

# Index keys used by the regime filter → Yahoo tickers.
_INDEX_TICKERS = {
    "NIFTY": "^NSEI",
    "INDIAVIX": "^INDIAVIX",
}

_AGENT_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]


class YahooFeed:
    """Fetch historical candles from Yahoo Finance via yfinance."""

    def __init__(self) -> None:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError(
                "yfinance is not installed — run: pip install yfinance"
            ) from exc
        self._yf = yf
        self._available = self._probe()

    def available(self) -> bool:
        return self._available

    @staticmethod
    def to_yahoo(symbol: str) -> str:
        """Map a Nifty symbol or index key to a Yahoo ticker."""
        key = symbol.upper().strip()
        if key in _INDEX_TICKERS:
            return _INDEX_TICKERS[key]
        return f"{key}.NS"

    @classmethod
    def _interval(cls) -> str:
        mapped = _ANGEL_TO_YF_INTERVAL.get(Config.CANDLE_INTERVAL.upper())
        if not mapped:
            logger.warning(
                "CANDLE_INTERVAL %s not mapped for Yahoo — using 15m",
                Config.CANDLE_INTERVAL,
            )
            return "15m"
        return mapped

    @staticmethod
    def _period_for(lookback: int, interval: str) -> str:
        """Pick a Yahoo period string covering `lookback` bars of `interval`."""
        bars_per_day = {
            "1m": 375, "5m": 75, "15m": 25, "30m": 13, "60m": 7, "1d": 1,
        }.get(interval, 25)
        days = max(5, math.ceil(lookback / bars_per_day) + 2)
        # Yahoo caps intraday history (e.g. 60d for 15m, 7d for 1m).
        if interval == "1m":
            days = min(days, 7)
        elif interval in ("5m", "15m", "30m", "60m"):
            days = min(days, 59)
        return f"{days}d"

    @classmethod
    def max_calendar_days(cls) -> int:
        """Max calendar days Yahoo returns for the configured CANDLE_INTERVAL."""
        interval = cls._interval()
        if interval == "1m":
            return 7
        if interval in ("5m", "15m", "30m", "60m"):
            return 59
        return 365

    @classmethod
    def lookback_for_days(cls, days: int) -> int:
        interval = cls._interval()
        bars_per_day = {
            "1m": 375, "5m": 75, "15m": 25, "30m": 13, "60m": 7, "1d": 1,
        }.get(interval, 25)
        return max(Config.CANDLE_LOOKBACK, days * bars_per_day)

    def _normalize(
        self, raw: pd.DataFrame, lookback: int | None = None,
    ) -> pd.DataFrame | None:
        if raw is None or raw.empty:
            return None
        out = raw.reset_index()
        ts_col = "Datetime" if "Datetime" in out.columns else "Date"
        rename = {
            ts_col: "datetime",
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        }
        out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
        if "datetime" not in out.columns:
            return None
        dt = pd.to_datetime(out["datetime"], errors="coerce")
        try:
            if dt.dt.tz is not None:
                dt = dt.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
        except (AttributeError, TypeError):
            pass
        out["datetime"] = dt
        for col in ("open", "high", "low", "close", "volume"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        out = out[[c for c in _AGENT_COLUMNS if c in out.columns]]
        out = out.dropna(subset=["datetime", "close"])
        out = out.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
        if out.empty:
            return None
        if lookback is not None:
            out = out.tail(lookback)
        return out.reset_index(drop=True)

    def _download(self, tickers: list[str], interval: str, period: str):
        return self._yf.download(
            " ".join(tickers),
            period=period,
            interval=interval,
            group_by="ticker",
            progress=False,
            auto_adjust=False,
            threads=True,
        )

    def _probe(self) -> bool:
        try:
            df = self._download(["RELIANCE.NS"], "15m", "5d")
        except Exception as exc:
            logger.warning("Yahoo probe error: %s", exc)
            return False
        ok = df is not None and not df.empty
        if ok:
            logger.info("Yahoo feed probe OK")
        else:
            logger.warning("Yahoo feed unavailable (empty probe response)")
        return ok

    def fetch_many(
        self, symbols: list[str], lookback: int | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Batch-fetch many symbols in one request. Returns {symbol: agent_df}."""
        if not self._available or not symbols:
            return {}
        lookback = lookback or Config.CANDLE_LOOKBACK
        interval = self._interval()
        period = self._period_for(lookback, interval)
        ticker_map = {self.to_yahoo(s): s for s in symbols}
        try:
            raw = self._download(list(ticker_map), interval, period)
        except Exception as exc:
            logger.warning("Yahoo batch download failed: %s", exc)
            return {}
        if raw is None or raw.empty:
            return {}

        result: dict[str, pd.DataFrame] = {}
        multi = isinstance(raw.columns, pd.MultiIndex)
        for ticker, symbol in ticker_map.items():
            try:
                sub = raw[ticker] if multi else raw
            except KeyError:
                continue
            df = self._normalize(sub, lookback)
            if df is not None and not df.empty:
                result[symbol] = df
        return result

    def fetch(self, symbol: str, lookback: int | None = None) -> pd.DataFrame | None:
        """Single-symbol fetch (used for indices / fallback)."""
        if not self._available:
            return None
        lookback = lookback or Config.CANDLE_LOOKBACK
        interval = self._interval()
        period = self._period_for(lookback, interval)
        ticker = self.to_yahoo(symbol)
        try:
            raw = self._download([ticker], interval, period)
        except Exception as exc:
            logger.warning("Yahoo fetch failed for %s: %s", symbol, exc)
            return None
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            try:
                raw = raw[ticker]
            except KeyError:
                return None
        return self._normalize(raw, lookback)

    def fetch_for_days(self, symbol: str, days: int) -> pd.DataFrame | None:
        """Fetch up to ``days`` calendar days (capped by Yahoo intraday limits)."""
        if not self._available:
            return None
        effective_days = min(days, self.max_calendar_days())
        if effective_days < days:
            logger.info(
                "Yahoo %s capped at %dd (requested %dd) for interval %s",
                symbol,
                effective_days,
                days,
                self._interval(),
            )
        lookback = self.lookback_for_days(effective_days)
        return self.fetch(symbol, lookback=lookback)
