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
