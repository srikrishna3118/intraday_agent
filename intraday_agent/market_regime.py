"""India VIX and Nifty index regime filters for short entries."""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from intraday_agent.config import Config

logger = logging.getLogger(__name__)

NIFTY_INDEX = {"tradingsymbol": "Nifty 50", "symboltoken": "99926000"}
INDIA_VIX = {"tradingsymbol": "India VIX", "symboltoken": "99926017"}

INDEX_INSTRUMENTS = {
    "NIFTY": NIFTY_INDEX,
    "INDIAVIX": INDIA_VIX,
}


class MarketRegime:
    """Gate short entries when VIX is elevated or Nifty is above its EMA."""

    def __init__(
        self,
        nifty_df: pd.DataFrame | None = None,
        vix_df: pd.DataFrame | None = None,
    ):
        self._nifty = self._prepare_nifty(nifty_df) if nifty_df is not None else None
        self._vix = self._prepare_vix(vix_df) if vix_df is not None else None

    @classmethod
    def from_broker(cls, broker, lookback: int | None = None) -> MarketRegime:
        # Keep index candle requests small — VIX needs only a recent value and the
        # Nifty EMA(20) needs ~5x its period. Large lookbacks waste getCandleData quota.
        lookback = lookback or Config.CANDLE_LOOKBACK
        nifty_df = broker.get_index_candles("NIFTY", lookback=lookback)
        vix_df = broker.get_index_candles("INDIAVIX", lookback=lookback)
        if nifty_df is None or nifty_df.empty:
            logger.warning("No Nifty index candles — regime Nifty filter inactive")
        if vix_df is None or vix_df.empty:
            logger.warning("No India VIX candles — regime VIX filter inactive")
        return cls(nifty_df, vix_df)

    @classmethod
    def from_feed(cls, feed, lookback: int | None = None) -> MarketRegime:
        """Build regime from an external feed (e.g. Yahoo) — no Angel quota used."""
        lookback = lookback or Config.CANDLE_LOOKBACK
        nifty_df = feed.fetch("NIFTY", lookback=lookback)
        vix_df = feed.fetch("INDIAVIX", lookback=lookback)
        if nifty_df is None or nifty_df.empty:
            logger.warning("No Nifty index candles (feed) — regime Nifty filter inactive")
        if vix_df is None or vix_df.empty:
            logger.warning("No India VIX candles (feed) — regime VIX filter inactive")
        return cls(nifty_df, vix_df)

    @staticmethod
    def _prepare_nifty(df: pd.DataFrame | None) -> pd.DataFrame | None:
        if df is None or df.empty:
            return None
        out = df.sort_values("datetime").reset_index(drop=True)
        period = Config.NIFTY_EMA_PERIOD
        out["ema"] = out["close"].ewm(span=period, adjust=False).mean()
        return out

    @staticmethod
    def _prepare_vix(df: pd.DataFrame | None) -> pd.DataFrame | None:
        if df is None or df.empty:
            return None
        return df.sort_values("datetime").reset_index(drop=True)

    @staticmethod
    def _normalize_ts(dt: datetime, ref: pd.Series) -> pd.Timestamp:
        if hasattr(dt, "to_pydatetime"):
            dt = dt.to_pydatetime()
        ts = pd.Timestamp(dt)
        sample = ref.iloc[0] if len(ref) else ts
        if getattr(sample, "tzinfo", None) is not None:
            if ts.tzinfo is None:
                ts = ts.tz_localize(sample.tzinfo)
            else:
                ts = ts.tz_convert(sample.tzinfo)
        elif ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        return ts

    def _value_at(self, df: pd.DataFrame | None, dt: datetime, column: str) -> float | None:
        if df is None or df.empty:
            return None
        ts = self._normalize_ts(dt, df["datetime"])
        idx = int(df["datetime"].searchsorted(ts, side="right")) - 1
        if idx < 0:
            return None
        val = df.iloc[idx][column]
        return None if pd.isna(val) else float(val)

    def snapshot(self, dt: datetime | None = None) -> dict[str, float | None]:
        dt = dt or datetime.now()
        return {
            "vix": self._value_at(self._vix, dt, "close"),
            "nifty_close": self._value_at(self._nifty, dt, "close"),
            "nifty_ema": self._value_at(self._nifty, dt, "ema"),
        }

    def block_reason(self, side: str, dt: datetime) -> str | None:
        if side != "SHORT" or not Config.REGIME_FILTER_ENABLED:
            return None

        snap = self.snapshot(dt)

        if Config.VIX_MAX > 0:
            vix = snap["vix"]
            if vix is not None and vix > Config.VIX_MAX:
                return f"VIX {vix:.1f} > max {Config.VIX_MAX}"

        if Config.NIFTY_REGIME_ENABLED:
            close = snap["nifty_close"]
            ema = snap["nifty_ema"]
            if close is not None and ema is not None and close >= ema:
                return (
                    f"NIFTY {close:.0f} >= EMA{Config.NIFTY_EMA_PERIOD} "
                    f"{ema:.0f} (not bearish)"
                )
        return None

    def allows_side(self, side: str, dt: datetime) -> bool:
        return self.block_reason(side, dt) is None
