"""Entry-time feature vectors for meta-label training and inference."""

from __future__ import annotations

import json
from datetime import datetime, time as dtime
from typing import Any

from intraday_agent.config import Config
from intraday_agent.market_regime import MarketRegime
from intraday_agent.strategy import BaseStrategy, ScreenResult
from intraday_agent.universe import to_ist


def stack_snapshot() -> dict[str, Any]:
    """Config snapshot stored on each paper/backtest entry for post-mortem."""
    return {
        "strategy": Config.STRATEGY,
        "rsi_overbought": Config.RSI_OVERBOUGHT,
        "rsi_oversold": Config.RSI_OVERSOLD,
        "entry_cutoff": Config.ENTRY_CUTOFF_TIME,
        "excluded_symbols": sorted(Config.EXCLUDED_SYMBOLS),
        "atr_stop_mult": Config.ATR_STOP_MULT,
        "atr_target_mult": Config.ATR_TARGET_MULT,
        "square_off": Config.SQUARE_OFF_TIME,
    }

MARKET_OPEN = dtime(9, 15)


def minutes_from_open(dt: datetime) -> float:
    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()
    t = dt.time()
    open_min = MARKET_OPEN.hour * 60 + MARKET_OPEN.minute
    bar_min = t.hour * 60 + t.minute
    return float(max(0, bar_min - open_min))


def build_entry_features(
    side: str,
    result: ScreenResult,
    strategy: BaseStrategy,
    slice_df,
    regime: MarketRegime | None,
    bar_dt: datetime,
) -> dict[str, Any]:
    """Feature dict at signal time (stored in journal + used by MetaLabelFilter)."""
    snap = regime.snapshot(bar_dt) if regime is not None else {}
    atr = result.atr if result.atr is not None else (
        strategy.current_atr(slice_df) if slice_df is not None else None
    )
    close = float(result.close)
    atr_pct = round(atr / close * 100, 4) if atr and close > 0 else None
    adx = result.adx
    if adx is None and slice_df is not None:
        adx = strategy.current_adx(slice_df)
    vol_ratio = (
        round(result.volume / result.volume_ma, 4)
        if result.volume_ma and result.volume_ma > 0
        else None
    )
    vwap_distance = None
    if result.vwap is not None and float(result.vwap) > 0:
        vwap_distance = round((close - float(result.vwap)) / float(result.vwap) * 100, 4)
    pivot_pp_dist = None
    if result.pivot_pp is not None and float(result.pivot_pp) > 0:
        pivot_pp_dist = round((close - float(result.pivot_pp)) / float(result.pivot_pp) * 100, 4)
    return {
        "symbol": result.symbol.upper(),
        "side": side.upper(),
        "rsi": round(float(result.rsi), 4),
        "volume_ratio": vol_ratio,
        "adx": round(float(adx), 4) if adx is not None else None,
        "atr_pct": atr_pct,
        "vwap_distance": vwap_distance,
        "pivot_pp": round(float(result.pivot_pp), 2) if result.pivot_pp is not None else None,
        "pivot_pp_dist_pct": pivot_pp_dist,
        "pivot_r1": round(float(result.pivot_r1), 2) if result.pivot_r1 is not None else None,
        "pivot_s1": round(float(result.pivot_s1), 2) if result.pivot_s1 is not None else None,
        "vix": round(float(snap["vix"]), 4) if snap.get("vix") is not None else None,
        "nifty_close": round(float(snap["nifty_close"]), 2) if snap.get("nifty_close") is not None else None,
        "nifty_ema": round(float(snap["nifty_ema"]), 2) if snap.get("nifty_ema") is not None else None,
        "minutes_from_open": round(minutes_from_open(bar_dt), 1),
        "entry_hour": to_ist(bar_dt).hour if bar_dt is not None else None,
        "day_of_week": to_ist(bar_dt).weekday() if bar_dt is not None else None,
        "stack": stack_snapshot(),
    }


def features_to_json(features: dict[str, Any] | None) -> str | None:
    if not features:
        return None
    return json.dumps(features, sort_keys=True)


def features_from_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
