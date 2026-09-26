"""Parquet store for live NFO option candles and ATM IV snapshots."""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd

from intraday_agent.config import Config
from intraday_agent.instruments_fno import FnOInstrumentRegistry, get_fno_registry
from intraday_agent.market_regime import INDEX_INSTRUMENTS

if TYPE_CHECKING:
    from intraday_agent.broker import AngelBroker

logger = logging.getLogger(__name__)

OPTION_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]
IV_COLUMNS = [
    "datetime",
    "expiry",
    "strike",
    "option_type",
    "implied_volatility",
    "delta",
    "gamma",
    "theta",
    "vega",
    "ltp",
]


def store_dir() -> str:
    path = Config.FNO_CANDLE_STORE_DIR
    os.makedirs(path, exist_ok=True)
    return path


def option_parquet_path(
    underlying: str,
    expiry: date,
    strike: float,
    option_type: str,
    interval: str = "ONE_MINUTE",
) -> str:
    folder = os.path.join(store_dir(), underlying.upper(), expiry.isoformat())
    os.makedirs(folder, exist_ok=True)
    strike_tag = str(int(strike)) if float(strike).is_integer() else str(strike)
    name = f"{strike_tag}_{option_type.upper()}_{interval.upper()}.parquet"
    return os.path.join(folder, name)


def index_parquet_path(index_key: str, session: date, interval: str = "ONE_MINUTE") -> str:
    folder = os.path.join(store_dir(), index_key.upper(), "index")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{session.isoformat()}_{interval.upper()}.parquet")


def iv_snapshot_path(underlying: str, expiry: date) -> str:
    folder = os.path.join(store_dir(), underlying.upper(), expiry.isoformat())
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "iv_snapshots.parquet")


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df[OPTION_COLUMNS].copy()
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.tz_localize(None)
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["datetime", "close"])
    return out.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last").reset_index(drop=True)


def _merge_ohlcv(path: str, incoming: pd.DataFrame) -> pd.DataFrame:
    new = _normalize_ohlcv(incoming)
    if os.path.exists(path):
        try:
            existing = _normalize_ohlcv(pd.read_parquet(path))
            new = _normalize_ohlcv(pd.concat([existing, new], ignore_index=True))
        except Exception as exc:
            logger.warning("Could not merge %s: %s", path, exc)
    tmp = f"{path}.tmp"
    new.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return new


def save_option_candles(
    underlying: str,
    expiry: date,
    strike: float,
    option_type: str,
    df: pd.DataFrame,
    interval: str = "ONE_MINUTE",
) -> pd.DataFrame:
    path = option_parquet_path(underlying, expiry, strike, option_type, interval)
    return _merge_ohlcv(path, df)


def save_index_session(
    index_key: str,
    session: date,
    df: pd.DataFrame,
    interval: str = "ONE_MINUTE",
) -> pd.DataFrame:
    path = index_parquet_path(index_key, session, interval)
    return _merge_ohlcv(path, df)


def load_option_candles(
    underlying: str,
    expiry: date,
    strike: float,
    option_type: str,
    interval: str = "ONE_MINUTE",
) -> pd.DataFrame | None:
    path = option_parquet_path(underlying, expiry, strike, option_type, interval)
    if not os.path.exists(path):
        return None
    return _normalize_ohlcv(pd.read_parquet(path))


def _row_iv(row: dict[str, Any]) -> dict[str, Any] | None:
    strike = row.get("strikePrice") or row.get("strike") or row.get("strikeprice")
    option_type = str(row.get("optionType") or row.get("optiontype") or row.get("option_type") or "")
    option_type = option_type.upper()
    if option_type.endswith("CE"):
        option_type = "CE"
    elif option_type.endswith("PE"):
        option_type = "PE"
    if option_type not in {"CE", "PE"}:
        symbol = str(row.get("tradingSymbol") or row.get("tradingsymbol") or "")
        option_type = symbol[-2:].upper() if symbol[-2:].upper() in {"CE", "PE"} else ""
    if strike is None or option_type not in {"CE", "PE"}:
        return None
    try:
        strike_f = float(strike)
    except (TypeError, ValueError):
        return None
    if strike_f > 10000:
        strike_f = strike_f / 100.0
    iv = row.get("impliedVolatility") or row.get("impliedvolatility") or row.get("iv")
    return {
        "strike": strike_f,
        "option_type": option_type,
        "implied_volatility": None if iv is None else float(iv),
        "delta": _maybe_float(row.get("delta")),
        "gamma": _maybe_float(row.get("gamma")),
        "theta": _maybe_float(row.get("theta")),
        "vega": _maybe_float(row.get("vega")),
        "ltp": _maybe_float(row.get("ltp") or row.get("lastPrice") or row.get("tradePrice")),
    }


def _maybe_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def record_iv_snapshot(
    broker: AngelBroker,
    underlying: str,
    expiry: date,
    *,
    as_of: datetime | None = None,
) -> int:
    rows = broker.get_option_greeks(underlying, expiry)
    if not rows:
        return 0
    when = as_of or datetime.now()
    parsed = []
    for row in rows:
        item = _row_iv(row)
        if item is None:
            continue
        item["datetime"] = pd.Timestamp(when.replace(tzinfo=None))
        item["expiry"] = expiry.isoformat()
        parsed.append(item)
    if not parsed:
        return 0
    incoming = pd.DataFrame(parsed)
    path = iv_snapshot_path(underlying, expiry)
    if os.path.exists(path):
        try:
            existing = pd.read_parquet(path)
            incoming = pd.concat([existing, incoming], ignore_index=True)
        except Exception as exc:
            logger.warning("Could not merge IV snapshots: %s", exc)
    incoming.to_parquet(path, index=False)
    logger.info("Wrote %d IV rows for %s %s", len(parsed), underlying, expiry)
    return len(parsed)


def _session_bounds(session: date) -> tuple[datetime, datetime] | None:
    start = datetime.combine(session, dtime(9, 15))
    end = datetime.combine(session, dtime(15, 30))
    now = datetime.now()
    if start > now:
        return None
    if end > now:
        end = now - timedelta(seconds=1)
    if end <= start:
        return None
    return start, end


def _session_range_from_index(
    broker: AngelBroker,
    session: date,
) -> tuple[float, float] | None:
    inst = INDEX_INSTRUMENTS["NIFTY"]
    bounds = _session_bounds(session)
    if bounds is None:
        return None
    start, end = bounds
    df = broker.get_candles_for_instrument(
        inst,
        interval="ONE_MINUTE",
        from_date=start,
        to_date=end,
    )
    if df is None or df.empty:
        df = broker.get_index_candles_range("NIFTY", start, end, interval="FIVE_MINUTE")
    if df is None or df.empty:
        return None
    save_index_session("NIFTY", session, df, "ONE_MINUTE" if len(df) > 80 else "FIVE_MINUTE")
    return float(df["low"].min()), float(df["high"].max())


def _sleep_delay() -> None:
    delay = max(0.0, Config.SCREENER_DELAY_SEC)
    if delay:
        time.sleep(delay)


def capture_session(
    broker: AngelBroker,
    session: date,
    *,
    registry: FnOInstrumentRegistry | None = None,
    strike_buffer: float | None = None,
    contracts: list[dict[str, Any]] | None = None,
    interval: str = "ONE_MINUTE",
) -> dict[str, Any]:
    """Idempotent 1-min capture for strikes near the session range.

    Angel only serves live contracts, so expiry-day history is best captured
    the same afternoon.
    """
    registry = registry or get_fno_registry()
    underlying = Config.FNO_UNDERLYING
    expiry = registry.nearest_expiry(underlying, as_of=session)
    buffer = Config.FNO_CAPTURE_STRIKE_BUFFER if strike_buffer is None else strike_buffer
    fetched = 0
    skipped = 0
    failed = 0

    bounds = _session_bounds(session)
    if bounds is None:
        return {
            "success": True,
            "session": session.isoformat(),
            "fetched": 0,
            "failed": 0,
            "skipped": 0,
            "summary": "session window not started yet",
        }
    start, end = bounds
    vix_inst = INDEX_INSTRUMENTS["INDIAVIX"]
    vix_df = broker.get_candles_for_instrument(
        vix_inst, interval=interval, from_date=start, to_date=end
    )
    if vix_df is not None and not vix_df.empty:
        save_index_session("INDIAVIX", session, vix_df, interval)
        fetched += 1

    session_range = _session_range_from_index(broker, session)
    if session_range is None:
        spot_inst = registry.resolve_underlying_spot(underlying)
        if spot_inst:
            ltp = broker.get_ltp_for_instrument(spot_inst)
            if ltp:
                session_range = (float(ltp), float(ltp))
    if session_range is None:
        return {"success": False, "message": "No NIFTY range for session", "fetched": fetched}

    low, high = session_range
    if contracts is None:
        strikes = [
            strike
            for strike in registry.available_strikes(underlying, expiry)  # type: ignore[arg-type]
            if (low - buffer) <= strike <= (high + buffer)
        ]
        contracts = []
        for strike in strikes:
            for option_type in ("CE", "PE"):
                inst = registry.resolve_option(underlying, expiry, strike, option_type)
                if inst:
                    contracts.append(inst)

    for inst in contracts:
        _sleep_delay()
        if broker.is_candle_paused():
            wait = broker.candle_pause_remaining() + 0.5
            logger.warning("Candle API paused — waiting %.1fs", wait)
            time.sleep(max(1.0, wait))
        df = broker.get_candles_for_instrument(
            inst, interval=interval, from_date=start, to_date=end
        )
        if df is None or df.empty:
            failed += 1
            continue
        save_option_candles(
            underlying,
            expiry or session,
            float(inst.get("strike") or 0),
            str(inst.get("option_type") or inst.get("tradingsymbol", "")[-2:]),
            df,
            interval,
        )
        fetched += 1

    try:
        if expiry is not None:
            record_iv_snapshot(broker, underlying, expiry)
    except Exception as exc:
        logger.warning("Capture IV snapshot failed: %s", exc)

    summary = {
        "success": True,
        "session": session.isoformat(),
        "expiry": expiry.isoformat() if expiry else None,
        "range": [low, high],
        "contracts": len(contracts),
        "fetched": fetched,
        "failed": failed,
        "skipped": skipped,
        "summary": f"{fetched} series saved, {failed} empty",
    }
    logger.info("F&O capture %s: %s", session, summary["summary"])
    return summary
