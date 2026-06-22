"""Local parquet cache for historical OHLCV candles."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from intraday_agent.config import Config
from intraday_agent.market_regime import INDEX_INSTRUMENTS

if TYPE_CHECKING:
    from intraday_agent.broker import AngelBroker

logger = logging.getLogger(__name__)

CANDLE_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]


def _normalize_key(symbol: str) -> str:
    return symbol.upper().strip()


def _store_dir(data_source: str = "angel") -> str:
    if data_source == "yahoo":
        return os.path.join(Config.CANDLE_STORE_DIR, "yahoo")
    return Config.CANDLE_STORE_DIR


def _parquet_path(symbol: str, interval: str, data_source: str = "angel") -> str:
    key = _normalize_key(symbol)
    interval = interval.upper().strip()
    store = _store_dir(data_source)
    os.makedirs(store, exist_ok=True)
    return os.path.join(store, f"{key}_{interval}.parquet")


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df[CANDLE_COLUMNS].copy()
    out["datetime"] = pd.to_datetime(out["datetime"], utc=True).dt.tz_localize(None)
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["datetime", "close"])
    out = out.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
    return out.reset_index(drop=True)


def load(symbol: str, interval: str | None = None, data_source: str = "angel") -> pd.DataFrame | None:
    """Read cached candles for symbol or index key (NIFTY, INDIAVIX)."""
    interval = interval or Config.CANDLE_INTERVAL
    path = _parquet_path(symbol, interval, data_source)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        return _normalize_df(df)
    except Exception as exc:
        logger.warning("Failed to read candle cache %s: %s", path, exc)
        return None


def save(symbol: str, interval: str, df: pd.DataFrame, data_source: str = "angel") -> pd.DataFrame:
    """Merge with existing cache, dedupe on datetime, write atomically."""
    interval = interval or Config.CANDLE_INTERVAL
    incoming = _normalize_df(df)
    existing = load(symbol, interval, data_source=data_source)
    if existing is not None and not existing.empty:
        merged = pd.concat([existing, incoming], ignore_index=True)
        merged = _normalize_df(merged)
    else:
        merged = incoming

    path = _parquet_path(symbol, interval, data_source)
    tmp = f"{path}.tmp"
    merged.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return merged


def coverage(
    symbol: str,
    interval: str | None = None,
    data_source: str = "angel",
) -> tuple[datetime | None, datetime | None, int]:
    df = load(symbol, interval, data_source=data_source)
    if df is None or df.empty:
        return None, None, 0
    return (
        pd.Timestamp(df["datetime"].iloc[0]).to_pydatetime(),
        pd.Timestamp(df["datetime"].iloc[-1]).to_pydatetime(),
        len(df),
    )


def _slice_window(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    mask = (df["datetime"] >= pd.Timestamp(start)) & (df["datetime"] <= pd.Timestamp(end))
    return df.loc[mask].reset_index(drop=True)


def _is_fresh(max_dt: datetime, max_age_hours: int) -> bool:
    if max_age_hours <= 0:
        return True
    age = datetime.now() - max_dt.replace(tzinfo=None) if max_dt.tzinfo else datetime.now() - max_dt
    return age <= timedelta(hours=max_age_hours)


def _fetch_from_broker(
    broker: AngelBroker,
    symbol: str,
    from_dt: datetime,
    to_dt: datetime,
    interval: str,
) -> pd.DataFrame | None:
    key = _normalize_key(symbol)
    if key in INDEX_INSTRUMENTS:
        return broker.get_index_candles_range(key, from_dt, to_dt, interval=interval)
    return broker.get_candles_range_for_symbol(key, from_dt, to_dt, interval=interval)


def get_or_fetch(
    broker: AngelBroker,
    symbol: str,
    days: int,
    interval: str | None = None,
    max_age_hours: int | None = None,
    sleep_sec: float | None = None,
) -> pd.DataFrame | None:
    """Return candles covering the last ``days`` calendar days, using cache when possible."""
    interval = interval or Config.CANDLE_INTERVAL
    max_age_hours = Config.CANDLE_STORE_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    sleep_sec = Config.SCREENER_DELAY_SEC if sleep_sec is None else sleep_sec

    end = datetime.now()
    start = end - timedelta(days=days)
    cached = load(symbol, interval)

    if cached is not None and not cached.empty:
        cmin = pd.Timestamp(cached["datetime"].iloc[0]).to_pydatetime()
        cmax = pd.Timestamp(cached["datetime"].iloc[-1]).to_pydatetime()
        covers_start = cmin <= start + timedelta(days=2)
        fresh = _is_fresh(cmax, max_age_hours)
        if covers_start and fresh:
            logger.debug("Candle cache hit for %s (%d rows)", symbol, len(cached))
            return _slice_window(cached, start, end)

    # Fetch missing ranges
    merged = cached if cached is not None else pd.DataFrame(columns=CANDLE_COLUMNS)
    fetch_start = start
    if not merged.empty:
        cmin = pd.Timestamp(merged["datetime"].iloc[0]).to_pydatetime()
        cmax = pd.Timestamp(merged["datetime"].iloc[-1]).to_pydatetime()
        if cmin > start + timedelta(days=1):
            fetch_start = start
        elif cmax < end - timedelta(hours=1):
            fetch_start = cmax - timedelta(days=1)
        elif not _is_fresh(cmax, max_age_hours):
            fetch_start = cmax - timedelta(days=3)
        else:
            return _slice_window(merged, start, end)

    chunk_days = Config.CANDLE_HISTORY_CHUNK_DAYS
    cursor = fetch_start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        if sleep_sec > 0 and cursor > fetch_start:
            time.sleep(sleep_sec)
        logger.info("Fetching %s candles %s → %s", symbol, cursor.date(), chunk_end.date())
        chunk = _fetch_from_broker(broker, symbol, cursor, chunk_end, interval)
        if chunk is not None and not chunk.empty:
            merged = save(symbol, interval, chunk)
        cursor = chunk_end + timedelta(minutes=1)

    if merged.empty:
        return None
    return _slice_window(merged, start, end)


def prefetch_symbols(
    broker: AngelBroker,
    symbols: list[str],
    days: int,
    interval: str | None = None,
    sleep_sec: float | None = None,
) -> dict[str, tuple[datetime | None, datetime | None, int]]:
    """Populate cache for each symbol; return coverage summary."""
    summary: dict[str, tuple[datetime | None, datetime | None, int]] = {}
    for i, symbol in enumerate(symbols):
        if i > 0 and (sleep_sec or Config.SCREENER_DELAY_SEC) > 0:
            time.sleep(sleep_sec or Config.SCREENER_DELAY_SEC)
        get_or_fetch(broker, symbol, days, interval=interval, max_age_hours=0)
        summary[_normalize_key(symbol)] = coverage(symbol, interval)
    return summary


_yahoo_feed = None


def _get_yahoo_feed():
    global _yahoo_feed
    if _yahoo_feed is None:
        from intraday_agent.market_data.yahoo_feed import YahooFeed

        _yahoo_feed = YahooFeed()
    return _yahoo_feed


def get_or_fetch_yahoo(
    symbol: str,
    days: int,
    interval: str | None = None,
    max_age_hours: int | None = None,
) -> pd.DataFrame | None:
    """Fetch from Yahoo Finance, persist under data/candles/yahoo/, return window."""
    interval = interval or Config.CANDLE_INTERVAL
    max_age_hours = Config.CANDLE_STORE_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    end = datetime.now()
    start = end - timedelta(days=days)

    cached = load(symbol, interval, data_source="yahoo")
    if cached is not None and not cached.empty:
        cmax = pd.Timestamp(cached["datetime"].iloc[-1]).to_pydatetime()
        if _is_fresh(cmax, max_age_hours):
            return _slice_window(cached, start, end)

    feed = _get_yahoo_feed()
    if not feed.available():
        logger.warning("Yahoo feed unavailable for %s", symbol)
        return cached

    df = feed.fetch_for_days(symbol, days)
    if df is None or df.empty:
        return cached
    merged = save(symbol, interval, df, data_source="yahoo")
    return _slice_window(merged, start, end)


def prefetch_symbols_yahoo(
    symbols: list[str],
    days: int,
    interval: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Batch-fetch via Yahoo and persist; returns {symbol: df} for the window."""
    interval = interval or Config.CANDLE_INTERVAL
    feed = _get_yahoo_feed()
    if not feed.available():
        logger.error("Yahoo feed unavailable — cannot prefetch")
        return {}

    effective_days = min(days, feed.max_calendar_days())
    lookback = feed.lookback_for_days(effective_days)
    end = datetime.now()
    start = end - timedelta(days=days)

    batch = feed.fetch_many(symbols, lookback=lookback)
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        key = _normalize_key(symbol)
        df = batch.get(key)
        if df is None or df.empty:
            df = feed.fetch_for_days(key, days)
        if df is not None and not df.empty:
            merged = save(key, interval, df, data_source="yahoo")
            out[key] = _slice_window(merged, start, end)
        else:
            logger.warning("Yahoo prefetch empty for %s", key)
    return out


def list_cached(
    data_source: str = "angel",
    interval: str | None = None,
) -> list[str]:
    """Return symbol keys with parquet files in the store."""
    interval = interval or Config.CANDLE_INTERVAL
    store = _store_dir(data_source)
    if not os.path.isdir(store):
        return []
    suffix = f"_{interval.upper()}.parquet"
    keys: list[str] = []
    for name in os.listdir(store):
        if name.endswith(suffix):
            keys.append(name[: -len(suffix)])
    return sorted(keys)


def export_manifest(
    symbols: list[str] | None = None,
    *,
    data_source: str = "angel",
    interval: str | None = None,
    days: int | None = None,
    bundle_name: str | None = None,
    path: str | None = None,
) -> dict:
    """Write JSON manifest describing cached parquet coverage for offline research."""
    import json

    interval = interval or Config.CANDLE_INTERVAL
    keys = symbols or list_cached(data_source=data_source, interval=interval)
    entries: dict[str, dict] = {}
    for key in keys:
        cmin, cmax, n = coverage(key, interval, data_source=data_source)
        entries[key] = {
            "bars": n,
            "from": cmin.date().isoformat() if cmin else None,
            "to": cmax.date().isoformat() if cmax else None,
        }

    manifest = {
        "bundle": bundle_name,
        "data_source": data_source,
        "interval": interval,
        "days_requested": days,
        "store_dir": _store_dir(data_source),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "symbol_count": len(entries),
        "symbols": entries,
    }
    if path is None:
        os.makedirs(os.path.join(Config.DATA_DIR, "research"), exist_ok=True)
        suffix = f"_{bundle_name}" if bundle_name else ""
        path = os.path.join(Config.DATA_DIR, "research", f"candle_cache{suffix}.json")

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    logger.info("Candle cache manifest → %s (%d symbols)", path, len(entries))
    manifest["manifest_path"] = path
    return manifest
