"""Angel scrip master download, cache, and NSE equity symbol resolution."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests

from intraday_agent.config import Config

logger = logging.getLogger(__name__)

SCRIP_MASTER_URLS = (
    "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json",
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
)


class InstrumentRegistry:
    """Resolve NSE equity symbols to Angel tradingsymbol + token."""

    def __init__(self, cache_path: str | None = None):
        self.cache_path = cache_path or Config.INSTRUMENTS_CACHE
        self._by_symbol: dict[str, dict[str, Any]] = {}
        self._by_tradingsymbol: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def load(self, force_refresh: bool = False) -> None:
        if self._loaded and not force_refresh:
            return

        data = self._fetch_master(force_refresh)
        self._build_index(data)
        self._loaded = True
        logger.info("Loaded %d NSE equity instruments", len(self._by_symbol))

    def _cache_is_fresh(self) -> bool:
        if not os.path.exists(self.cache_path):
            return False
        age = time.time() - os.path.getmtime(self.cache_path)
        return age < Config.INSTRUMENTS_CACHE_MAX_AGE_HOURS * 3600

    def _fetch_master(self, force_refresh: bool) -> list[dict]:
        os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)

        if not force_refresh and self._cache_is_fresh():
            logger.info("Using cached instruments from %s", self.cache_path)
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                return json.load(fh)

        logger.info("Downloading Angel scrip master...")
        last_error: Exception | None = None
        for url in SCRIP_MASTER_URLS:
            try:
                logger.info("Trying %s", url)
                response = requests.get(url, timeout=180)
                response.raise_for_status()
                data = response.json()
                with open(self.cache_path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh)
                logger.info("Saved scrip master from %s", url)
                return data
            except Exception as exc:
                last_error = exc
                logger.warning("Scrip master fetch failed for %s: %s", url, exc)

        if os.path.exists(self.cache_path):
            logger.warning("Using stale cached instruments after download failure")
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                return json.load(fh)

        raise RuntimeError(f"Could not download Angel scrip master: {last_error}")

    def _build_index(self, rows: list[dict]) -> None:
        self._by_symbol.clear()
        self._by_tradingsymbol.clear()

        for row in rows:
            if row.get("exch_seg") != "NSE":
                continue
            if row.get("instrumenttype") not in ("", None):
                continue

            tradingsymbol = row.get("symbol", "")
            if not tradingsymbol.endswith("-EQ"):
                continue

            base = tradingsymbol.replace("-EQ", "").upper()
            entry = {
                "tradingsymbol": tradingsymbol,
                "symboltoken": str(row.get("token", "")),
                "name": row.get("name", base),
                "tick_size": float(row.get("tick_size", 0.05) or 0.05),
                "lotsize": int(row.get("lotsize", 1) or 1),
            }
            self._by_symbol[base] = entry
            self._by_tradingsymbol[tradingsymbol] = entry

    def resolve(self, symbol: str) -> dict[str, Any] | None:
        """Resolve a bare symbol (e.g. RELIANCE) to instrument metadata."""
        if not self._loaded:
            self.load()
        key = symbol.upper().replace("-EQ", "")
        return self._by_symbol.get(key)


_registry: InstrumentRegistry | None = None


def get_registry() -> InstrumentRegistry:
    global _registry
    if _registry is None:
        _registry = InstrumentRegistry()
        _registry.load()
    return _registry


def resolve_symbol(symbol: str) -> dict[str, Any] | None:
    return get_registry().resolve(symbol)
