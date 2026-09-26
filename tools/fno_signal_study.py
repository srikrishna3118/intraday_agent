#!/usr/bin/env python3
"""Angel-only NIFTY 5-min study: 9:20 EMA premise + expiry remaining-vol model."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from intraday_agent.config import Config
from intraday_agent.instruments_fno import (
    expiry_cycle_day,
    historical_expiry_era,
    historical_weekly_expiry,
)
from intraday_agent.learning.candle_store import load as load_cache
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy_fno import (
    forecast_remaining_log_move,
    realized_variance,
    session_slice,
    strike_distance_points,
    to_ist_naive,
    trend_state,
)

OUT_MD = os.path.join("data", "research", "fno_signal_study.md")
OUT_JSON = os.path.join("data", "research", "fno_signal_study.json")
# Angel parquet cache is UTC-naive (09:15 IST = 03:45). Live getCandleData is IST.
CACHE_TZ = "utc"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NIFTY F&O spot-signal study")
    parser.add_argument("--nifty-interval", default="FIVE_MINUTE")
    parser.add_argument("--vix-interval", default="FIVE_MINUTE")
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument(
        "--prefetch",
        action="store_true",
        help="Fetch missing Angel history before running",
    )
    return parser.parse_args()


def _prepare(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["ist"] = to_ist_naive(out["datetime"], naive_tz=CACHE_TZ)
    out["session"] = pd.to_datetime(out["ist"]).dt.date
    return out.sort_values("ist").reset_index(drop=True)


def _sessions(df: pd.DataFrame) -> list[date]:
    if df.empty:
        return []
    days = sorted({d for d in df["session"].tolist() if d.weekday() < 5})
    return days


def _bar_at(df: pd.DataFrame, session: date, hhmm: dtime) -> pd.Series | None:
    bars = session_slice(df, session, hhmm, hhmm, naive_tz=CACHE_TZ)
    if bars.empty:
        window_end = (datetime.combine(session, hhmm) + timedelta(minutes=4)).time()
        bars = session_slice(df, session, hhmm, window_end, naive_tz=CACHE_TZ)
    if bars.empty:
        return None
    return bars.iloc[0]


def _last_bar(df: pd.DataFrame, session: date, end: dtime) -> pd.Series | None:
    bars = session_slice(df, session, dtime(9, 15), end, naive_tz=CACHE_TZ)
    if bars.empty:
        return None
    return bars.iloc[-1]


def _bootstrap_mean_lb(values: np.ndarray, draws: int = 2000, alpha: float = 0.05) -> float:
    rng = np.random.default_rng(42)
    if len(values) == 0:
        return float("nan")
    means = np.empty(draws)
    n = len(values)
    for i in range(draws):
        means[i] = rng.choice(values, size=n, replace=True).mean()
    return float(np.quantile(means, alpha))


def study_ema(nifty: pd.DataFrame) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for session in _sessions(nifty):
        day = nifty[nifty["session"] == session]
        if day.empty:
            continue
        lookback = nifty[
            (nifty["session"] >= session - timedelta(days=10)) & (nifty["session"] <= session)
        ]
        state = trend_state(
            lookback,
            at=datetime.combine(session, dtime(9, 15)),
            naive_tz=CACHE_TZ,
        )
        if state not in {"bull", "bear"}:
            continue
        entry = _bar_at(nifty, session, dtime(9, 15))
        exit_bar = _last_bar(nifty, session, dtime(15, 10))
        if entry is None or exit_bar is None:
            continue
        entry_px = float(entry["close"])
        exit_px = float(exit_bar["close"])
        if entry_px <= 0:
            continue
        raw = (exit_px - entry_px) / entry_px
        signed = raw if state == "bull" else -raw
        rows.append(
            {
                "session": session.isoformat(),
                "ema_state": state,
                "signed_return": signed,
                "raw_return": raw,
                "era": historical_expiry_era(session),
                "expiry_cycle_day": expiry_cycle_day(historical_weekly_expiry(session), session),
            }
        )
    if not rows:
        return {
            "n": 0,
            "mean": None,
            "bootstrap_95_lb": None,
            "first_half_mean": None,
            "second_half_mean": None,
            "pass": False,
            "reason": "no EMA-signed sessions",
        }
    signed = np.array([r["signed_return"] for r in rows], dtype=float)
    mid = len(signed) // 2
    first = signed[:mid] if mid else signed
    second = signed[mid:] if mid else signed
    mean = float(signed.mean())
    lb = _bootstrap_mean_lb(signed)
    first_mean = float(first.mean())
    second_mean = float(second.mean())
    passed = mean > 0 and lb > 0 and first_mean > 0 and second_mean > 0
    return {
        "n": int(len(signed)),
        "mean": mean,
        "mean_bps": mean * 10000,
        "bootstrap_95_lb": lb,
        "bootstrap_95_lb_bps": lb * 10000,
        "first_half_mean": first_mean,
        "second_half_mean": second_mean,
        "win_rate": float((signed > 0).mean()),
        "pass": passed,
        "gates": {
            "mean_gt_0": mean > 0,
            "bootstrap_lb_gt_0": lb > 0,
            "first_half_gt_0": first_mean > 0,
            "second_half_gt_0": second_mean > 0,
        },
        "rows_head": rows[:5],
        "rows_tail": rows[-5:],
    }


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, float]:
    beta, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
    pred = x @ beta
    resid = y - pred
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    dof = max(1, len(y) - x.shape[1])
    scale = float(np.sqrt(ss_res / dof)) if len(y) > x.shape[1] else 0.45
    return beta, r2, scale


def _design(morning_rv: np.ndarray, vix: np.ndarray) -> np.ndarray:
    return np.column_stack(
        [
            np.ones(len(morning_rv)),
            np.log(np.clip(morning_rv, 1e-12, None)),
            np.log(np.clip(vix, 1e-6, None)),
        ]
    )


def _prior_close(vix_daily: pd.DataFrame, session: date) -> float | None:
    if vix_daily.empty:
        return None
    work = vix_daily.copy()
    work["session"] = pd.to_datetime(to_ist_naive(work["datetime"], naive_tz=CACHE_TZ)).dt.date
    prior = work[work["session"] < session]
    if prior.empty:
        return None
    return float(prior.iloc[-1]["close"])


def collect_expiry_rows(nifty: pd.DataFrame, vix_daily: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for session in _sessions(nifty):
        expiry = historical_weekly_expiry(session)
        if expiry_cycle_day(expiry, session) != 0:
            continue
        morning = realized_variance(nifty, session, dtime(9, 15), dtime(11, 0), naive_tz=CACHE_TZ)
        remaining = realized_variance(nifty, session, dtime(11, 0), dtime(14, 30), naive_tz=CACHE_TZ)
        start_bar = _bar_at(nifty, session, dtime(11, 0))
        end_bar = _last_bar(nifty, session, dtime(14, 30))
        vix = _prior_close(vix_daily, session)
        if morning is None or remaining is None or start_bar is None or end_bar is None or vix is None:
            continue
        p0 = float(start_bar["close"])
        p1 = float(end_bar["close"])
        if p0 <= 0 or p1 <= 0:
            continue
        log_move = abs(math.log(p1 / p0))
        rows.append(
            {
                "session": session.isoformat(),
                "era": historical_expiry_era(session),
                "morning_rv": morning,
                "remaining_rv": remaining,
                "prior_vix": vix,
                "p1100": p0,
                "p1430": p1,
                "abs_move": abs(p1 - p0),
                "log_move": log_move,
            }
        )
    return rows


def study_expiry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 20:
        return {
            "n": len(rows),
            "oos_r2": None,
            "tail_breach_rate": None,
            "pass": False,
            "reason": "not enough expiry days",
            "model": {},
        }
    morning = np.array([r["morning_rv"] for r in rows], dtype=float)
    remaining = np.array([r["remaining_rv"] for r in rows], dtype=float)
    vix = np.array([r["prior_vix"] for r in rows], dtype=float)
    abs_move = np.array([r["abs_move"] for r in rows], dtype=float)
    spot = np.array([r["p1100"] for r in rows], dtype=float)
    y = np.log(np.clip(remaining, 1e-12, None))
    x = _design(morning, vix)

    min_train = min(80, max(20, len(rows) // 3))
    oos_log_rv = np.full(len(rows), np.nan)
    oos_log_move = np.full(len(rows), np.nan)
    oos_breach = []
    for i in range(min_train, len(rows)):
        beta, _, scale = _ols(x[:i], y[:i])
        model = {
            "intercept": float(beta[0]),
            "coef_morning_rv": float(beta[1]),
            "coef_vix": float(beta[2]),
            "resid_scale": scale,
            "t_crit": 1.2815515655446004,
        }
        oos_log_rv[i] = float((x[i] @ beta))
        log_move = forecast_remaining_log_move(morning[i], vix[i], model)
        oos_log_move[i] = log_move
        distance = strike_distance_points(spot[i], log_move)
        oos_breach.append(bool(abs_move[i] > distance))

    mask = ~np.isnan(oos_log_rv)
    if mask.sum() < 5:
        oos_r2 = None
        breach = None
    else:
        ss_res = float(((y[mask] - oos_log_rv[mask]) ** 2).sum())
        ss_tot = float(((y[mask] - y[mask].mean()) ** 2).sum())
        oos_r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        breach = float(np.mean(oos_breach)) if oos_breach else None

    beta_all, in_r2, scale_all = _ols(x, y)
    model = {
        "intercept": float(beta_all[0]),
        "coef_morning_rv": float(beta_all[1]),
        "coef_vix": float(beta_all[2]),
        "resid_scale": float(scale_all),
        "t_crit": 1.2815515655446004,
        "in_sample_r2": float(in_r2),
        "n": len(rows),
        "trained_through": rows[-1]["session"],
        "min_train": min_train,
    }
    os.makedirs(os.path.dirname(Config.FNO_EXPIRY_MODEL_PATH) or ".", exist_ok=True)
    with open(Config.FNO_EXPIRY_MODEL_PATH, "w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=2)

    by_era: dict[str, Any] = {}
    for era in ("thursday", "tuesday", "transition"):
        idx = [i for i, r in enumerate(rows) if r["era"] == era and i >= min_train]
        if not idx:
            by_era[era] = {"n_oos": 0}
            continue
        pred = oos_log_rv[idx]
        actual = y[idx]
        good = ~np.isnan(pred)
        if good.sum() < 3:
            by_era[era] = {"n_oos": int(good.sum())}
            continue
        ss_res = float(((actual[good] - pred[good]) ** 2).sum())
        ss_tot = float(((actual[good] - actual[good].mean()) ** 2).sum())
        era_r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        era_breach = []
        for i in idx:
            if np.isnan(oos_log_move[i]):
                continue
            distance = strike_distance_points(rows[i]["p1100"], float(oos_log_move[i]))
            era_breach.append(rows[i]["abs_move"] > distance)
        by_era[era] = {
            "n_oos": int(good.sum()),
            "oos_r2": era_r2,
            "tail_breach_rate": float(np.mean(era_breach)) if era_breach else None,
        }

    passed = (
        oos_r2 is not None
        and oos_r2 >= 0.2
        and breach is not None
        and breach <= 0.12
    )
    return {
        "n": len(rows),
        "oos_n": int(mask.sum()),
        "oos_r2": oos_r2,
        "tail_breach_rate": breach,
        "in_sample_r2": float(in_r2),
        "pass": passed,
        "gates": {
            "oos_r2_ge_0.2": bool(oos_r2 is not None and oos_r2 >= 0.2),
            "tail_breach_le_0.12": bool(breach is not None and breach <= 0.12),
        },
        "by_era": by_era,
        "model": model,
        "model_path": Config.FNO_EXPIRY_MODEL_PATH,
    }


def study_profile(nifty: pd.DataFrame, vix_daily: pd.DataFrame) -> dict[str, Any]:
    marks = {
        "09:20": dtime(9, 20),
        "10:00": dtime(10, 0),
        "11:15": dtime(11, 15),
    }
    shares = {k: [] for k in marks}
    gap_vs_rest: list[float] = []
    vix_vs_rv: dict[int, list[tuple[float, float]]] = {i: [] for i in range(5)}
    for session in _sessions(nifty):
        day = session_slice(nifty, session, dtime(9, 15), dtime(15, 10), naive_tz=CACHE_TZ)
        if day.empty:
            continue
        day_range = float(day["high"].max() - day["low"].min())
        if day_range <= 0:
            continue
        for label, mark in marks.items():
            part = session_slice(nifty, session, dtime(9, 15), mark, naive_tz=CACHE_TZ)
            if part.empty:
                continue
            shares[label].append(float(part["high"].max() - part["low"].min()) / day_range)
        open_bar = _bar_at(nifty, session, dtime(9, 15))
        prev = nifty[nifty["session"] < session]
        if open_bar is not None and not prev.empty:
            prev_close = float(prev.iloc[-1]["close"])
            gap = abs(float(open_bar["open"]) - prev_close)
            rest = session_slice(nifty, session, dtime(9, 20), dtime(15, 10), naive_tz=CACHE_TZ)
            rest_range = float(rest["high"].max() - rest["low"].min()) if not rest.empty else 0.0
            if rest_range > 0:
                gap_vs_rest.append(gap / rest_range)
        rv = realized_variance(nifty, session, dtime(9, 20), dtime(15, 10), naive_tz=CACHE_TZ)
        vix = _prior_close(vix_daily, session)
        cycle = expiry_cycle_day(historical_weekly_expiry(session), session)
        if rv is not None and vix is not None and 0 <= cycle <= 4:
            vix_vs_rv[cycle].append((vix, math.sqrt(rv) * 100.0))

    def _mean(xs: list[float]) -> float | None:
        return float(np.mean(xs)) if xs else None

    cycle_summary = {}
    for day, pairs in vix_vs_rv.items():
        if not pairs:
            cycle_summary[str(day)] = {"n": 0}
            continue
        vix_arr = np.array([p[0] for p in pairs])
        rv_arr = np.array([p[1] for p in pairs])
        cycle_summary[str(day)] = {
            "n": len(pairs),
            "mean_prior_vix": float(vix_arr.mean()),
            "mean_9_20_15_10_rv_pct": float(rv_arr.mean()),
            "corr_vix_rv": float(np.corrcoef(vix_arr, rv_arr)[0, 1]) if len(pairs) > 2 else None,
        }
    return {
        "range_share_by_time": {k: _mean(v) for k, v in shares.items()},
        "range_share_n": {k: len(v) for k, v in shares.items()},
        "gap_vs_rest_of_day": _mean(gap_vs_rest),
        "gap_vs_rest_n": len(gap_vs_rest),
        "vix_vs_rv_by_cycle_day": cycle_summary,
    }


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def write_markdown(payload: dict[str, Any]) -> None:
    ema = payload["ema"]
    exp = payload["expiry_model"]
    prof = payload["profile"]
    lines = [
        "# NIFTY F&O spot-signal study",
        "",
        f"**Generated:** {payload['generated_at']}",
        f"**NIFTY 5-min bars:** {payload['nifty_bars']}  |  sessions: {payload['sessions']}",
        f"**Coverage:** {payload['coverage']}",
        "",
        "## 1. 09:20 EMA direction premise (arms 2 and 3)",
        "",
        "Signal uses the completed 09:15 5-min bar. Predicted-direction return is 09:15 close → last bar ≤ 15:10.",
        "",
        f"- n = {ema.get('n', 0)}",
        f"- mean signed return = {_fmt(ema.get('mean'))} ({_fmt(ema.get('mean_bps'), 1)} bps)",
        f"- bootstrap 95% lower bound = {_fmt(ema.get('bootstrap_95_lb'))}",
        f"- first half mean = {_fmt(ema.get('first_half_mean'))}",
        f"- second half mean = {_fmt(ema.get('second_half_mean'))}",
        f"- win rate = {_fmt(ema.get('win_rate'))}",
        f"- **PASS = {ema.get('pass')}**  gates={ema.get('gates')}",
        "",
        "## 2. Expiry-day remaining-volatility model (arm 5)",
        "",
        "Walk-forward OLS: `log(remaining_rv_11:00_14:30) = a + b log(morning_rv) + c log(prior VIX)`.",
        "10% tail distance never closer than 0.4% of the 11:00 spot. Breach = |14:30−11:00| > distance.",
        "",
        f"- expiry days = {exp.get('n')}  |  OOS n = {exp.get('oos_n')}",
        f"- OOS R² (walk-forward log remaining RV) = {_fmt(exp.get('oos_r2'))}",
        f"- OOS 10% tail breach rate = {_fmt(exp.get('tail_breach_rate'))}",
        f"- in-sample R² (on remaining RV) = {_fmt(exp.get('in_sample_r2'))}",
        f"- **PASS = {exp.get('pass')}**  gates={exp.get('gates')}",
        f"- model path = `{exp.get('model_path', Config.FNO_EXPIRY_MODEL_PATH)}`",
        "",
        "### By expiry era",
        "",
    ]
    for era, stats in (exp.get("by_era") or {}).items():
        lines.append(
            f"- **{era}**: n_oos={stats.get('n_oos', 0)}  "
            f"R²={_fmt(stats.get('oos_r2'))}  "
            f"breach={_fmt(stats.get('tail_breach_rate'))}"
        )
    lines += [
        "",
        "## 3. Intraday profile",
        "",
        f"- share of day range done by 09:20 / 10:00 / 11:15: "
        f"{_fmt((prof.get('range_share_by_time') or {}).get('09:20'))} / "
        f"{_fmt((prof.get('range_share_by_time') or {}).get('10:00'))} / "
        f"{_fmt((prof.get('range_share_by_time') or {}).get('11:15'))}",
        f"- |gap| / rest-of-day range = {_fmt(prof.get('gap_vs_rest_of_day'))}",
        "",
        "India VIX (prior close) vs 09:20–15:10 realized vol by expiry-cycle day:",
        "",
    ]
    for day, stats in (prof.get("vix_vs_rv_by_cycle_day") or {}).items():
        lines.append(
            f"- cycle {day}: n={stats.get('n', 0)}  "
            f"mean VIX={_fmt(stats.get('mean_prior_vix'), 2)}  "
            f"mean RV%={_fmt(stats.get('mean_9_20_15_10_rv_pct'), 3)}  "
            f"corr={_fmt(stats.get('corr_vix_rv'))}"
        )
    lines += [
        "",
        "## 4. How this feeds the paper trial",
        "",
        "- Arms 2 and 3 (`ema920_*`) also need the EMA premise to PASS.",
        "- Arm 5 (`expiry_vol_strangle`) also needs the expiry-model premise to PASS.",
        "- Paper KILL after ~40 sessions is separate: net ≤ 0 after F&O costs, negative in either half, or DD > ₹20k.",
        "",
    ]
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def maybe_prefetch(days: int) -> None:
    from intraday_agent.broker import AngelBroker
    from intraday_agent.instruments import get_registry
    from intraday_agent.learning.research_data import prefetch_for_research

    Config.validate()
    get_registry().load()
    broker = AngelBroker()
    if not broker.login():
        raise RuntimeError("Angel login failed")
    try:
        prefetch_for_research(
            ["NIFTY", "INDIAVIX"],
            days,
            "angel",
            broker=broker,
            interval="FIVE_MINUTE",
        )
        prefetch_for_research(
            ["INDIAVIX"],
            max(days, 1500),
            "angel",
            broker=broker,
            interval="ONE_DAY",
        )
    finally:
        broker.logout()


def main() -> int:
    args = parse_args()
    setup_logger()
    if args.prefetch:
        maybe_prefetch(args.days)

    nifty = _prepare(load_cache("NIFTY", args.nifty_interval))
    vix_intraday = _prepare(load_cache("INDIAVIX", args.vix_interval))
    vix_daily = load_cache("INDIAVIX", "ONE_DAY")
    if vix_daily is None or vix_daily.empty:
        vix_daily = vix_intraday.copy() if not vix_intraday.empty else pd.DataFrame()

    coverage = "no NIFTY cache"
    if not nifty.empty:
        coverage = (
            f"{nifty['ist'].min()} → {nifty['ist'].max()} "
            f"({nifty['session'].nunique()} sessions)"
        )

    ema = study_ema(nifty)
    expiry_rows = collect_expiry_rows(nifty, vix_daily if vix_daily is not None else pd.DataFrame())
    expiry = study_expiry(expiry_rows)
    profile = study_profile(nifty, vix_daily if vix_daily is not None else pd.DataFrame())
    payload = {
        "generated_at": datetime.now().isoformat(),
        "nifty_bars": int(len(nifty)),
        "sessions": int(nifty["session"].nunique()) if not nifty.empty else 0,
        "coverage": coverage,
        "ema": ema,
        "expiry_model": expiry,
        "profile": profile,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    write_markdown(payload)
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")
    if expiry.get("model_path"):
        print(f"Wrote {expiry['model_path']}")
    print(f"EMA premise PASS={ema.get('pass')}  expiry model PASS={expiry.get('pass')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
