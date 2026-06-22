"""Angel One SmartAPI broker wrapper."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pyotp
from SmartApi import SmartConnect

from intraday_agent.config import Config
from intraday_agent.instruments import resolve_symbol

logger = logging.getLogger(__name__)


class AngelBroker:
    """Login, market data, and order placement via Angel SmartAPI."""

    def __init__(self):
        self.api_key = Config.ANGEL_API_KEY
        self.client_id = Config.ANGEL_CLIENT_ID
        self.password = Config.ANGEL_PASSWORD
        self.totp_secret = Config.ANGEL_TOTP_SECRET
        self.smart_api: SmartConnect | None = None
        self.refresh_token: str | None = None
        self._candle_pause_until: float = 0.0
        self._rate_limit_streak: int = 0

    @property
    def rate_limit_streak(self) -> int:
        return self._rate_limit_streak

    def is_candle_paused(self) -> bool:
        return time.time() < self._candle_pause_until

    def candle_pause_remaining(self) -> float:
        return max(0.0, self._candle_pause_until - time.time())

    def _pause_candles(self, seconds: float | None = None) -> None:
        self._rate_limit_streak += 1
        if seconds is None:
            threshold = Config.API_RECOVERY_STREAK_THRESHOLD
            if threshold > 0 and self._rate_limit_streak >= threshold:
                # Sticky penalty: back right off so Angel's cooldown can clear.
                seconds = Config.API_RECOVERY_PAUSE_SEC
            else:
                # Escalate 1x, 2x, 4x ... up to the max.
                base = Config.API_RATE_LIMIT_PAUSE_SEC
                seconds = min(
                    Config.API_RATE_LIMIT_PAUSE_MAX,
                    base * (2 ** (self._rate_limit_streak - 1)),
                )
        until = time.time() + seconds
        if until > self._candle_pause_until:
            self._candle_pause_until = until
            threshold = Config.API_RECOVERY_STREAK_THRESHOLD
            if threshold > 0 and self._rate_limit_streak >= threshold:
                logger.warning(
                    "Extended API recovery — no candle requests for %.0fs (streak %d)",
                    seconds,
                    self._rate_limit_streak,
                )
            else:
                logger.warning(
                    "Candle API paused for %.0fs (rate limit #%d)",
                    seconds,
                    self._rate_limit_streak,
                )

    def mark_candle_api_healthy(self) -> None:
        """Reset rate-limit streak after a full successful screener scan."""
        self._rate_limit_streak = 0

    def probe_candle_api(self, symbol: str = "RELIANCE") -> bool:
        """Single-symbol health check before a full Nifty 50 scan."""
        if self.is_candle_paused():
            return False
        df = self.get_candles_for_symbol(symbol, lookback=30)
        return df is not None and not df.empty and not self.is_candle_paused()

    def _totp(self) -> str:
        return pyotp.TOTP(self.totp_secret).now()

    def login(self) -> bool:
        try:
            self.smart_api = SmartConnect(api_key=self.api_key)
            session = self.smart_api.generateSession(
                clientCode=self.client_id,
                password=self.password,
                totp=self._totp(),
            )
            if not session.get("status"):
                logger.error("Login failed: %s", session.get("message"))
                return False
            self.refresh_token = session["data"]["refreshToken"]
            logger.info("Logged in to Angel One as %s", self.client_id)
            return True
        except Exception as exc:
            logger.error("Login error: %s", exc)
            raise

    def ensure_session(self) -> None:
        if not self.smart_api:
            self.login()

    def get_candles(
        self,
        symboltoken: str,
        exchange: str = Config.EXCHANGE_NSE,
        interval: str | None = None,
        lookback: int | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> pd.DataFrame | None:
        """Fetch OHLCV candles as a DataFrame."""
        self.ensure_session()
        interval = interval or Config.CANDLE_INTERVAL

        if from_date is not None and to_date is not None:
            return self._fetch_candle_range(
                symboltoken, from_date, to_date, exchange, interval,
            )

        lookback = lookback or Config.CANDLE_LOOKBACK
        to_date = datetime.now()
        # 15-min bars: ~6.5h session => ~26 bars/day; lookback 100 => ~4 days
        days_back = max(3, (lookback // 20) + 2)
        from_date = to_date - timedelta(days=days_back)
        df = self._fetch_candle_range(symboltoken, from_date, to_date, exchange, interval)
        if df is None or df.empty:
            return df
        return df.tail(lookback)

    def _fetch_candle_range(
        self,
        symboltoken: str,
        from_date: datetime,
        to_date: datetime,
        exchange: str,
        interval: str,
    ) -> pd.DataFrame | None:
        if self.is_candle_paused():
            return None

        params = {
            "exchange": exchange,
            "symboltoken": symboltoken,
            "interval": interval,
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }

        try:
            response = self._get_candle_response(params, symboltoken)
            if response is None:
                return None
            if not response.get("status"):
                logger.warning("No candle data for token %s: %s", symboltoken, response)
                return None

            rows = response.get("data") or []
            if not rows:
                return None

            df = pd.DataFrame(
                rows,
                columns=["datetime", "open", "high", "low", "close", "volume"],
            )
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.sort_values("datetime").reset_index(drop=True)
            if not df.empty:
                self.mark_candle_api_healthy()
            return df
        except Exception as exc:
            logger.error("getCandleData failed for %s: %s", symboltoken, exc)
            return None

    def _get_candle_response(
        self, params: dict[str, Any], symboltoken: str,
    ) -> dict[str, Any] | None:
        """Call getCandleData; on rate limit, pause all candle fetches (no retry spam)."""
        try:
            return self.smart_api.getCandleData(params)
        except Exception as exc:
            if "exceeding access rate" in str(exc).lower():
                self._pause_candles()
                return None
            raise

    def get_candles_range(
        self,
        symboltoken: str,
        from_date: datetime,
        to_date: datetime,
        exchange: str = Config.EXCHANGE_NSE,
        interval: str | None = None,
    ) -> pd.DataFrame | None:
        """Fetch candles for an explicit date range (single API call)."""
        self.ensure_session()
        interval = interval or Config.CANDLE_INTERVAL
        return self._fetch_candle_range(symboltoken, from_date, to_date, exchange, interval)

    def get_candles_history(
        self,
        symboltoken: str,
        days: int,
        exchange: str = Config.EXCHANGE_NSE,
        interval: str | None = None,
        chunk_days: int | None = None,
        sleep_sec: float | None = None,
    ) -> pd.DataFrame | None:
        """Fetch history in large calendar chunks and merge."""
        interval = interval or Config.CANDLE_INTERVAL
        chunk_days = chunk_days or Config.CANDLE_HISTORY_CHUNK_DAYS
        sleep_sec = Config.SCREENER_DELAY_SEC if sleep_sec is None else sleep_sec

        end = datetime.now()
        start = end - timedelta(days=days)
        frames: list[pd.DataFrame] = []
        cursor = start
        first = True
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=chunk_days), end)
            if not first and sleep_sec > 0:
                time.sleep(sleep_sec)
            first = False
            chunk = self.get_candles_range(symboltoken, cursor, chunk_end, exchange, interval)
            if chunk is not None and not chunk.empty:
                frames.append(chunk)
            cursor = chunk_end + timedelta(minutes=1)

        if not frames:
            return None
        df = pd.concat(frames, ignore_index=True)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
        return df.reset_index(drop=True)

    def get_candles_range_for_symbol(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        **kwargs,
    ) -> pd.DataFrame | None:
        inst = resolve_symbol(symbol)
        if not inst:
            logger.warning("Unknown symbol: %s", symbol)
            return None
        return self.get_candles_range(inst["symboltoken"], from_date, to_date, **kwargs)

    def get_candles_history_for_symbol(self, symbol: str, days: int, **kwargs) -> pd.DataFrame | None:
        inst = resolve_symbol(symbol)
        if not inst:
            logger.warning("Unknown symbol: %s", symbol)
            return None
        return self.get_candles_history(inst["symboltoken"], days, **kwargs)

    def get_candles_for_symbol(self, symbol: str, **kwargs) -> pd.DataFrame | None:
        inst = resolve_symbol(symbol)
        if not inst:
            logger.warning("Unknown symbol: %s", symbol)
            return None
        return self.get_candles(inst["symboltoken"], **kwargs)

    def get_index_candles(self, index_key: str, **kwargs) -> pd.DataFrame | None:
        """Fetch OHLCV for NSE index symbols (NIFTY, INDIAVIX)."""
        from intraday_agent.market_regime import INDEX_INSTRUMENTS

        key = index_key.upper()
        inst = INDEX_INSTRUMENTS.get(key)
        if not inst:
            logger.warning("Unknown index key: %s", index_key)
            return None
        return self.get_candles(inst["symboltoken"], **kwargs)

    def get_index_candles_range(
        self,
        index_key: str,
        from_date: datetime,
        to_date: datetime,
        **kwargs,
    ) -> pd.DataFrame | None:
        from intraday_agent.market_regime import INDEX_INSTRUMENTS

        key = index_key.upper()
        inst = INDEX_INSTRUMENTS.get(key)
        if not inst:
            logger.warning("Unknown index key: %s", index_key)
            return None
        return self.get_candles_range(inst["symboltoken"], from_date, to_date, **kwargs)

    def get_index_candles_history(self, index_key: str, days: int, **kwargs) -> pd.DataFrame | None:
        from intraday_agent.market_regime import INDEX_INSTRUMENTS

        key = index_key.upper()
        inst = INDEX_INSTRUMENTS.get(key)
        if not inst:
            logger.warning("Unknown index key: %s", index_key)
            return None
        return self.get_candles_history(inst["symboltoken"], days, **kwargs)

    def get_ltp(
        self,
        tradingsymbol: str,
        symboltoken: str,
        exchange: str = Config.EXCHANGE_NSE,
    ) -> float | None:
        self.ensure_session()
        try:
            response = self.smart_api.ltpData(exchange, tradingsymbol, symboltoken)
            if response and response.get("status"):
                return float(response["data"]["ltp"])
        except Exception as exc:
            logger.error("ltpData failed for %s: %s", tradingsymbol, exc)
        return None

    def get_ltp_for_symbol(self, symbol: str) -> float | None:
        inst = resolve_symbol(symbol)
        if not inst:
            return None
        return self.get_ltp(inst["tradingsymbol"], inst["symboltoken"])

    def place_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        order_type: str = Config.ORDER_TYPE_MARKET,
        product_type: str = Config.PRODUCT_INTRADAY,
        price: float = 0,
    ) -> dict[str, Any]:
        self.ensure_session()
        inst = resolve_symbol(symbol)
        if not inst:
            return {"success": False, "message": f"Unknown symbol: {symbol}"}

        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": inst["tradingsymbol"],
            "symboltoken": inst["symboltoken"],
            "transactiontype": transaction_type.upper(),
            "exchange": Config.EXCHANGE_NSE,
            "ordertype": order_type,
            "producttype": product_type,
            "duration": "DAY",
            "price": str(price),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity),
            "triggerprice": "0",
        }

        try:
            logger.info("Placing order: %s", order_params)
            response = self.smart_api.placeOrder(order_params)
            if response and response.get("status"):
                order_id = response["data"]["orderid"]
                return {
                    "success": True,
                    "order_id": order_id,
                    "message": "Order placed",
                    "tradingsymbol": inst["tradingsymbol"],
                }
            msg = response.get("message", "Unknown error") if response else "No response"
            return {"success": False, "message": msg}
        except Exception as exc:
            logger.error("place_order error: %s", exc)
            return {"success": False, "message": str(exc)}

    def get_positions(self) -> dict | None:
        self.ensure_session()
        try:
            return self.smart_api.position()
        except Exception as exc:
            logger.error("position() error: %s", exc)
            return None

    def logout(self) -> None:
        if self.smart_api:
            try:
                self.smart_api.terminateSession(self.client_id)
            except Exception:
                pass
