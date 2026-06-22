"""NSE charting OHLCV — screener data only (not for live orders)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import requests

from intraday_agent.config import Config
from intraday_agent.instruments import resolve_symbol

logger = logging.getLogger(__name__)

_ANGEL_TO_OPENCHART = {
    "ONE_MINUTE": "1m",
    "FIVE_MINUTE": "5m",
    "FIFTEEN_MINUTE": "15m",
    "THIRTY_MINUTE": "30m",
    "ONE_HOUR": "1h",
    "ONE_DAY": "1d",
}

_INTERVAL_MAP = {
    "1m": (1, "I"),
    "5m": (5, "I"),
    "10m": (10, "I"),
    "15m": (15, "I"),
    "30m": (30, "I"),
    "1h": (60, "I"),
    "1d": (1, "D"),
    "1w": (1, "W"),
    "1M": (1, "M"),
}

_COOKIE_URLS = (
    "https://www.nseindia.com/market-data/live-equity-market",
    "https://charting.nseindia.com/",
)

_HISTORICAL_URL = "https://charting.nseindia.com/v1/charts/symbolHistoricalData"

_PROBE_SYMBOL = "RELIANCE"


class OpenChartFeed:
    """Fetch historical candles from NSE charting API."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://charting.nseindia.com",
            "Referer": "https://charting.nseindia.com/",
        })
        self._bootstrap_cookies()
        self._available = self._probe()

    def available(self) -> bool:
        return self._available

    def _bootstrap_cookies(self) -> None:
        for url in _COOKIE_URLS:
            try:
                self._session.get(url, timeout=15)
            except Exception as exc:
                logger.debug("OpenChart cookie warmup skip %s: %s", url, exc)

    @staticmethod
    def _interval() -> str:
        mapped = _ANGEL_TO_OPENCHART.get(Config.CANDLE_INTERVAL.upper())
        if not mapped:
            logger.warning(
                "CANDLE_INTERVAL %s not mapped for OpenChart — using 15m",
                Config.CANDLE_INTERVAL,
            )
            return "15m"
        return mapped

    def _fetch_raw(
        self,
        token: str,
        tradingsymbol: str,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> pd.DataFrame | None:
        time_interval, chart_type = _INTERVAL_MAP.get(interval, (15, "I"))
        payload = {
            "token": str(token),
            "fromDate": int(start.timestamp()),
            "toDate": int(end.timestamp()),
            "symbol": tradingsymbol,
            "symbolType": "Equity",
            "chartType": chart_type,
            "timeInterval": time_interval,
        }
        try:
            response = self._session.post(
                _HISTORICAL_URL, json=payload, timeout=15,
            )
            response.raise_for_status()
            result = response.json()
        except Exception as exc:
            logger.debug("OpenChart HTTP error for %s: %s", tradingsymbol, exc)
            return None

        if not result.get("status") or not result.get("data"):
            return None

        rows = result["data"]
        df = pd.DataFrame(rows)
        df = df.rename(columns={
            "time": "Timestamp",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        })
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], unit="ms", utc=True)
        df["Timestamp"] = df["Timestamp"].dt.tz_localize(None)
        if interval in ("1m", "5m", "10m", "15m", "30m", "1h"):
            cutoff = pd.Timestamp("15:29:59").time()
            df = df[df["Timestamp"].dt.time <= cutoff]
        return df.set_index("Timestamp")

    @staticmethod
    def _to_agent_df(raw: pd.DataFrame, lookback: int) -> pd.DataFrame:
        out = raw.reset_index()
        rename = {
            "Timestamp": "datetime",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
        out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
        for col in ("open", "high", "low", "close", "volume"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        out["datetime"] = pd.to_datetime(out["datetime"])
        out = out.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
        return out.tail(lookback).reset_index(drop=True)

    def _probe(self) -> bool:
        """One-shot health check — avoids hammering NSE when blocked."""
        inst = resolve_symbol(_PROBE_SYMBOL)
        if not inst:
            logger.warning("OpenChart probe skipped — cannot resolve %s", _PROBE_SYMBOL)
            return False
        end = datetime.now()
        start = end - timedelta(days=5)
        raw = self._fetch_raw(
            inst["symboltoken"],
            inst["tradingsymbol"],
            start,
            end,
            self._interval(),
        )
        if raw is not None and not raw.empty:
            logger.info("OpenChart probe OK (%s, %d bars)", _PROBE_SYMBOL, len(raw))
            return True
        logger.warning(
            "OpenChart unavailable from this network (NSE charting returned no data) — "
            "screener will use fallback=%s only",
            Config.SCREENER_OPENCHART_FALLBACK,
        )
        return False

    def fetch(self, symbol: str, lookback: int | None = None) -> pd.DataFrame | None:
        """Return OHLCV in Angel broker format (datetime + lowercase OHLCV)."""
        if not self._available:
            return None

        lookback = lookback or Config.CANDLE_LOOKBACK
        inst = resolve_symbol(symbol)
        if not inst:
            logger.warning("OpenChart skip — unknown symbol %s", symbol)
            return None

        end = datetime.now()
        days_back = max(3, (lookback // 20) + 2)
        start = end - timedelta(days=days_back)
        interval = self._interval()

        raw = self._fetch_raw(
            inst["symboltoken"],
            inst["tradingsymbol"],
            start,
            end,
            interval,
        )
        if raw is None or raw.empty:
            logger.debug("OpenChart returned no rows for %s", symbol)
            return None

        df = self._to_agent_df(raw, lookback)
        return df if not df.empty else None
