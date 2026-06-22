"""Unified candle loading for research tools (Angel, Yahoo, or cache-only)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from intraday_agent.config import Config
from intraday_agent.learning.candle_store import (
    coverage,
    get_or_fetch,
    load,
    prefetch_symbols,
    prefetch_symbols_yahoo,
)
from intraday_agent.market_regime import MarketRegime

if TYPE_CHECKING:
    from intraday_agent.broker import AngelBroker

logger = logging.getLogger(__name__)

ResearchSource = Literal["angel", "yahoo", "cache"]

_VALID_SOURCES = ("angel", "yahoo", "cache")


def normalize_source(value: str | None) -> ResearchSource:
    key = (value or Config.RESEARCH_DATA_SOURCE or "angel").lower().strip()
    if key == "offline":
        key = "cache"
    if key not in _VALID_SOURCES:
        raise ValueError(f"Unknown research data source '{key}'. Choose: {', '.join(_VALID_SOURCES)}")
    return key  # type: ignore[return-value]


def _cache_backend() -> str:
    backend = (Config.CANDLE_CACHE_BACKEND or "angel").lower()
    return backend if backend in ("angel", "yahoo") else "angel"


def init_research_session(
    source: str | None = None,
) -> tuple[ResearchSource, AngelBroker | None]:
    """Resolve data source; login to Angel only when source=angel."""
    from intraday_agent.broker import AngelBroker
    from intraday_agent.instruments import get_registry

    src = normalize_source(source)
    broker: AngelBroker | None = None
    if needs_angel_login(src):
        Config.validate()
        get_registry().load()
        broker = AngelBroker()
        broker.login()
    return src, broker


def resolve_candles(
    symbol: str,
    days: int,
    source: ResearchSource,
    broker: AngelBroker | None = None,
    interval: str | None = None,
) -> pd.DataFrame | None:
    """Load candles for one symbol from cache, Yahoo, or Angel."""
    interval = interval or Config.CANDLE_INTERVAL
    if source == "cache":
        df = load(symbol, interval, data_source=_cache_backend())
        if df is None or df.empty:
            return None
        if days and days > 0:
            from datetime import datetime, timedelta

            from intraday_agent.learning.candle_store import _slice_window

            end = datetime.now()
            start = end - timedelta(days=days)
            return _slice_window(df, start, end)
        return df

    if source == "yahoo":
        from intraday_agent.learning.candle_store import get_or_fetch_yahoo

        return get_or_fetch_yahoo(symbol, days, interval=interval)

    if broker is None:
        raise ValueError("Angel broker required for source=angel")
    return get_or_fetch(broker, symbol, days, interval=interval)


def needs_angel_login(source: ResearchSource) -> bool:
    return source == "angel"


def load_symbol_dfs(
    symbols: list[str],
    days: int,
    source: ResearchSource,
    broker: AngelBroker | None = None,
    interval: str | None = None,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if source == "yahoo":
        batch = prefetch_symbols_yahoo(symbols, days, interval=interval)
        out.update(batch)
        return out

    for symbol in symbols:
        df = resolve_candles(symbol, days, source, broker=broker, interval=interval)
        if df is not None and not df.empty:
            out[symbol.upper()] = df
        else:
            logger.warning("No candles for %s (source=%s)", symbol, source)
    return out


def build_regime(
    days: int,
    source: ResearchSource,
    enabled: bool,
    broker: AngelBroker | None = None,
) -> MarketRegime | None:
    if not enabled:
        return None

    nifty = resolve_candles("NIFTY", days, source, broker=broker)
    vix = resolve_candles("INDIAVIX", days, source, broker=broker)
    return MarketRegime(nifty_df=nifty, vix_df=vix)


def prefetch_for_research(
    symbols: list[str],
    days: int,
    source: ResearchSource,
    broker: AngelBroker | None = None,
    interval: str | None = None,
) -> dict[str, tuple[datetime | None, datetime | None, int]]:
    interval = interval or Config.CANDLE_INTERVAL
    if source == "yahoo":
        prefetch_symbols_yahoo(symbols, days, interval=interval)
    elif source == "angel":
        if broker is None:
            raise ValueError("Angel broker required for prefetch source=angel")
        prefetch_symbols(broker, symbols, days, interval=interval)
    else:
        raise ValueError("prefetch does not apply to source=cache")

    data_src = "yahoo" if source == "yahoo" else "angel"
    return {s.upper(): coverage(s, interval, data_source=data_src) for s in symbols}


def source_label(source: ResearchSource) -> str:
    labels = {
        "angel": "Angel SmartAPI (parquet cache)",
        "yahoo": "Yahoo Finance (parquet cache, max ~59d on 15m)",
        "cache": f"offline parquet ({_cache_backend()} store)",
    }
    return labels.get(source, source)
