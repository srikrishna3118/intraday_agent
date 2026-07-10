"""Nifty index universes and SCAN_UNIVERSE routing.

Maintenance:
  - NIFTY_50 / NIFTY_NEXT_50 / midcap lists: update on NSE index rebalance (~Mar & Sep).
  - T2_SYMBOLS: fixed 30-name research subset (sim-validated Jul 2026). Do NOT mirror
    every Nifty rebalance — update on rename/delist or Angel resolution failures only.
  - After edits: verify instruments.resolve() and refresh candle cache if needed.
"""

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

# Tier-1 research subset (5 names)
T1_SYMBOLS = ["RELIANCE", "SBIN", "TCS", "HDFCBANK", "INFY"]

# Tier-2 research subset (30 liquid Nifty names — legacy Phase B window)
T2_SYMBOLS = T1_SYMBOLS + [
    "ICICIBANK", "KOTAKBANK", "AXISBANK", "LT", "ITC", "BHARTIARTL", "HINDUNILVR",
    "MARUTI", "TATASTEEL", "TATACONSUM", "WIPRO", "HCLTECH", "TECHM", "SUNPHARMA",
    "NTPC", "ONGC", "POWERGRID", "TITAN", "M&M", "BAJFINANCE", "ASIANPAINT",
    "ULTRACEMCO", "JSWSTEEL", "INDUSINDBK", "COALINDIA",
]

# Nifty Next 50 — static list; edit when index rebalances (SCAN_UNIVERSE=nifty100)
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
    "LTM",  # LTIMindtree (renamed from LTIM, Feb 2026)
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
    "ETERNAL",  # Zomato (renamed from ZOMATO)
    "ADANIENSOL",
    "DMART",
    "HAL",
    "JIOFIN",
    "MAXHEALTH",
    "NHPC",
    "SUZLON",
]

# Nifty Midcap 100 — static list; edit when index rebalances (SCAN_UNIVERSE=nifty200)
# Nifty 200 = Nifty 100 (50+Next50) + this list. Last verified: Jul 2026.
NIFTY_MIDCAP_100 = [
    "ABCAPITAL",
    "ABFRL",
    "AIAENG",
    "AJANTPHARM",
    "ALKEM",
    "APOLLOTYRE",
    "APLAPOLLO",
    "ASHOKLEY",
    "ASTRAL",
    "ATGL",
    "AUBANK",
    "AUROPHARMA",
    "BALKRISIND",
    "BANDHANBNK",
    "BATAINDIA",
    "BHARATFORG",
    "BLUEDART",
    "CAMS",
    "CANFINHOME",
    "CDSL",
    "CESC",
    "CGPOWER",
    "COFORGE",
    "CONCOR",
    "CROMPTON",
    "CUB",
    "CYIENT",
    "DALBHARAT",
    "DEEPAKFERT",
    "DEEPAKNTR",
    "DIXON",
    "ELGIEQUIP",
    "EMAMILTD",
    "ENGINERSIN",
    "ESCORTS",
    "EXIDEIND",
    "FEDERALBNK",
    "FLUOROCHEM",
    "FORTIS",
    "GLENMARK",
    "GNFC",
    "GODREJPROP",
    "GRINDWELL",
    "GUJENERGY",  # Gujarat Gas / Gujarat Energy (was GUJGASLTD)
    "HFCL",
    "HINDPETRO",
    "HONAUT",
    "IDFCFIRSTB",
    "IEX",
    "INDIAMART",
    "IPCALAB",
    "IRCTC",
    "JKCEMENT",
    "JSL",
    "JUBLFOOD",
    "JUBLPHARMA",  # Jubilant Pharmova (was JUBILINDS)
    "KAJARIACER",
    "KALPATARU",  # Kalpataru Power (was KALPATPOWR)
    "KANSAINER",
    "KEC",
    "KPITTECH",
    "LALPATHLAB",
    "LAURUSLABS",
    "LTTS",
    "MANKIND",
    "MARICO",
    "METROPOLIS",
    "MFSL",
    "MPHASIS",
    "NATCOPHARM",
    "OBEROIRLTY",
    "OFSS",
    "PAGEIND",
    "PGHH",
    "PHOENIXLTD",
    "PIIND",
    "POLYCAB",
    "PRESTIGE",
    "RADICO",
    "RAMCOCEM",
    "RBLBANK",
    "RELAXO",
    "ROUTE",
    "SAFARI",
    "SCHAEFFLER",
    "SOBHA",
    "SOLARINDS",
    "SUNDRMFAST",
    "SWIGGY",  # Replaces delisted ISEC (ICICI Securities, Mar 2025)
    "SUPREMEIND",
    "SUNTV",
    "SYNGENE",
    "TANLA",
    "TATACHEM",
    "TATACOMM",
    "TIINDIA",
    "TORNTPOWER",
    "TRIDENT",
    "TTKPRESTIG",
    "TVSHLTD",
]

# Legacy alias — Nifty 250 was 50+Next50+Midcap150; kept for old research bundles only.
NIFTY_MIDCAP_150 = NIFTY_MIDCAP_100 + [
    "UBL", "UTIAMC", "VGUARD", "VOLTAS", "WHIRLPOOL", "ZYDUSLIFE",
    "BIKAJI", "CAMPUS", "DELHIVERY", "ELECON", "FINEORG", "HAPPSTMNDS",
    "HBLPOWER", "HINDZINC", "JBCHEPHARM", "KALYANKJIL", "KNRCON", "LATENTVIEW",
    "MEDANTA", "NUVOCO", "OLECTRA", "POONAWALLA", "RAJESHEXPO", "SAPPHIRE",
    "SENCO", "SIGNATURE", "STARHEALTH", "SWIGGY", "TEAMLEASE", "TRITURBINE",
    "VAIBHAVGBL", "YATHARTH", "JYOTICNC", "GESHIP", "NSLNISP", "RAILVIKAS",
    "RITES", "SUVENPHAR", "TEJASNET", "WABAG", "ZEEL", "TATAELXSI", "CEATLTD",
    "AAVAS", "CREDITACC", "EMCURE", "JKPAPER", "KAYNES", "NIACL", "PREMIERENE",
    "PNBHOUSING", "RRKABEL", "SAMMAANCAP", "TBOTEK", "UCOBANK",
]


def _dedupe_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sym in symbols:
        key = sym.upper()
        if key not in seen:
            seen.add(key)
            out.append(sym)
    return out


def nifty100_symbols() -> list[str]:
    """Nifty 50 + Next 50 (deduped)."""
    return _dedupe_symbols(NIFTY_50 + NIFTY_NEXT_50)


def nifty200_symbols() -> list[str]:
    """Nifty 200 index: Nifty 100 + Midcap 100 (deduped)."""
    return _dedupe_symbols(NIFTY_50 + NIFTY_NEXT_50 + NIFTY_MIDCAP_100)


def nifty250_symbols() -> list[str]:
    """Legacy: Nifty 50 + Next 50 + extended midcap list (~250)."""
    return _dedupe_symbols(NIFTY_50 + NIFTY_NEXT_50 + NIFTY_MIDCAP_150)


def symbols_for_tier(tier: str) -> list[str]:
    """Research symbol list: t1 | t2 | t200 | t250."""
    key = tier.lower().strip()
    if key in ("t200", "nifty200"):
        return nifty200_symbols()
    if key in ("t250", "nifty250"):
        return nifty250_symbols()
    if key == "t2":
        return list(T2_SYMBOLS)
    if key == "t1":
        return list(T1_SYMBOLS)
    raise ValueError(f"Unknown research tier '{tier}'. Use: t1, t2, t200, t250")


def trading_universe() -> list[str]:
    """Return scan universe based on SCAN_UNIVERSE config."""
    if Config.SCAN_UNIVERSE in ("nifty200", "nifty250"):
        if Config.SCAN_UNIVERSE == "nifty250":
            return nifty250_symbols()
        return nifty200_symbols()
    if Config.SCAN_UNIVERSE == "nifty100":
        return nifty100_symbols()
    if Config.SCAN_UNIVERSE == "t2":
        return list(T2_SYMBOLS)
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
