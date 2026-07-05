"""Nifty 50 universe — edit this list when index constituents change."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytz

from intraday_agent.config import Config

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.UTC

NIFTY_50 = [
    "ADANIENT",
    "ADANIPORTS",
    "APOLLOHOSP",
    "ASIANPAINT",
    "AXISBANK",
    "BAJAJ-AUTO",
    "BAJFINANCE",
    "BAJAJFINSV",
    "BPCL",
    "BHARTIARTL",
    "BRITANNIA",
    "CIPLA",
    "COALINDIA",
    "DIVISLAB",
    "DRREDDY",
    "EICHERMOT",
    "GRASIM",
    "HCLTECH",
    "HDFCBANK",
    "HDFCLIFE",
    "HEROMOTOCO",
    "HINDALCO",
    "HINDUNILVR",
    "ICICIBANK",
    "ITC",
    "INDUSINDBK",
    "INFY",
    "JSWSTEEL",
    "KOTAKBANK",
    "LT",
    "M&M",
    "MARUTI",
    "NESTLEIND",
    "NTPC",
    "ONGC",
    "POWERGRID",
    "RELIANCE",
    "SBILIFE",
    "SBIN",
    "SUNPHARMA",
    "TCS",
    "TATACONSUM",
    "TMPV",  # Tata Motors PV (renamed from TATAMOTORS, Jun 2025)
    "TATASTEEL",
    "TECHM",
    "TITAN",
    "ULTRACEMCO",
    "UPL",
    "WIPRO",
]

# Nifty Next 50 — static list; edit when index rebalances (research / SCAN_UNIVERSE=nifty100)
NIFTY_NEXT_50 = [
    "ABB",
    "AMBUJACEM",
    "BANKBARODA",
    "BEL",
    "BERGEPAINT",
    "BOSCHLTD",
    "CANBK",
    "CHOLAFIN",
    "COLPAL",
    "DABUR",
    "DLF",
    "GAIL",
    "GODREJCP",
    "HAVELLS",
    "HDFCAMC",
    "ICICIGI",
    "ICICIPRULI",
    "INDHOTEL",
    "IOC",
    "IRFC",
    "JINDALSTEL",
    "LICI",
    "LTIM",
    "LUPIN",
    "MOTHERSON",
    "MUTHOOTFIN",
    "NAUKRI",
    "NMDC",
    "PERSISTENT",
    "PETRONET",
    "PIDILITIND",
    "PNB",
    "RECLTD",
    "SHRIRAMFIN",
    "SIEMENS",
    "SRF",
    "TATAPOWER",
    "TORNTPHARM",
    "TRENT",
    "TVSMOTOR",
    "UNITDSPR",
    "VBL",
    "VEDL",
    "ZOMATO",
    "ADANIENSOL",
    "DMART",
    "HAL",
    "JIOFIN",
    "MAXHEALTH",
    "NHPC",
    "SUZLON",
]


def trading_universe() -> list[str]:
    """Return scan universe based on SCAN_UNIVERSE config."""
    if Config.SCAN_UNIVERSE == "nifty100":
        seen: set[str] = set()
        out: list[str] = []
        for sym in NIFTY_50 + NIFTY_NEXT_50:
            key = sym.upper()
            if key not in seen:
                seen.add(key)
                out.append(sym)
        return out
    return list(NIFTY_50)


def is_symbol_excluded(symbol: str) -> bool:
    return symbol.upper() in Config.EXCLUDED_SYMBOLS


def to_ist(dt: datetime | Any) -> datetime:
    """Normalize bar timestamps to IST (naive UTC for Angel cache, naive IST for Yahoo)."""
    if dt is None:
        raise ValueError("datetime required")
    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()
    if dt.tzinfo is not None:
        return dt.astimezone(IST)
    if Config.CANDLE_NAIVE_TZ.lower() == "ist":
        return IST.localize(dt)
    return UTC.localize(dt).astimezone(IST)
