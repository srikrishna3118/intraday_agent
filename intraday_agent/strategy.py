"""Pluggable intraday strategies: RSI mean-reversion, ORB, VWAP pullback."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from enum import Enum

import numpy as np
import pandas as pd

from intraday_agent.config import Config
from intraday_agent.universe import to_ist


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


@dataclass
class ScreenResult:
    symbol: str
    rsi: float
    volume: float
    volume_ma: float
    close: float
    signal: Signal
    vwap: float | None = None
    atr: float | None = None
    adx: float | None = None
    bar_dt: datetime | None = None
    pivot_pp: float | None = None
    pivot_r1: float | None = None
    pivot_r2: float | None = None
    pivot_r3: float | None = None
    pivot_s1: float | None = None
    pivot_s2: float | None = None
    pivot_s3: float | None = None


@dataclass(frozen=True)
class ClassicPivotLevels:
    pp: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float


def classic_pivot_levels(high: float, low: float, close: float) -> ClassicPivotLevels:
    """Classic floor pivots from prior session H/L/C.

    PP = (H+L+C)/3
    S1 = 2*PP - H,  S2 = PP - (H-L),  S3 = L - 2*(H-PP)
    R1 = 2*PP - L,  R2 = PP + (H-L),  R3 = H + 2*(PP-L)
    """
    pp = (high + low + close) / 3.0
    hl = high - low
    return ClassicPivotLevels(
        pp=pp,
        s1=(2.0 * pp) - high,
        s2=pp - hl,
        s3=low - (2.0 * (high - pp)),
        r1=(2.0 * pp) - low,
        r2=pp + hl,
        r3=high + (2.0 * (pp - low)),
    )


def compute_session_pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """Attach prior-session classic pivot levels to each intraday bar."""
    if df is None or df.empty:
        return df
    out = df.copy() if "pp" not in df.columns else df
    dates = pd.to_datetime(out["datetime"]).dt.date
    unique_days = sorted(dates.unique())

    day_hlc: dict[date, tuple[float, float, float]] = {}
    for day in unique_days:
        mask = dates == day
        day_hlc[day] = (
            float(out.loc[mask, "high"].max()),
            float(out.loc[mask, "low"].min()),
            float(out.loc[mask, "close"].iloc[-1]),
        )

    cols = {name: pd.Series(np.nan, index=out.index, dtype=float) for name in (
        "pp", "r1", "r2", "r3", "s1", "s2", "s3",
    )}
    for i, day in enumerate(unique_days):
        if i == 0:
            continue
        prev_h, prev_l, prev_c = day_hlc[unique_days[i - 1]]
        levels = classic_pivot_levels(prev_h, prev_l, prev_c)
        mask = dates == day
        cols["pp"].loc[mask] = levels.pp
        cols["r1"].loc[mask] = levels.r1
        cols["r2"].loc[mask] = levels.r2
        cols["r3"].loc[mask] = levels.r3
        cols["s1"].loc[mask] = levels.s1
        cols["s2"].loc[mask] = levels.s2
        cols["s3"].loc[mask] = levels.s3

    if "pp" not in df.columns:
        out = out.copy()
    for name, series in cols.items():
        out[name] = series
    return out


def _near_pivot_level(price: float, level: float, touch_pct: float) -> bool:
    if level <= 0 or pd.isna(level) or pd.isna(price):
        return False
    return abs(price - level) / level <= touch_pct / 100.0


def pivot_levels_from_df(df: pd.DataFrame) -> ClassicPivotLevels | None:
    """Read classic pivot levels from the last row of a precomputed frame."""
    if df is None or df.empty or "pp" not in df.columns:
        return None
    row = df.iloc[-1]
    pp = row.get("pp")
    if pp is None or pd.isna(pp):
        return None
    return ClassicPivotLevels(
        pp=float(pp),
        r1=float(row["r1"]),
        r2=float(row["r2"]),
        r3=float(row["r3"]),
        s1=float(row["s1"]),
        s2=float(row["s2"]),
        s3=float(row["s3"]),
    )


def compute_rsi(close: pd.Series, period: int | None = None) -> pd.Series:
    period = period or Config.RSI_PERIOD
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_atr(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    period = period or Config.ATR_PERIOD
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def compute_adx(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """Wilder ADX using the same ewm smoothing style as ATR/RSI helpers."""
    period = period or Config.ADX_PERIOD
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / di_sum).fillna(0)
    dx = (100 * (plus_di - minus_di).abs() / di_sum).fillna(0)
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def compute_dmi(
    df: pd.DataFrame,
    di_len: int | None = None,
    adx_len: int | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """+DI, -DI, ADX with separate DI and ADX smoothing (Pine DMI style)."""
    di_len = di_len or Config.ZP_DMI_DI_LEN
    adx_len = adx_len or Config.ZP_DMI_ADX_LEN
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    tr_smooth = tr.ewm(alpha=1 / di_len, min_periods=di_len, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / di_len, min_periods=di_len, adjust=False).mean() / tr_smooth
    minus_di = 100 * minus_dm.ewm(alpha=1 / di_len, min_periods=di_len, adjust=False).mean() / tr_smooth
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / di_sum).fillna(0)
    adx = dx.ewm(alpha=1 / adx_len, min_periods=adx_len, adjust=False).mean()
    return plus_di, minus_di, adx


def compute_macd(
    close: pd.Series,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
) -> tuple[pd.Series, pd.Series]:
    fast = fast or Config.ZP_MACD_FAST
    slow = slow or Config.ZP_MACD_SLOW
    signal = signal or Config.ZP_MACD_SIGNAL
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def _rqk_estimate(close: np.ndarray, end_idx: int, h: float, r: float, x0: int) -> float:
    weighted = 0.0
    total_w = 0.0
    limit = min(end_idx, x0 + len(close))
    for i in range(limit + 1):
        idx = end_idx - i
        if idx < 0:
            break
        y = float(close[idx])
        if np.isnan(y):
            continue
        w = (1 + (i * i / (h * h * 2 * r))) ** (-r)
        weighted += y * w
        total_w += w
    return weighted / total_w if total_w > 0 else np.nan


def compute_rqk_trend(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Rational Quadratic Kernel slope: up when yhat rises, down when yhat falls."""
    arr = close.to_numpy(dtype=float)
    n = len(arr)
    h = Config.ZP_RQK_H
    r = Config.ZP_RQK_R
    x0 = Config.ZP_RQK_X0
    yhat = np.full(n, np.nan)
    for i in range(n):
        if i >= x0:
            yhat[i] = _rqk_estimate(arr, i, h, r, x0)
    up = pd.Series(np.zeros(n, dtype=bool), index=close.index)
    down = pd.Series(np.zeros(n, dtype=bool), index=close.index)
    for i in range(1, n):
        if not np.isnan(yhat[i]) and not np.isnan(yhat[i - 1]):
            up.iloc[i] = yhat[i] > yhat[i - 1]
            down.iloc[i] = yhat[i] < yhat[i - 1]
    return up, down


def compute_chandelier_direction(df: pd.DataFrame) -> pd.Series:
    """Chandelier Exit direction: 1 long, -1 short (Pine port)."""
    length = Config.ZP_CE_LEN
    mult = Config.ZP_CE_MULT
    close = df["close"]
    high = df["high"]
    low = df["low"]
    atr = compute_atr(df, length)
    ce_atr = mult * atr

    if Config.ZP_CE_USE_CLOSE:
        roll_high = close.rolling(length).max()
        roll_low = close.rolling(length).min()
    else:
        roll_high = high.rolling(length).max()
        roll_low = low.rolling(length).min()

    n = len(df)
    direction = np.ones(n, dtype=int)
    long_stop = np.full(n, np.nan)
    short_stop = np.full(n, np.nan)

    for i in range(n):
        if i < length or pd.isna(ce_atr.iloc[i]):
            continue
        ls = float(roll_high.iloc[i]) - float(ce_atr.iloc[i])
        ss = float(roll_low.iloc[i]) + float(ce_atr.iloc[i])
        prev_ls = long_stop[i - 1] if i > 0 and not np.isnan(long_stop[i - 1]) else ls
        prev_ss = short_stop[i - 1] if i > 0 and not np.isnan(short_stop[i - 1]) else ss
        prev_close = float(close.iloc[i - 1]) if i > 0 else float(close.iloc[i])
        long_stop[i] = max(ls, prev_ls) if prev_close > prev_ls else ls
        short_stop[i] = min(ss, prev_ss) if prev_close < prev_ss else ss
        prev_dir = int(direction[i - 1]) if i > 0 else 1
        c = float(close.iloc[i])
        if i > 0 and c > short_stop[i - 1]:
            direction[i] = 1
        elif i > 0 and c < long_stop[i - 1]:
            direction[i] = -1
        else:
            direction[i] = prev_dir

    return pd.Series(direction, index=df.index)


def compute_wma(series: pd.Series, length: int) -> pd.Series:
    """Linear weighted moving average (Pine ta.wma)."""
    weights = np.arange(1, length + 1, dtype=float)

    def _wma(arr: np.ndarray) -> float:
        if len(arr) < length:
            return np.nan
        w = weights
        return float(np.dot(arr, w) / w.sum())

    return series.rolling(length, min_periods=length).apply(_wma, raw=True)


def compute_volume_ma(
    close: pd.Series,
    volume: pd.Series,
    length: int,
    ma_src: str | None = None,
) -> pd.Series:
    """Volume-weighted price MA (Pine Volume SuperTrend AI vwma)."""
    src = ma_src or Config.VST_MA_SRC
    num = close * volume
    if src == "SMA":
        return num.rolling(length, min_periods=length).sum() / volume.rolling(
            length, min_periods=length,
        ).sum().replace(0, np.nan)
    if src == "EMA":
        return num.ewm(span=length, adjust=False, min_periods=length).mean() / volume.ewm(
            span=length, adjust=False, min_periods=length,
        ).mean().replace(0, np.nan)
    if src == "RMA":
        return num.ewm(alpha=1 / length, adjust=False, min_periods=length).mean() / volume.ewm(
            alpha=1 / length, adjust=False, min_periods=length,
        ).mean().replace(0, np.nan)
    if src == "VWMA":
        return num.rolling(length, min_periods=length).sum() / volume.rolling(
            length, min_periods=length,
        ).sum().replace(0, np.nan)
    return compute_wma(num, length) / compute_wma(volume, length)


def compute_volume_supertrend(
    df: pd.DataFrame,
    length: int | None = None,
    factor: float | None = None,
    ma_src: str | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Volume SuperTrend line and direction (-1 up, 1 down) — Zeiierman Pine port."""
    length = length or Config.VST_LEN
    factor = factor if factor is not None else Config.VST_FACTOR
    close = df["close"]
    vwma = compute_volume_ma(close, df["volume"], length, ma_src)
    atr = compute_atr(df, length)

    n = len(df)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    direction = np.ones(n, dtype=int)
    supertrend = np.full(n, np.nan)

    upper_raw = vwma + factor * atr
    lower_raw = vwma - factor * atr

    for i in range(n):
        if pd.isna(upper_raw.iloc[i]) or pd.isna(lower_raw.iloc[i]):
            continue
        ub = float(upper_raw.iloc[i])
        lb = float(lower_raw.iloc[i])
        if i > 0 and not np.isnan(lower[i - 1]):
            prev_lb = lower[i - 1]
            prev_close = float(close.iloc[i - 1])
            lb = lb if (lb > prev_lb or prev_close < prev_lb) else prev_lb
        if i > 0 and not np.isnan(upper[i - 1]):
            prev_ub = upper[i - 1]
            prev_close = float(close.iloc[i - 1])
            ub = ub if (ub < prev_ub or prev_close > prev_ub) else prev_ub
        upper[i] = ub
        lower[i] = lb

        if i == 0 or pd.isna(atr.iloc[i - 1]):
            direction[i] = 1
        elif not np.isnan(supertrend[i - 1]) and np.isclose(supertrend[i - 1], upper[i - 1]):
            direction[i] = -1 if float(close.iloc[i]) > ub else 1
        else:
            direction[i] = 1 if float(close.iloc[i]) < lb else -1

        supertrend[i] = lower[i] if direction[i] == -1 else upper[i]

    idx = df.index
    return pd.Series(supertrend, index=idx), pd.Series(direction, index=idx)


def _knn_weighted_label(
    st_values: np.ndarray,
    price_wma: np.ndarray,
    st_wma: np.ndarray,
    i: int,
    k: int,
    n: int,
) -> float:
    """Weighted KNN label at bar i (1 bullish, 0 bearish)."""
    x = st_values[i]
    if np.isnan(x):
        return np.nan
    data: list[float] = []
    labels: list[int] = []
    for j in range(n):
        idx = i - j
        if idx < 0:
            break
        st_val = st_values[idx]
        p = price_wma[idx]
        s = st_wma[idx]
        if np.isnan(st_val) or np.isnan(p) or np.isnan(s):
            continue
        data.append(float(st_val))
        labels.append(1 if p > s else 0)
    if len(data) < k:
        return np.nan
    pairs = sorted((abs(d - x), lab) for d, lab in zip(data, labels))
    weighted_sum = 0.0
    total_weight = 0.0
    for dist, lab in pairs[:k]:
        w = 1.0 / (dist + 1e-6)
        weighted_sum += w * lab
        total_weight += w
    return weighted_sum / total_weight if total_weight > 0 else np.nan


def _vst_label_bullish(label: float) -> bool:
    return not np.isnan(label) and np.isclose(label, 1.0)


def _vst_label_bearish(label: float) -> bool:
    return not np.isnan(label) and np.isclose(label, 0.0)


def precompute_vst_ai_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Zeiierman Volume SuperTrend AI entry flags (vst_long / vst_short)."""
    if df is None or df.empty:
        return df
    out = df.copy() if "vst_long" not in df.columns else df

    super_trend, direction = compute_volume_supertrend(out)
    st_arr = super_trend.to_numpy(dtype=float)
    dir_arr = direction.to_numpy(dtype=int)
    price_wma = compute_wma(out["close"], Config.VST_PRICE_LEN).to_numpy(dtype=float)
    st_wma = compute_wma(super_trend, Config.VST_ST_LEN).to_numpy(dtype=float)

    k = Config.VST_K
    n = max(k, Config.VST_N)
    mode = Config.VST_ENTRY_MODE
    use_signals = Config.VST_AI_SIGNALS

    labels = np.full(len(out), np.nan)
    vst_long = np.zeros(len(out), dtype=bool)
    vst_short = np.zeros(len(out), dtype=bool)

    start = max(
        Config.VST_LEN + 1,
        Config.VST_PRICE_LEN + n,
        Config.VST_ST_LEN + n,
    )

    for i in range(start, len(out)):
        labels[i] = _knn_weighted_label(st_arr, price_wma, st_wma, i, k, n)
        if not use_signals:
            continue

        bullish = _vst_label_bullish(labels[i])
        bearish = _vst_label_bearish(labels[i])
        prev_label = labels[i - 1] if i > 0 else np.nan
        prev_bull = _vst_label_bullish(prev_label)
        prev_bear = _vst_label_bearish(prev_label)
        prev_neutral = not prev_bull and not prev_bear

        start_up = bullish and (not prev_bull or prev_neutral)
        start_dn = bearish and (not prev_bear or prev_neutral)
        trend_up = dir_arr[i] == -1 and dir_arr[i - 1] == 1 and bullish
        trend_dn = dir_arr[i] == 1 and dir_arr[i - 1] == -1 and bearish

        long_hit = (
            (mode in ("start", "both") and start_up)
            or (mode in ("trend", "both") and trend_up)
        )
        short_hit = (
            (mode in ("start", "both") and start_dn)
            or (mode in ("trend", "both") and trend_dn)
        )
        vst_long[i] = long_hit
        vst_short[i] = short_hit

    if "vst_long" not in df.columns:
        out = out.copy()
    out["vst_long"] = vst_long
    out["vst_short"] = vst_short
    out["vst_label"] = labels
    out["vst_direction"] = dir_arr
    out["vst_line"] = st_arr
    return out


def _sbp_base_len_gap(mode: str) -> tuple[int, int]:
    m = (mode or "INTRADAY").upper()
    if m == "SCALPING":
        return 14, 4
    if m == "SWING":
        return 34, 10
    return 21, 6


def _wma_at(values: np.ndarray, end: int, length: int) -> float:
    length = max(int(length), 1)
    if end < length - 1:
        return np.nan
    window = values[end - length + 1 : end + 1]
    weights = np.arange(1, length + 1, dtype=float)
    return float(np.dot(window, weights) / weights.sum())


def precompute_sbp_signals(df: pd.DataFrame) -> pd.DataFrame:
    """SBP Trend & Momentum entry flags (sbp_long / sbp_short / sbp_momentum_score).

    Entry state only (gap + signalDirection). Exits use entry-anchored Pine ATR trail in
    SbpTmStrategy.exit_reason(), not precomputed activeTrade columns.
    """
    if df is None or df.empty:
        return df
    out = df.copy() if "sbp_long" not in df.columns else df

    base_len, gap_bars = _sbp_base_len_gap(Config.SBP_TRADE_MODE)
    close_s = out["close"]
    close = close_s.to_numpy(dtype=float)
    volume = out["volume"].to_numpy(dtype=float)
    n = len(out)

    atr_slow = compute_atr(out, 21).to_numpy(dtype=float)
    atr_avg = pd.Series(atr_slow).rolling(20, min_periods=20).mean().to_numpy(dtype=float)
    volatility = np.ones(n, dtype=float)
    for i in range(n):
        if not np.isnan(atr_avg[i]) and atr_avg[i] > 0:
            volatility[i] = float(atr_slow[i] / atr_avg[i])

    ratio = np.clip(volatility, 0.8, 1.3)
    baseline = close_s.ewm(span=base_len, adjust=False).mean().to_numpy(dtype=float)
    baseline_slope = np.empty(n)
    baseline_slope[0] = np.nan
    baseline_slope[1:] = baseline[1:] - baseline[:-1]

    trend = np.zeros(n, dtype=int)
    for i in range(1, n):
        if np.isnan(baseline[i]) or np.isnan(baseline_slope[i]):
            continue
        if close[i] > baseline[i] and baseline_slope[i] > 0:
            trend[i] = 1
        elif close[i] < baseline[i] and baseline_slope[i] < 0:
            trend[i] = -1

    ema25 = close_s.ewm(span=25, adjust=False).mean()
    dtf = ema25.ewm(span=2, adjust=False).mean().to_numpy(dtype=float)

    avg_volume = pd.Series(volume).rolling(20, min_periods=20).mean().to_numpy(dtype=float)
    volume_ratio = np.ones(n, dtype=float)
    for i in range(n):
        if not np.isnan(avg_volume[i]) and avg_volume[i] > 0:
            volume_ratio[i] = float(volume[i] / avg_volume[i])
        volume_ratio[i] = float(np.clip(volume_ratio[i], 0.5, 2.0))

    momentum = np.zeros(n, dtype=float)
    for i in range(5, n):
        if not np.isnan(atr_slow[i]) and atr_slow[i] > 0:
            momentum[i] = (close[i] - close[i - 5]) / atr_slow[i]

    momentum_score = np.zeros(n, dtype=float)
    for i in range(n):
        score = abs(momentum[i]) * 50.0 + volume_ratio[i] * 20.0
        if i > 0 and trend[i] == trend[i - 1]:
            score += 30.0
        momentum_score[i] = min(score, 100.0)

    adaptive_src = np.full(n, np.nan)
    adaptive_trend = np.full(n, np.nan)
    adaptive_up = np.zeros(n, dtype=bool)
    for i in range(n):
        alen = max(int(round(base_len * ratio[i])), 5)
        w2_len = max(int(round(alen / 2)), 1)
        w1 = _wma_at(close, i, alen)
        w2 = _wma_at(close, i, w2_len)
        if np.isnan(w1) or np.isnan(w2):
            continue
        adaptive_src[i] = 2.0 * w2 - w1
        wma_len = max(int(round(np.sqrt(alen))), 1)
        adaptive_trend[i] = _wma_at(adaptive_src, i, wma_len)
        if i > 0 and not np.isnan(adaptive_trend[i]) and not np.isnan(adaptive_trend[i - 1]):
            adaptive_up[i] = adaptive_trend[i] > adaptive_trend[i - 1]

    distance = np.zeros(n, dtype=float)
    sideways = np.zeros(n, dtype=bool)
    for i in range(n):
        if not np.isnan(atr_slow[i]) and atr_slow[i] > 0 and not np.isnan(dtf[i]):
            distance[i] = abs(close[i] - dtf[i]) / atr_slow[i]
        sideways[i] = distance[i] < 0.25 and volatility[i] < 1.0

    mom_min = Config.SBP_MOMENTUM_MIN
    sbp_long = np.zeros(n, dtype=bool)
    sbp_short = np.zeros(n, dtype=bool)
    signal_direction = 0
    last_signal_bar = -10_000

    warmup = max(base_len + 20, 30, 5 + gap_bars)
    for i in range(warmup, n):
        if np.isnan(dtf[i]) or np.isnan(atr_slow[i]):
            continue
        strong_momentum = momentum_score[i] >= mom_min
        raw_buy = (
            trend[i] == 1
            and close[i] > dtf[i]
            and adaptive_up[i]
            and strong_momentum
            and not sideways[i]
        )
        raw_sell = (
            trend[i] == -1
            and close[i] < dtf[i]
            and not adaptive_up[i]
            and strong_momentum
            and not sideways[i]
        )
        gap_ok = last_signal_bar < 0 or (i - last_signal_bar) >= gap_bars
        buy_signal = raw_buy and signal_direction != 1 and gap_ok
        sell_signal = raw_sell and signal_direction != -1 and gap_ok
        if buy_signal:
            signal_direction = 1
            last_signal_bar = i
            sbp_long[i] = True
        elif sell_signal:
            signal_direction = -1
            last_signal_bar = i
            sbp_short[i] = True

    if "sbp_long" not in df.columns:
        out = out.copy()
    out["sbp_long"] = sbp_long
    out["sbp_short"] = sbp_short
    out["sbp_momentum_score"] = momentum_score
    return out


@dataclass
class _ZpSdZone:
    """Active supply (resistance) or demand (support) zone from swing pivot."""

    top: float
    bottom: float
    kind: int  # 1 = supply, -1 = demand

    @property
    def poi(self) -> float:
        return (self.top + self.bottom) / 2.0


def _confirmed_swing_pivot(values: np.ndarray, i: int, length: int, *, high: bool) -> float | None:
    """Pine ta.pivothigh/pivotlow confirmation at bar i."""
    if i < 2 * length:
        return None
    p = i - length
    center = float(values[p])
    if np.isnan(center):
        return None
    for j in range(p - length, p + length + 1):
        if j == p:
            continue
        v = float(values[j])
        if np.isnan(v):
            return None
        if high and v >= center:
            return None
        if not high and v <= center:
            return None
    return center


def _sd_zone_overlaps(new_poi: float, zones: list[_ZpSdZone], threshold: float) -> bool:
    return any(abs(new_poi - z.poi) <= threshold for z in zones)


def _sd_price_at_zone(close: float, zone: _ZpSdZone, touch_pct: float) -> bool:
    if zone.bottom <= close <= zone.top:
        return True
    return _near_pivot_level(close, zone.poi, touch_pct)


def compute_zp_sd_zone_flags(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """ZPayab supply/demand S/R: swing pivots + ATR box (POI overlay port)."""
    swing_len = Config.ZP_SD_SWING_LEN
    history = Config.ZP_SD_HISTORY
    box_width = Config.ZP_SD_BOX_WIDTH
    atr_len = Config.ZP_SD_ATR_LEN
    touch = Config.ZP_SD_TOUCH_PCT

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    atr_arr = compute_atr(df, atr_len).to_numpy(dtype=float)
    n = len(df)

    supply_zones: list[_ZpSdZone] = []
    demand_zones: list[_ZpSdZone] = []
    demand_ok = np.zeros(n, dtype=bool)
    supply_ok = np.zeros(n, dtype=bool)

    for i in range(n):
        atrpoi = atr_arr[i]
        if not np.isnan(atrpoi) and atrpoi > 0:
            close = closes[i]
            supply_zones = [z for z in supply_zones if close < z.top]
            demand_zones = [z for z in demand_zones if close > z.bottom]

            pivot_high = _confirmed_swing_pivot(highs, i, swing_len, high=True)
            if pivot_high is not None:
                buffer = atrpoi * (box_width / 10.0)
                top = pivot_high
                bottom = top - buffer
                poi = (top + bottom) / 2.0
                if not _sd_zone_overlaps(poi, supply_zones, atrpoi * 2.0):
                    supply_zones.insert(0, _ZpSdZone(top=top, bottom=bottom, kind=1))
                    if len(supply_zones) > history:
                        supply_zones.pop()

            pivot_low = _confirmed_swing_pivot(lows, i, swing_len, high=False)
            if pivot_low is not None:
                buffer = atrpoi * (box_width / 10.0)
                bottom = pivot_low
                top = bottom + buffer
                poi = (top + bottom) / 2.0
                if not _sd_zone_overlaps(poi, demand_zones, atrpoi * 2.0):
                    demand_zones.insert(0, _ZpSdZone(top=top, bottom=bottom, kind=-1))
                    if len(demand_zones) > history:
                        demand_zones.pop()

        close = closes[i]
        demand_ok[i] = any(_sd_price_at_zone(close, z, touch) for z in demand_zones)
        supply_ok[i] = any(_sd_price_at_zone(close, z, touch) for z in supply_zones)

    idx = df.index
    return pd.Series(demand_ok, index=idx), pd.Series(supply_ok, index=idx)


def precompute_zp_dmi_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add zp_long/zp_short columns for ZPayab DMI confluence strategy."""
    if df is None or df.empty:
        return df
    out = df.copy() if "zp_long" not in df.columns else df

    plus_di, minus_di, adx = compute_dmi(out)
    rqk_up, rqk_down = compute_rqk_trend(out["close"])
    vwap = out["vwap"] if "vwap" in out.columns else compute_session_vwap(out)
    ce_dir = compute_chandelier_direction(out)
    macd_line, signal_line = compute_macd(out["close"])
    vol_ma = out["vol_ma"] if "vol_ma" in out.columns else out["volume"].rolling(
        Config.ZP_VOL_MA_LEN,
    ).mean()

    close = out["close"]
    volume = out["volume"]
    adx_min = Config.ZP_DMI_ADX_MIN

    leading_long = (plus_di > minus_di) & (adx >= adx_min)
    leading_short = (plus_di < minus_di) & (adx >= adx_min)
    vwap_long = close > vwap
    vwap_short = close < vwap
    ce_long = ce_dir == 1
    ce_short = ce_dir == -1
    macd_long = macd_line > signal_line
    macd_short = macd_line < signal_line
    vol_ok = volume > vol_ma

    sd_demand_ok, sd_supply_ok = compute_zp_sd_zone_flags(out)
    mode = Config.ZP_SD_FILTER_MODE
    if not Config.ZP_SD_FILTER_ENABLED:
        long_sd = pd.Series(True, index=out.index)
        short_sd = pd.Series(True, index=out.index)
    elif mode == "at_zone":
        long_sd = sd_demand_ok
        short_sd = sd_supply_ok
    else:  # avoid — default; do not buy into supply / sell into demand
        long_sd = ~sd_supply_ok
        short_sd = ~sd_demand_ok

    long_raw = leading_long & rqk_up & vwap_long & ce_long & macd_long & vol_ok & long_sd
    short_raw = leading_short & rqk_down & vwap_short & ce_short & macd_short & vol_ok & short_sd

    n = len(out)
    expiry = Config.ZP_SIGNAL_EXPIRY
    zp_long = np.zeros(n, dtype=bool)
    zp_short = np.zeros(n, dtype=bool)
    cond_ini = np.zeros(n, dtype=int)

    start = max(
        Config.ZP_DMI_DI_LEN * 2,
        Config.ZP_MACD_SLOW + Config.ZP_MACD_SIGNAL,
        Config.ZP_CE_LEN + 1,
        Config.ZP_RQK_X0 + 2,
        Config.ZP_VOL_MA_LEN + 1,
    )

    for i in range(start, n):
        ll_streak = 0
        if bool(long_raw.iloc[i]):
            for j in range(i, -1, -1):
                if bool(leading_long.iloc[j]):
                    ll_streak += 1
                else:
                    break
        ss_streak = 0
        if bool(short_raw.iloc[i]):
            for j in range(i, -1, -1):
                if bool(leading_short.iloc[j]):
                    ss_streak += 1
                else:
                    break

        long_exp = bool(long_raw.iloc[i]) and 1 <= ll_streak <= expiry
        short_exp = bool(short_raw.iloc[i]) and 1 <= ss_streak <= expiry
        prev_ini = cond_ini[i - 1] if i > 0 else 0

        if Config.ZP_ALTERNATE_SIGNAL:
            if long_exp and prev_ini == -1:
                zp_long[i] = True
            if short_exp and prev_ini == 1:
                zp_short[i] = True
        else:
            zp_long[i] = long_exp
            zp_short[i] = short_exp

        if long_exp:
            cond_ini[i] = 1
        elif short_exp:
            cond_ini[i] = -1
        else:
            cond_ini[i] = prev_ini

    if "zp_long" not in df.columns:
        out = out.copy()
    out["zp_long"] = zp_long
    out["zp_short"] = zp_short
    out["zp_sd_demand"] = sd_demand_ok.to_numpy(dtype=bool)
    out["zp_sd_supply"] = sd_supply_ok.to_numpy(dtype=bool)
    return out


def compute_session_vwap(df: pd.DataFrame) -> pd.Series:
    """Intraday session VWAP reset each calendar day on the candle timestamps."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    dates = pd.to_datetime(df["datetime"]).dt.date
    tp_vol = typical * df["volume"]
    vwap = pd.Series(index=df.index, dtype=float)
    for day in dates.unique():
        mask = dates == day
        cum_vol = df.loc[mask, "volume"].cumsum()
        cum_tp_vol = tp_vol.loc[mask].cumsum()
        vwap.loc[mask] = cum_tp_vol / cum_vol.replace(0, np.nan)
    return vwap


def volume_confirmed(df: pd.DataFrame, mult: float | None = None) -> bool:
    if df is None or len(df) < Config.VOLUME_MA_LEN + 1:
        return False
    if "vol_ma" in df.columns:
        vol_ma = float(df["vol_ma"].iloc[-1])
    else:
        vol_ma = float(df["volume"].rolling(Config.VOLUME_MA_LEN).mean().iloc[-1])
    last_vol = float(df["volume"].iloc[-1])
    min_mult = mult if mult is not None else Config.VOLUME_MA_MULT
    if pd.isna(vol_ma) or vol_ma <= 0:
        return False
    if last_vol <= vol_ma * min_mult:
        return False
    if Config.VOLUME_MA_MAX_MULT > 0 and last_vol > vol_ma * Config.VOLUME_MA_MAX_MULT:
        return False
    return True


def parse_time_setting(value: str) -> dtime:
    hh, mm = value.split(":")
    return dtime(int(hh), int(mm))


def entry_time_allowed(dt: datetime) -> bool:
    if not Config.ENTRY_CUTOFF_TIME:
        return True
    cutoff = parse_time_setting(Config.ENTRY_CUTOFF_TIME)
    return to_ist(dt).time() < cutoff


def _pnl_pct(side: str, entry: float, price: float) -> float:
    if side == "LONG":
        return (price - entry) / entry * 100
    return (entry - price) / entry * 100


def _bar_minutes() -> int:
    """Minutes per bar from CANDLE_INTERVAL (15m default)."""
    mapping = {
        "ONE_MINUTE": 1,
        "THREE_MINUTE": 3,
        "FIVE_MINUTE": 5,
        "TEN_MINUTE": 10,
        "FIFTEEN_MINUTE": 15,
        "THIRTY_MINUTE": 30,
        "ONE_HOUR": 60,
    }
    return mapping.get(Config.CANDLE_INTERVAL, 15)


def _session_day_df(df: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(df["datetime"]).dt.date
    last_date = dates.iloc[-1]
    return df.loc[dates == last_date].copy()


def _orb_bar_count() -> int:
    return max(1, Config.ORB_MINUTES // _bar_minutes())


def opening_range_levels(df: pd.DataFrame) -> tuple[float, float] | None:
    """High/low of the opening range for the session of the last bar."""
    day_df = _session_day_df(df)
    n = _orb_bar_count()
    if len(day_df) < n:
        return None
    or_slice = day_df.iloc[:n]
    return float(or_slice["high"].max()), float(or_slice["low"].min())


def prior_session_close(df: pd.DataFrame) -> float | None:
    dates = pd.to_datetime(df["datetime"]).dt.date
    uniq = list(dates.unique())
    if len(uniq) < 2:
        return None
    prev_day = df.loc[dates == uniq[-2]]
    if prev_day.empty:
        return None
    return float(prev_day["close"].iloc[-1])


def session_open(df: pd.DataFrame) -> float | None:
    day_df = _session_day_df(df)
    if day_df.empty:
        return None
    return float(day_df["open"].iloc[0])


def session_high(df: pd.DataFrame) -> float | None:
    day_df = _session_day_df(df)
    if day_df.empty:
        return None
    return float(day_df["high"].max())


def session_change_pct(df: pd.DataFrame) -> float | None:
    """Percent change vs prior session close (typical 'stock up X% today')."""
    prev = prior_session_close(df)
    close = float(df["close"].iloc[-1])
    if prev is None or prev <= 0:
        return None
    return (close - prev) / prev * 100.0


def gap_pct(df: pd.DataFrame) -> float | None:
    prev = prior_session_close(df)
    open_px = session_open(df)
    if prev is None or open_px is None or prev <= 0:
        return None
    return (open_px - prev) / prev * 100.0


def distance_from_vwap_pct(close: float, vwap: float | None) -> float | None:
    if vwap is None or vwap <= 0 or pd.isna(vwap):
        return None
    return (close - vwap) / vwap * 100.0


def volume_contracting(df: pd.DataFrame, n: int = 1) -> bool:
    if len(df) < n + 1:
        return False
    vols = df["volume"].iloc[-(n + 1):]
    for i in range(1, len(vols)):
        if float(vols.iloc[i]) >= float(vols.iloc[i - 1]):
            return False
    return True


def is_bullish_candle(df: pd.DataFrame, idx: int = -1) -> bool:
    row = df.iloc[idx]
    return float(row["close"]) > float(row["open"])


def bars_since_session_open(df: pd.DataFrame) -> int:
    return len(_session_day_df(df))


def first_session_bar(df: pd.DataFrame) -> pd.Series | None:
    day_df = _session_day_df(df)
    if day_df.empty:
        return None
    return day_df.iloc[0]


def open_fade_time_allowed(dt: datetime) -> bool:
    end = parse_time_setting(Config.OPEN_FADE_END_TIME)
    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()
    return dt.time() <= end


def current_rsi_fast(df: pd.DataFrame) -> float | None:
    if df is not None and "rsi2" in df.columns:
        val = float(df["rsi2"].iloc[-1])
        return None if pd.isna(val) else val
    period = Config.RSI_FAST_PERIOD
    if df is None or len(df) < period + 1:
        return None
    val = float(compute_rsi(df["close"], period).iloc[-1])
    return None if pd.isna(val) else val


class Strategy(ABC):
    @abstractmethod
    def entry_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        ...

    @abstractmethod
    def exit_signal(self, df: pd.DataFrame, side: str) -> bool:
        ...


class BaseStrategy(Strategy):
    """Shared ATR/VWAP helpers, trailing stops, and default exit stack."""

    def min_bars(self) -> int:
        return max(Config.ATR_PERIOD + 1, Config.VOLUME_MA_LEN + 1)

    def current_atr(self, df: pd.DataFrame) -> float | None:
        if df is not None and "atr" in df.columns:
            val = float(df["atr"].iloc[-1])
            return val if not pd.isna(val) and val > 0 else None
        if df is None or len(df) < Config.ATR_PERIOD + 1:
            return None
        val = float(compute_atr(df).iloc[-1])
        return val if not pd.isna(val) and val > 0 else None

    def current_vwap(self, df: pd.DataFrame) -> float | None:
        if df is not None and "vwap" in df.columns:
            val = float(df["vwap"].iloc[-1])
            return val if not pd.isna(val) else None
        if df is None or len(df) < 2:
            return None
        val = float(compute_session_vwap(df).iloc[-1])
        return val if not pd.isna(val) else None

    def current_rsi(self, df: pd.DataFrame) -> float | None:
        if df is not None and "rsi" in df.columns:
            val = float(df["rsi"].iloc[-1])
            return None if pd.isna(val) else val
        if df is None or len(df) < Config.RSI_PERIOD + 1:
            return None
        val = float(compute_rsi(df["close"]).iloc[-1])
        return None if pd.isna(val) else val

    def current_adx(self, df: pd.DataFrame) -> float | None:
        if df is not None and "adx" in df.columns:
            val = float(df["adx"].iloc[-1])
            return None if pd.isna(val) else val
        if df is None or len(df) < Config.ADX_PERIOD * 2:
            return None
        val = float(compute_adx(df).iloc[-1])
        return None if pd.isna(val) else val

    def current_pivot_levels(self, df: pd.DataFrame) -> ClassicPivotLevels | None:
        if df is None or df.empty:
            return None
        if "pp" not in df.columns:
            return pivot_levels_from_df(compute_session_pivot_points(df))
        return pivot_levels_from_df(df)

    def pivot_allows_entry(
        self,
        side: str,
        close: float,
        df: pd.DataFrame,
        *,
        trend: bool = False,
    ) -> bool:
        """Optional classic pivot gate: MR fades at S/R; trend entries on PP half."""
        if not Config.PIVOT_FILTER_ENABLED:
            return True
        levels = self.current_pivot_levels(df)
        if levels is None or levels.pp <= 0:
            return False

        touch = Config.PIVOT_TOUCH_PCT / 100.0
        if trend:
            if side == "LONG":
                return close >= levels.pp * (1.0 - touch)
            return close <= levels.pp * (1.0 + touch)

        mode = Config.PIVOT_FILTER_MODE
        supports = [levels.pp, levels.s1, levels.s2, levels.s3]
        resistances = [levels.pp, levels.r1, levels.r2, levels.r3]

        def near_levels(candidates: list[float]) -> bool:
            return any(
                _near_pivot_level(close, lv, Config.PIVOT_TOUCH_PCT)
                for lv in candidates
                if lv and lv > 0
            )

        if mode == "zone":
            if side == "LONG":
                return close <= levels.pp * (1.0 + touch)
            return close >= levels.pp * (1.0 - touch)
        if mode == "proximity":
            if side == "LONG":
                return near_levels(supports)
            return near_levels(resistances)
        if mode == "both":
            if side == "LONG":
                return close <= levels.pp * (1.0 + touch) and near_levels(supports)
            return close >= levels.pp * (1.0 - touch) and near_levels(resistances)
        return True

    def _gate_pivot_entry(
        self,
        signal: Signal,
        close: float,
        df: pd.DataFrame,
        *,
        trend: bool = False,
    ) -> Signal:
        if signal == Signal.NONE:
            return signal
        side = "LONG" if signal == Signal.BUY else "SHORT"
        return signal if self.pivot_allows_entry(side, close, df, trend=trend) else Signal.NONE

    def adx_allows_entry(self, df: pd.DataFrame) -> bool:
        if Config.ADX_MR_MAX <= 0 and Config.ADX_MR_MIN <= 0:
            return True
        adx = self.current_adx(df)
        if adx is None:
            return False
        if Config.ADX_MR_MIN > 0 and adx < Config.ADX_MR_MIN:
            return False
        if Config.ADX_MR_MAX > 0 and adx >= Config.ADX_MR_MAX:
            return False
        return True

    def vwap_allows_entry(self, side: str, close: float, vwap: float | None) -> bool:
        if not Config.VWAP_FILTER_ENABLED or vwap is None or pd.isna(vwap):
            return True
        if side == "LONG":
            return close > vwap
        return close < vwap

    def vwap_breakdown(self, df: pd.DataFrame, side: str) -> bool:
        if not Config.VWAP_EXIT_ENABLED:
            return False
        close = float(df["close"].iloc[-1])
        vwap = self.current_vwap(df)
        if vwap is None:
            return False
        if side == "LONG":
            return close < vwap
        return close > vwap

    def stop_target_hit(
        self,
        side: str,
        entry: float,
        price: float,
        entry_atr: float | None,
        trailing_active: bool = False,
    ) -> str | None:
        if Config.USE_ATR_EXITS and entry_atr and entry_atr > 0:
            stop_dist = entry_atr * Config.ATR_STOP_MULT
            target_dist = entry_atr * Config.ATR_TARGET_MULT
            if side == "LONG":
                if not trailing_active and price <= entry - stop_dist:
                    return f"ATR stop ({_pnl_pct(side, entry, price):.2f}%)"
                if price >= entry + target_dist:
                    return f"ATR target ({_pnl_pct(side, entry, price):.2f}%)"
            else:
                if not trailing_active and price >= entry + stop_dist:
                    return f"ATR stop ({_pnl_pct(side, entry, price):.2f}%)"
                if price <= entry - target_dist:
                    return f"ATR target ({_pnl_pct(side, entry, price):.2f}%)"
            return None

        if trailing_active:
            return None
        pnl_pct = _pnl_pct(side, entry, price)
        if pnl_pct <= -Config.STOP_LOSS_PCT:
            return f"stop loss ({pnl_pct:.2f}%)"
        if pnl_pct >= Config.TARGET_PCT:
            return f"target ({pnl_pct:.2f}%)"
        return None

    def _trailing_active(
        self, side: str, entry: float, extreme: float, entry_atr: float | None,
    ) -> bool:
        if Config.USE_ATR_EXITS and entry_atr and entry_atr > 0:
            activation = entry_atr * Config.TRAILING_ACTIVATION_ATR_MULT
            if side == "LONG":
                return extreme >= entry + activation
            return extreme <= entry - activation
        activation_pct = Config.TRAILING_ACTIVATION_PCT
        return _pnl_pct(side, entry, extreme) >= activation_pct

    def _trailing_stop_level(
        self,
        side: str,
        entry: float,
        extreme: float,
        entry_atr: float | None,
    ) -> float | None:
        if not self._trailing_active(side, entry, extreme, entry_atr):
            return None
        if Config.USE_ATR_EXITS and entry_atr and entry_atr > 0:
            trail_dist = entry_atr * Config.TRAILING_STOP_ATR_MULT
            if side == "LONG":
                return extreme - trail_dist
            return extreme + trail_dist
        trail_pct = Config.TRAILING_STOP_PCT / 100
        if side == "LONG":
            return extreme * (1 - trail_pct)
        return extreme * (1 + trail_pct)

    def trailing_stop_hit(
        self,
        side: str,
        entry: float,
        price: float,
        entry_atr: float | None,
        trail_extreme: float | None,
    ) -> str | None:
        if not Config.TRAILING_STOP_ENABLED or trail_extreme is None:
            return None
        level = self._trailing_stop_level(side, entry, trail_extreme, entry_atr)
        if level is None:
            return None
        if side == "LONG" and price <= level:
            return f"trailing stop ({_pnl_pct(side, entry, price):.2f}%)"
        if side == "SHORT" and price >= level:
            return f"trailing stop ({_pnl_pct(side, entry, price):.2f}%)"
        return None

    @staticmethod
    def update_trail_extreme(
        side: str,
        extreme: float | None,
        high: float,
        low: float,
        *,
        close: float | None = None,
        atr: float | None = None,
    ) -> float:
        if extreme is None:
            extreme = high if side == "LONG" else low
        if side == "LONG":
            return max(extreme, high)
        return min(extreme, low)

    def exit_reason(
        self,
        df: pd.DataFrame,
        side: str,
        entry: float,
        price: float,
        entry_atr: float | None = None,
        trail_extreme: float | None = None,
    ) -> str | None:
        trailing_active = False
        if Config.TRAILING_STOP_ENABLED and trail_extreme is not None:
            trailing_active = self._trailing_active(side, entry, trail_extreme, entry_atr)
            reason = self.trailing_stop_hit(side, entry, price, entry_atr, trail_extreme)
            if reason:
                return reason

        reason = self.stop_target_hit(
            side, entry, price, entry_atr, trailing_active=trailing_active,
        )
        if reason:
            return reason
        if self.exit_signal(df, side):
            return "RSI mid-line exit"
        if self.vwap_breakdown(df, side):
            return "VWAP breakdown"
        return None

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        raise NotImplementedError

    def entry_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        result = self.analyze(df, symbol)
        return result.signal if result else Signal.NONE

    def exit_signal(self, df: pd.DataFrame, side: str) -> bool:
        rsi = self.current_rsi(df)
        if rsi is None:
            return False
        if side == "LONG" and rsi >= Config.RSI_EXIT:
            return True
        if side == "SHORT" and rsi <= Config.RSI_EXIT:
            return True
        return False

    def precompute_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _base_screen_fields(self, df: pd.DataFrame, symbol: str) -> dict | None:
        if df is None or len(df) < self.min_bars():
            return None
        rsi = self.current_rsi(df)
        if rsi is None:
            return None
        vol_ma = float(df["vol_ma"].iloc[-1]) if "vol_ma" in df.columns else float(
            df["volume"].rolling(Config.VOLUME_MA_LEN).mean().iloc[-1]
        )
        last_vol = float(df["volume"].iloc[-1])
        close = float(df["close"].iloc[-1])
        bar_dt = df.iloc[-1]["datetime"]
        if hasattr(bar_dt, "to_pydatetime"):
            bar_dt = bar_dt.to_pydatetime()
        return {
            "symbol": symbol,
            "rsi": rsi,
            "volume": last_vol,
            "volume_ma": vol_ma,
            "close": close,
            "vwap": self.current_vwap(df),
            "atr": self.current_atr(df),
            "adx": self.current_adx(df),
            "bar_dt": bar_dt,
            **self._pivot_screen_fields(df),
        }

    def _pivot_screen_fields(self, df: pd.DataFrame) -> dict[str, float | None]:
        levels = self.current_pivot_levels(df)
        if levels is None:
            return {
                "pivot_pp": None,
                "pivot_r1": None,
                "pivot_r2": None,
                "pivot_r3": None,
                "pivot_s1": None,
                "pivot_s2": None,
                "pivot_s3": None,
            }
        return {
            "pivot_pp": levels.pp,
            "pivot_r1": levels.r1,
            "pivot_r2": levels.r2,
            "pivot_r3": levels.r3,
            "pivot_s1": levels.s1,
            "pivot_s2": levels.s2,
            "pivot_s3": levels.s3,
        }


class RsiVolumeMeanReversionStrategy(BaseStrategy):
    """RSI extremes + volume, filtered by session VWAP; ATR or fixed-% exits."""

    def min_bars(self) -> int:
        need = max(
            Config.RSI_PERIOD + Config.VOLUME_MA_LEN,
            Config.ATR_PERIOD + 1,
        )
        if Config.ADX_MR_MAX > 0 or Config.ADX_MR_MIN > 0:
            need = max(need, Config.ADX_PERIOD * 2)
        return need

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        base = self._base_screen_fields(df, symbol)
        if not base:
            return None

        if not self.adx_allows_entry(df):
            return ScreenResult(signal=Signal.NONE, **base)

        signal = Signal.NONE
        if base["rsi"] < Config.RSI_OVERSOLD and volume_confirmed(df):
            if self.vwap_allows_entry("LONG", base["close"], base["vwap"]):
                signal = Signal.BUY
        elif base["rsi"] > Config.RSI_OVERBOUGHT and volume_confirmed(df):
            if self.vwap_allows_entry("SHORT", base["close"], base["vwap"]):
                signal = Signal.SELL

        signal = self._gate_pivot_entry(signal, base["close"], df)
        return ScreenResult(signal=signal, **base)


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Opening range breakout with VWAP alignment; structural OR stop + ATR trail."""

    def min_bars(self) -> int:
        return max(
            Config.RSI_PERIOD + Config.VOLUME_MA_LEN,
            Config.ATR_PERIOD + 1,
            _orb_bar_count() + Config.VOLUME_MA_LEN,
        )

    def _or_ready(self, df: pd.DataFrame) -> bool:
        day_df = _session_day_df(df)
        return len(day_df) > _orb_bar_count()

    def _range_target_hit(
        self,
        side: str,
        entry: float,
        price: float,
        or_high: float,
        or_low: float,
    ) -> str | None:
        height = or_high - or_low
        if height <= 0:
            return None
        target_dist = height * Config.ORB_TARGET_R_MULT
        if side == "LONG" and price >= entry + target_dist:
            return f"OR target ({_pnl_pct(side, entry, price):.2f}%)"
        if side == "SHORT" and price <= entry - target_dist:
            return f"OR target ({_pnl_pct(side, entry, price):.2f}%)"
        return None

    def exit_reason(
        self,
        df: pd.DataFrame,
        side: str,
        entry: float,
        price: float,
        entry_atr: float | None = None,
        trail_extreme: float | None = None,
    ) -> str | None:
        levels = opening_range_levels(df)
        if levels:
            or_high, or_low = levels
            if Config.ORB_STOP_MODE == "range":
                if side == "LONG" and price <= or_low:
                    return f"OR stop ({_pnl_pct(side, entry, price):.2f}%)"
                if side == "SHORT" and price >= or_high:
                    return f"OR stop ({_pnl_pct(side, entry, price):.2f}%)"
            target = self._range_target_hit(side, entry, price, or_high, or_low)
            if target:
                return target

        trailing_active = False
        if Config.TRAILING_STOP_ENABLED and trail_extreme is not None:
            trailing_active = self._trailing_active(side, entry, trail_extreme, entry_atr)
            reason = self.trailing_stop_hit(side, entry, price, entry_atr, trail_extreme)
            if reason:
                return reason

        if Config.ORB_STOP_MODE == "atr":
            reason = self.stop_target_hit(
                side, entry, price, entry_atr, trailing_active=trailing_active,
            )
            if reason:
                return reason

        if Config.ORB_USE_RSI_EXIT and self.exit_signal(df, side):
            return "RSI mid-line exit"
        return None

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        base = self._base_screen_fields(df, symbol)
        if not base or not self._or_ready(df):
            return None

        levels = opening_range_levels(df)
        if not levels:
            return None
        or_high, or_low = levels
        close = base["close"]
        vwap = base["vwap"]

        signal = Signal.NONE
        vol_ok = volume_confirmed(df, Config.ORB_VOLUME_MULT)

        if (
            close > or_high
            and vol_ok
            and vwap is not None
            and close > vwap
        ):
            signal = Signal.BUY
        elif (
            close < or_low
            and vol_ok
            and vwap is not None
            and close < vwap
        ):
            signal = Signal.SELL

        signal = self._gate_pivot_entry(signal, close, df, trend=True)
        return ScreenResult(signal=signal, **base)


class VwapPullbackStrategy(BaseStrategy):
    """Pullback to session VWAP in the direction of the intraday trend."""

    def min_bars(self) -> int:
        return max(
            Config.RSI_PERIOD + Config.VOLUME_MA_LEN,
            Config.ATR_PERIOD + 1,
            Config.VWAP_PULLBACK_SLOPE_BARS + 2,
        )

    def _vwap_slope_up(self, df: pd.DataFrame) -> bool:
        vwap = compute_session_vwap(df)
        if len(vwap) < Config.VWAP_PULLBACK_SLOPE_BARS + 1:
            return True
        recent = vwap.iloc[-Config.VWAP_PULLBACK_SLOPE_BARS:]
        return float(recent.iloc[-1]) >= float(recent.iloc[0])

    def _vwap_slope_down(self, df: pd.DataFrame) -> bool:
        vwap = compute_session_vwap(df)
        if len(vwap) < Config.VWAP_PULLBACK_SLOPE_BARS + 1:
            return True
        recent = vwap.iloc[-Config.VWAP_PULLBACK_SLOPE_BARS:]
        return float(recent.iloc[-1]) <= float(recent.iloc[0])

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        base = self._base_screen_fields(df, symbol)
        if not base or len(df) < 2:
            return None

        close = base["close"]
        vwap = base["vwap"]
        if vwap is None or vwap <= 0:
            return None

        low = float(df["low"].iloc[-1])
        high = float(df["high"].iloc[-1])
        prev_low = float(df["low"].iloc[-2])
        prev_high = float(df["high"].iloc[-2])
        prev_vwap = float(compute_session_vwap(df).iloc[-2])
        touch_pct = Config.VWAP_PULLBACK_TOUCH_PCT / 100.0

        signal = Signal.NONE
        if not volume_confirmed(df):
            return ScreenResult(signal=signal, **base)

        long_touch = low <= vwap * (1 + touch_pct) or prev_low <= prev_vwap * (1 + touch_pct)
        short_touch = high >= vwap * (1 - touch_pct) or prev_high >= prev_vwap * (1 - touch_pct)

        slope_ok_long = not Config.VWAP_PULLBACK_REQUIRE_SLOPE or self._vwap_slope_up(df)
        slope_ok_short = not Config.VWAP_PULLBACK_REQUIRE_SLOPE or self._vwap_slope_down(df)

        if close > vwap and long_touch and slope_ok_long:
            signal = Signal.BUY
        elif close < vwap and short_touch and slope_ok_short:
            signal = Signal.SELL

        signal = self._gate_pivot_entry(signal, close, df, trend=True)
        return ScreenResult(signal=signal, **base)


class VwapMeanReversionStrategy(BaseStrategy):
    """Fade extended moves away from session VWAP; target VWAP touch."""

    def min_bars(self) -> int:
        return max(
            Config.RSI_PERIOD + Config.VOLUME_MA_LEN,
            Config.ATR_PERIOD + 1,
        )

    def _vwap_target_hit(self, side: str, price: float, vwap: float | None) -> str | None:
        if not Config.VWAP_MR_USE_VWAP_TARGET or vwap is None:
            return None
        if side == "SHORT" and price <= vwap:
            return "VWAP target"
        if side == "LONG" and price >= vwap:
            return "VWAP target"
        return None

    def exit_reason(
        self,
        df: pd.DataFrame,
        side: str,
        entry: float,
        price: float,
        entry_atr: float | None = None,
        trail_extreme: float | None = None,
    ) -> str | None:
        vwap = self.current_vwap(df)
        target = self._vwap_target_hit(side, price, vwap)
        if target:
            return target

        trailing_active = False
        if Config.TRAILING_STOP_ENABLED and trail_extreme is not None:
            trailing_active = self._trailing_active(side, entry, trail_extreme, entry_atr)
            reason = self.trailing_stop_hit(side, entry, price, entry_atr, trail_extreme)
            if reason:
                return reason

        reason = self.stop_target_hit(
            side, entry, price, entry_atr, trailing_active=trailing_active,
        )
        if reason:
            return reason
        if self.exit_signal(df, side):
            return "RSI mid-line exit"
        return None

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        base = self._base_screen_fields(df, symbol)
        if not base or len(df) < 2:
            return None

        close = base["close"]
        vwap = base["vwap"]
        if vwap is None or vwap <= 0:
            return None

        dist = distance_from_vwap_pct(close, vwap)
        if dist is None:
            return None

        signal = Signal.NONE
        if (
            dist > Config.VWAP_MR_MIN_DIST
            and base["rsi"] > Config.RSI_OVERBOUGHT
            and volume_contracting(df)
        ):
            signal = Signal.SELL
        elif (
            dist < -Config.VWAP_MR_MIN_DIST
            and base["rsi"] < Config.VWAP_MR_RSI_OVERSOLD
            and volume_contracting(df)
        ):
            signal = Signal.BUY

        signal = self._gate_pivot_entry(signal, close, df)
        return ScreenResult(signal=signal, **base)


class OpeningDriveFadeStrategy(BaseStrategy):
    """Short gap-up opening drive exhaustion; cover at VWAP."""

    def min_bars(self) -> int:
        return max(
            Config.RSI_PERIOD + Config.VOLUME_MA_LEN,
            Config.ATR_PERIOD + 1,
            3,
        )

    def _vwap_cover(self, side: str, price: float, vwap: float | None) -> str | None:
        if vwap is None:
            return None
        if side == "SHORT" and price <= vwap:
            return "VWAP cover"
        return None

    def exit_reason(
        self,
        df: pd.DataFrame,
        side: str,
        entry: float,
        price: float,
        entry_atr: float | None = None,
        trail_extreme: float | None = None,
    ) -> str | None:
        cover = self._vwap_cover(side, price, self.current_vwap(df))
        if cover:
            return cover

        reason = self.stop_target_hit(side, entry, price, entry_atr, trailing_active=False)
        if reason:
            return reason
        if self.exit_signal(df, side):
            return "RSI mid-line exit"
        return None

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        base = self._base_screen_fields(df, symbol)
        if not base:
            return None

        bar_dt = base["bar_dt"]
        if bar_dt is None or not open_fade_time_allowed(bar_dt):
            return ScreenResult(signal=Signal.NONE, **base)

        gap = gap_pct(df)
        if gap is None or gap < Config.OPEN_FADE_MIN_GAP:
            return ScreenResult(signal=Signal.NONE, **base)

        day_df = _session_day_df(df)
        if len(day_df) < 2:
            return ScreenResult(signal=Signal.NONE, **base)

        first = day_df.iloc[0]
        open_px = float(first["open"])
        if open_px <= 0:
            return ScreenResult(signal=Signal.NONE, **base)

        body_pct = abs(float(first["close"]) - float(first["open"])) / open_px * 100
        first_vol_ok = float(first["volume"]) >= float(base["volume_ma"]) * Config.OPEN_FADE_VOLUME_MULT
        first_bullish = float(first["close"]) > float(first["open"])
        first_rsi = float(compute_rsi(df["close"]).loc[first.name])
        if pd.isna(first_rsi):
            first_rsi = base["rsi"]

        if not (first_bullish and body_pct >= Config.OPEN_FADE_MIN_BODY_PCT and first_vol_ok):
            return ScreenResult(signal=Signal.NONE, **base)

        # Exhaustion: current bar off highs after strong open drive
        high = float(df["high"].iloc[-1])
        close = base["close"]
        exhaustion = close < high * 0.998 and base["rsi"] >= Config.OPEN_FADE_MIN_RSI - 5
        vol_spike = volume_confirmed(df, Config.OPEN_FADE_VOLUME_MULT)

        signal = Signal.SELL if exhaustion and vol_spike and base["rsi"] >= Config.OPEN_FADE_MIN_RSI - 10 else Signal.NONE
        signal = self._gate_pivot_entry(signal, close, df)
        return ScreenResult(signal=signal, **base)


class RelativeStrengthPullbackStrategy(BaseStrategy):
    """Buy strong stocks on RSI(2) pullback with contracting volume."""

    def min_bars(self) -> int:
        return max(
            Config.RSI_FAST_PERIOD + 2,
            Config.VOLUME_MA_LEN + 1,
            Config.ATR_PERIOD + 1,
        )

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        base = self._base_screen_fields(df, symbol)
        if not base or len(df) < 2:
            return None

        day_chg = session_change_pct(df)
        vwap = base["vwap"]
        atr = base["atr"]
        sess_hi = session_high(df)
        rsi_fast = current_rsi_fast(df)

        if (
            day_chg is None
            or vwap is None
            or atr is None
            or sess_hi is None
            or rsi_fast is None
        ):
            return ScreenResult(signal=Signal.NONE, **base)

        close = base["close"]
        pullback = sess_hi - close
        pullback_atr = pullback / atr if atr > 0 else 0

        signal = Signal.NONE
        if (
            Config.RS_MR_MIN_DAY_CHANGE <= day_chg <= Config.RS_MR_MAX_DAY_CHANGE
            and close > vwap
            and Config.RS_MR_PULLBACK_ATR_MIN <= pullback_atr <= Config.RS_MR_PULLBACK_ATR_MAX
            and rsi_fast < Config.RSI_FAST_OVERSOLD
            and volume_contracting(df)
            and (not Config.RS_MR_REQUIRE_BULLISH or is_bullish_candle(df))
        ):
            signal = Signal.BUY

        signal = self._gate_pivot_entry(signal, close, df)
        return ScreenResult(signal=signal, **base)


def _rsi_div_osc(df: pd.DataFrame) -> pd.Series:
    if df is not None and "rsi_div" in df.columns:
        return df["rsi_div"]
    return compute_rsi(df["close"], Config.RSI_DIV_PERIOD)


def _pivot_flags(osc: pd.Series, *, high: bool, lbL: int, lbR: int) -> np.ndarray:
    """TradingView-style pivotlow/pivothigh confirmation flags (True at confirm bar)."""
    arr = osc.to_numpy(dtype=float)
    n = len(arr)
    flags = np.zeros(n, dtype=bool)
    for i in range(lbL + lbR, n):
        p = i - lbR
        window = arr[p - lbL : i + 1]
        if np.any(np.isnan(window)):
            continue
        center = arr[p]
        if high:
            if center == np.max(window):
                flags[i] = True
        elif center == np.min(window):
            flags[i] = True
    return flags


def _prev_pivot_index(flags: np.ndarray, i: int) -> int | None:
    for j in range(i - 1, -1, -1):
        if flags[j]:
            return j
    return None


def _valuewhen_at_pivot(
    series: np.ndarray,
    flags: np.ndarray,
    i: int,
    lbR: int,
    occurrence: int = 1,
) -> float | None:
    count = 0
    for j in range(i - 1, -1, -1):
        if not flags[j]:
            continue
        count += 1
        if count == occurrence:
            p = j - lbR
            if p < 0 or p >= len(series):
                return None
            val = float(series[p])
            return None if np.isnan(val) else val
    return None


def _pivot_spacing_in_range(flags: np.ndarray, i: int, lower: int, upper: int) -> bool:
    prev = _prev_pivot_index(flags, i)
    if prev is None:
        return False
    gap = i - prev
    return lower <= gap <= upper


def _divergence_entry_at_index(
    osc: np.ndarray,
    lows: np.ndarray,
    highs: np.ndarray,
    pl: np.ndarray,
    ph: np.ndarray,
    i: int,
    *,
    lbR: int,
    range_lower: int,
    range_upper: int,
) -> Signal:
    """Return BUY/SELL at bar index i per Pine RSI Divergence Indicator logic."""
    p = i - lbR
    if p < 0:
        return Signal.NONE

    osc_p = float(osc[p])
    low_p = float(lows[p])
    high_p = float(highs[p])

    if not pl[i] and not ph[i]:
        return Signal.NONE

    long_signal = Signal.NONE
    if pl[i] and _pivot_spacing_in_range(pl, i, range_lower, range_upper):
        prev_osc = _valuewhen_at_pivot(osc, pl, i, lbR)
        prev_low = _valuewhen_at_pivot(lows, pl, i, lbR)
        if prev_osc is not None and prev_low is not None:
            bull = (
                Config.RSI_DIV_PLOT_BULL
                and low_p < prev_low
                and osc_p > prev_osc
            )
            hidden_bull = (
                Config.RSI_DIV_PLOT_HIDDEN_BULL
                and low_p > prev_low
                and osc_p < prev_osc
            )
            if bull or hidden_bull:
                long_signal = Signal.BUY

    short_signal = Signal.NONE
    if ph[i] and _pivot_spacing_in_range(ph, i, range_lower, range_upper):
        prev_osc = _valuewhen_at_pivot(osc, ph, i, lbR)
        prev_high = _valuewhen_at_pivot(highs, ph, i, lbR)
        if prev_osc is not None and prev_high is not None:
            bear = (
                Config.RSI_DIV_PLOT_BEAR
                and high_p > prev_high
                and osc_p < prev_osc
            )
            hidden_bear = (
                Config.RSI_DIV_PLOT_HIDDEN_BEAR
                and high_p < prev_high
                and osc_p > prev_osc
            )
            if bear or hidden_bear:
                short_signal = Signal.SELL

    if long_signal == Signal.BUY and short_signal == Signal.SELL:
        return Signal.NONE
    if long_signal == Signal.BUY:
        return Signal.BUY
    if short_signal == Signal.SELL:
        return Signal.SELL
    return Signal.NONE


def precompute_rsi_div_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add div_long/div_short columns once per symbol (portfolio sim / backtest)."""
    if df is None or df.empty:
        return df
    out = df
    if "rsi_div" not in out.columns:
        out = out.copy()
        out["rsi_div"] = compute_rsi(out["close"], Config.RSI_DIV_PERIOD)

    lbL = Config.RSI_DIV_PIVOT_LEFT
    lbR = Config.RSI_DIV_PIVOT_RIGHT
    start = max(
        lbL + lbR,
        Config.RSI_DIV_PERIOD + lbL + lbR,
        Config.RSI_DIV_RANGE_UPPER + lbR + 2,
    )
    osc = out["rsi_div"].to_numpy(dtype=float)
    lows = out["low"].to_numpy(dtype=float)
    highs = out["high"].to_numpy(dtype=float)
    pl = _pivot_flags(out["rsi_div"], high=False, lbL=lbL, lbR=lbR)
    ph = _pivot_flags(out["rsi_div"], high=True, lbL=lbL, lbR=lbR)

    div_long = np.zeros(len(out), dtype=bool)
    div_short = np.zeros(len(out), dtype=bool)
    for i in range(start, len(out)):
        sig = _divergence_entry_at_index(
            osc,
            lows,
            highs,
            pl,
            ph,
            i,
            lbR=lbR,
            range_lower=Config.RSI_DIV_RANGE_LOWER,
            range_upper=Config.RSI_DIV_RANGE_UPPER,
        )
        if sig == Signal.BUY:
            div_long[i] = True
        elif sig == Signal.SELL:
            div_short[i] = True

    if "div_long" not in df.columns:
        out = out.copy()
    out["div_long"] = div_long
    out["div_short"] = div_short
    return out


def _divergence_entry_at(
    df: pd.DataFrame,
    i: int,
    *,
    lbL: int,
    lbR: int,
    range_lower: int,
    range_upper: int,
) -> Signal:
    """Return BUY/SELL at bar index i (fallback when div_* columns missing)."""
    if i < lbL + lbR:
        return Signal.NONE

    if "div_long" in df.columns and "div_short" in df.columns:
        if df["div_long"].iloc[i]:
            return Signal.BUY
        if df["div_short"].iloc[i]:
            return Signal.SELL
        return Signal.NONE

    osc = _rsi_div_osc(df).to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    pl = _pivot_flags(pd.Series(osc), high=False, lbL=lbL, lbR=lbR)
    ph = _pivot_flags(pd.Series(osc), high=True, lbL=lbL, lbR=lbR)
    return _divergence_entry_at_index(
        osc, lows, highs, pl, ph, i,
        lbR=lbR, range_lower=range_lower, range_upper=range_upper,
    )


class RsiDivergenceStrategy(BaseStrategy):
    """RSI pivot divergence entries (Pine RSI Divergence Indicator port); RSI-level take profit."""

    def min_bars(self) -> int:
        return max(
            Config.RSI_DIV_PERIOD + Config.RSI_DIV_PIVOT_LEFT + Config.RSI_DIV_PIVOT_RIGHT,
            Config.RSI_DIV_RANGE_UPPER + Config.RSI_DIV_PIVOT_RIGHT + 2,
            Config.RSI_DIV_ATR_LEN + 1 if Config.RSI_DIV_SL_TYPE == "ATR" else 0,
        )

    def current_rsi(self, df: pd.DataFrame) -> float | None:
        if df is None or len(df) < Config.RSI_DIV_PERIOD + 1:
            return None
        osc = _rsi_div_osc(df)
        val = float(osc.iloc[-1])
        return None if pd.isna(val) else val

    def _div_trailing_stop_hit(
        self,
        side: str,
        entry: float,
        price: float,
        low: float,
        high: float,
        entry_atr: float | None,
        trail_extreme: float | None,
    ) -> str | None:
        if Config.RSI_DIV_SL_TYPE == "NONE" or trail_extreme is None:
            return None
        if Config.RSI_DIV_SL_TYPE == "ATR":
            if entry_atr is None or entry_atr <= 0:
                return None
            sl_val = Config.RSI_DIV_STOP_LOSS_PCT * entry_atr
        else:
            sl_val = price * Config.RSI_DIV_STOP_LOSS_PCT / 100.0
        if side == "LONG":
            level = trail_extreme - sl_val
            if low <= level:
                return f"RSI div trail ({_pnl_pct(side, entry, price):.2f}%)"
        else:
            level = trail_extreme + sl_val
            if high >= level:
                return f"RSI div trail ({_pnl_pct(side, entry, price):.2f}%)"
        return None

    def exit_reason(
        self,
        df: pd.DataFrame,
        side: str,
        entry: float,
        price: float,
        entry_atr: float | None = None,
        trail_extreme: float | None = None,
    ) -> str | None:
        rsi = self.current_rsi(df)
        if rsi is not None:
            if side == "LONG" and rsi >= Config.RSI_DIV_TP_RSI:
                return f"RSI TP ({rsi:.1f})"
            short_tp = 100.0 - Config.RSI_DIV_TP_RSI
            if side == "SHORT" and rsi <= short_tp:
                return f"RSI TP ({rsi:.1f})"

        if trail_extreme is not None and len(df) >= 1:
            low = float(df["low"].iloc[-1])
            high = float(df["high"].iloc[-1])
            reason = self._div_trailing_stop_hit(
                side, entry, price, low, high, entry_atr, trail_extreme,
            )
            if reason:
                return reason

        if Config.USE_ATR_EXITS:
            reason = self.stop_target_hit(side, entry, price, entry_atr, trailing_active=False)
            if reason:
                return reason
        return None

    def exit_signal(self, df: pd.DataFrame, side: str) -> bool:
        return False

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        if df is None or len(df) < self.min_bars():
            return None

        rsi = self.current_rsi(df)
        if rsi is None:
            return None

        close = float(df["close"].iloc[-1])
        bar_dt = df.iloc[-1]["datetime"]
        if hasattr(bar_dt, "to_pydatetime"):
            bar_dt = bar_dt.to_pydatetime()

        i = len(df) - 1
        lbL = Config.RSI_DIV_PIVOT_LEFT
        lbR = Config.RSI_DIV_PIVOT_RIGHT
        signal = _divergence_entry_at(
            df,
            i,
            lbL=lbL,
            lbR=lbR,
            range_lower=Config.RSI_DIV_RANGE_LOWER,
            range_upper=Config.RSI_DIV_RANGE_UPPER,
        )

        vol_ma = float(df["vol_ma"].iloc[-1]) if "vol_ma" in df.columns else float(
            df["volume"].rolling(Config.VOLUME_MA_LEN).mean().iloc[-1]
        )
        last_vol = float(df["volume"].iloc[-1])

        signal = self._gate_pivot_entry(signal, close, df)

        return ScreenResult(
            symbol=symbol,
            rsi=rsi,
            volume=last_vol,
            volume_ma=vol_ma,
            close=close,
            signal=signal,
            vwap=self.current_vwap(df),
            atr=self.current_atr(df),
            adx=self.current_adx(df),
            bar_dt=bar_dt,
            **self._pivot_screen_fields(df),
        )


class ZpDmiConfluenceStrategy(BaseStrategy):
    """ZPayab DIY builder: DMI (ADX) lead + RQK, VWAP, Chandelier, MACD, volume filters."""

    def min_bars(self) -> int:
        return max(
            Config.ZP_DMI_DI_LEN * 2,
            Config.ZP_MACD_SLOW + Config.ZP_MACD_SIGNAL + 2,
            Config.ZP_CE_LEN + 2,
            Config.ZP_RQK_X0 + 3,
            Config.ZP_VOL_MA_LEN + 2,
        )

    def precompute_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return precompute_zp_dmi_signals(df)

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        base = self._base_screen_fields(df, symbol)
        if not base:
            return None

        signal = Signal.NONE
        if "zp_long" in df.columns and "zp_short" in df.columns:
            if bool(df["zp_long"].iloc[-1]):
                signal = Signal.BUY
            elif bool(df["zp_short"].iloc[-1]):
                signal = Signal.SELL
        else:
            enriched = precompute_zp_dmi_signals(df)
            if bool(enriched["zp_long"].iloc[-1]):
                signal = Signal.BUY
            elif bool(enriched["zp_short"].iloc[-1]):
                signal = Signal.SELL

        signal = self._gate_pivot_entry(signal, base["close"], df, trend=True)
        return ScreenResult(signal=signal, **base)


class VstAiStrategy(BaseStrategy):
    """Zeiierman Volume SuperTrend AI — KNN-classified volume SuperTrend signals."""

    def min_bars(self) -> int:
        n = max(Config.VST_K, Config.VST_N)
        return max(
            Config.VST_LEN + 2,
            Config.VST_PRICE_LEN + n + 1,
            Config.VST_ST_LEN + n + 1,
        )

    def precompute_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return precompute_vst_ai_signals(df)

    def exit_reason(
        self,
        df: pd.DataFrame,
        side: str,
        entry: float,
        price: float,
        entry_atr: float | None = None,
        trail_extreme: float | None = None,
    ) -> str | None:
        if Config.VST_EXIT_ON_FLIP and df is not None and len(df) >= 2:
            if "vst_label" not in df.columns or "vst_direction" not in df.columns:
                df = precompute_vst_ai_signals(df)
            label = float(df["vst_label"].iloc[-1])
            direction = int(df["vst_direction"].iloc[-1])
            if side == "LONG" and (_vst_label_bearish(label) or direction == 1):
                return "VST AI flip"
            if side == "SHORT" and (_vst_label_bullish(label) or direction == -1):
                return "VST AI flip"

        trailing_active = False
        if Config.TRAILING_STOP_ENABLED and trail_extreme is not None:
            trailing_active = self._trailing_active(side, entry, trail_extreme, entry_atr)
            reason = self.trailing_stop_hit(side, entry, price, entry_atr, trail_extreme)
            if reason:
                return reason

        reason = self.stop_target_hit(
            side, entry, price, entry_atr, trailing_active=trailing_active,
        )
        if reason:
            return reason
        if self.exit_signal(df, side):
            return "RSI mid-line exit"
        return None

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        base = self._base_screen_fields(df, symbol)
        if not base:
            return None

        signal = Signal.NONE
        if "vst_long" in df.columns and "vst_short" in df.columns:
            if bool(df["vst_long"].iloc[-1]):
                signal = Signal.BUY
            elif bool(df["vst_short"].iloc[-1]):
                signal = Signal.SELL
        else:
            enriched = precompute_vst_ai_signals(df)
            if bool(enriched["vst_long"].iloc[-1]):
                signal = Signal.BUY
            elif bool(enriched["vst_short"].iloc[-1]):
                signal = Signal.SELL

        signal = self._gate_pivot_entry(signal, base["close"], df, trend=True)
        return ScreenResult(signal=signal, **base)


class SbpTmStrategy(BaseStrategy):
    """SBP Trend & Momentum — Pine INTRADAY/SCALPING/SWING entry; ATR trail exit at position level."""

    _SBP_ATR_LEN = 21

    def min_bars(self) -> int:
        base_len, gap_bars = _sbp_base_len_gap(Config.SBP_TRADE_MODE)
        return max(base_len + 25, 30, gap_bars + 10)

    def precompute_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return precompute_sbp_signals(df)

    @staticmethod
    def update_trail_extreme(
        side: str,
        extreme: float | None,
        high: float,
        low: float,
        *,
        close: float | None = None,
        atr: float | None = None,
    ) -> float:
        """Store Pine ATR trail level in trail_extreme (not price high/low)."""
        if close is None or atr is None or atr <= 0:
            if extreme is not None:
                return extreme
            return close if close is not None else (high if side == "LONG" else low)

        mult = Config.SBP_TRAIL_ATR_MULT
        if side == "LONG":
            candidate = close - atr * mult
            if extreme is None or extreme >= close - 1e-9:
                return candidate
            return max(extreme, candidate)
        candidate = close + atr * mult
        if extreme is None or extreme <= close + 1e-9:
            return candidate
        return min(extreme, candidate)

    def _sbp_trail_atr(self, df: pd.DataFrame) -> float | None:
        if df is None or len(df) < self._SBP_ATR_LEN + 1:
            return None
        atr = compute_atr(df, self._SBP_ATR_LEN)
        val = float(atr.iloc[-1])
        return val if not np.isnan(val) and val > 0 else None

    def current_atr(self, df: pd.DataFrame) -> float | None:
        return self._sbp_trail_atr(df)

    def exit_reason(
        self,
        df: pd.DataFrame,
        side: str,
        entry: float,
        price: float,
        entry_atr: float | None = None,
        trail_extreme: float | None = None,
    ) -> str | None:
        if Config.SBP_USE_TRAIL_EXIT and trail_extreme is not None and df is not None and len(df):
            bar_low = float(df["low"].iloc[-1])
            bar_high = float(df["high"].iloc[-1])
            if side == "LONG" and bar_low <= trail_extreme:
                return f"SBP trail ({_pnl_pct(side, entry, price):.2f}%)"
            if side == "SHORT" and bar_high >= trail_extreme:
                return f"SBP trail ({_pnl_pct(side, entry, price):.2f}%)"
            return None

        trailing_active = False
        if Config.TRAILING_STOP_ENABLED and trail_extreme is not None:
            trailing_active = self._trailing_active(side, entry, trail_extreme, entry_atr)
            reason = self.trailing_stop_hit(side, entry, price, entry_atr, trail_extreme)
            if reason:
                return reason

        reason = self.stop_target_hit(
            side, entry, price, entry_atr, trailing_active=trailing_active,
        )
        if reason:
            return reason
        if self.exit_signal(df, side):
            return "RSI mid-line exit"
        if self.vwap_breakdown(df, side):
            return "VWAP breakdown"
        return None

    def exit_signal(self, df: pd.DataFrame, side: str) -> bool:
        return False

    def analyze(self, df: pd.DataFrame, symbol: str) -> ScreenResult | None:
        base = self._base_screen_fields(df, symbol)
        if not base:
            return None

        signal = Signal.NONE
        if "sbp_long" in df.columns and "sbp_short" in df.columns:
            if bool(df["sbp_long"].iloc[-1]):
                signal = Signal.BUY
            elif bool(df["sbp_short"].iloc[-1]):
                signal = Signal.SELL
        else:
            enriched = precompute_sbp_signals(df)
            if bool(enriched["sbp_long"].iloc[-1]):
                signal = Signal.BUY
            elif bool(enriched["sbp_short"].iloc[-1]):
                signal = Signal.SELL

        return ScreenResult(signal=signal, **base)


STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "rsi_mr": RsiVolumeMeanReversionStrategy,
    "orb": OpeningRangeBreakoutStrategy,
    "vwap_pullback": VwapPullbackStrategy,
    "vwap_mr": VwapMeanReversionStrategy,
    "open_fade": OpeningDriveFadeStrategy,
    "rs_mr": RelativeStrengthPullbackStrategy,
    "rsi_div": RsiDivergenceStrategy,
    "zp_dmi": ZpDmiConfluenceStrategy,
    "vst_ai": VstAiStrategy,
    "sbp_tm": SbpTmStrategy,
}


def get_strategy(name: str | None = None) -> BaseStrategy:
    key = (name or Config.STRATEGY).lower().strip()
    cls = STRATEGY_REGISTRY.get(key)
    if cls is None:
        valid = ", ".join(sorted(STRATEGY_REGISTRY))
        raise ValueError(f"Unknown strategy '{key}'. Choose from: {valid}")
    return cls()


def list_strategies() -> list[str]:
    return sorted(STRATEGY_REGISTRY.keys())
