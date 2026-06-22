#!/usr/bin/env python3
"""Portfolio bake-off: compare rsi_mr variants and new strategies on T2 cache."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator

import pandas as pd

from intraday_agent.config import Config
from intraday_agent.learning.metrics import summarize_trades
from intraday_agent.learning.portfolio_sim import simulate_portfolio
from intraday_agent.learning.research_data import (
    build_regime,
    init_research_session,
    load_symbol_dfs,
    normalize_source,
    source_label,
)
from intraday_agent.learning.walk_forward import unique_trading_dates
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import BaseStrategy, get_strategy, list_strategies

logger = logging.getLogger(__name__)

T1_SYMBOLS = ["RELIANCE", "SBIN", "TCS", "HDFCBANK", "INFY"]
T2_SYMBOLS = T1_SYMBOLS + [
    "ICICIBANK", "KOTAKBANK", "AXISBANK", "LT", "ITC", "BHARTIARTL", "HINDUNILVR",
    "MARUTI", "TATASTEEL", "TATACONSUM", "WIPRO", "HCLTECH", "TECHM", "SUNPHARMA",
    "NTPC", "ONGC", "POWERGRID", "TITAN", "M&M", "BAJFINANCE", "ASIANPAINT",
    "ULTRACEMCO", "JSWSTEEL", "INDUSINDBK", "COALINDIA",
]

# Pre-registered baseline (180d T2 portfolio, Jun 2026 research run)
BASELINE_NET = -5290.0
BASELINE_SHARPE = -2.655
BASELINE_TRADES = 146
MIN_TRADES_GATE = max(1, int(BASELINE_TRADES * 0.30))

BAKEOFF_CANDIDATES: list[dict[str, Any]] = [
    {
        "key": "rsi_mr_baseline",
        "strategy": "rsi_mr",
        "overrides": {},
        "note": "Current tuned short-only profile",
    },
    {
        "key": "rsi_mr_adx_12_18",
        "strategy": "rsi_mr",
        "overrides": {"ADX_MR_MIN": 12.0, "ADX_MR_MAX": 18.0},
    },
    {
        "key": "rsi_mr_adx_10_15",
        "strategy": "rsi_mr",
        "overrides": {"ADX_MR_MIN": 10.0, "ADX_MR_MAX": 15.0},
    },
    {
        "key": "rsi_mr_adx_15_20",
        "strategy": "rsi_mr",
        "overrides": {"ADX_MR_MIN": 15.0, "ADX_MR_MAX": 20.0},
    },
    {
        "key": "rsi_mr_both_band_12_18",
        "strategy": "rsi_mr",
        "overrides": {
            "REGIME_FILTER_ENABLED": True,
            "ADX_MR_MIN": 12.0,
            "ADX_MR_MAX": 18.0,
        },
    },
    {
        "key": "vwap_mr",
        "strategy": "vwap_mr",
        "overrides": {"ALLOW_LONG": False, "ALLOW_SHORT": True},
    },
    {
        "key": "open_fade",
        "strategy": "open_fade",
        "overrides": {"ALLOW_LONG": False, "ALLOW_SHORT": True},
    },
    {
        "key": "rs_mr",
        "strategy": "rs_mr",
        "overrides": {"ALLOW_LONG": True, "ALLOW_SHORT": False},
    },
    {
        "key": "rsi_div",
        "strategy": "rsi_div",
        "overrides": {
            "USE_ATR_EXITS": False,
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
            "RSI_DIV_SL_TYPE": "NONE",
        },
    },
    {
        "key": "rsi_div_short",
        "strategy": "rsi_div",
        "overrides": {
            "ALLOW_LONG": False,
            "ALLOW_SHORT": True,
            "RSI_DIV_PLOT_BULL": False,
            "RSI_DIV_PLOT_HIDDEN_BULL": False,
            "USE_ATR_EXITS": False,
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
            "RSI_DIV_SL_TYPE": "NONE",
        },
    },
    {
        "key": "zp_dmi",
        "strategy": "zp_dmi",
        "overrides": {
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
        },
    },
    {
        "key": "zp_dmi_short",
        "strategy": "zp_dmi",
        "overrides": {
            "ALLOW_LONG": False,
            "ALLOW_SHORT": True,
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
        },
    },
    {
        "key": "zp_dmi_sd",
        "strategy": "zp_dmi",
        "overrides": {
            "ZP_SD_FILTER_ENABLED": True,
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
        },
    },
    {
        "key": "zp_dmi_sd_short",
        "strategy": "zp_dmi",
        "overrides": {
            "ALLOW_LONG": False,
            "ALLOW_SHORT": True,
            "ZP_SD_FILTER_ENABLED": True,
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
        },
    },
    {
        "key": "vst_ai",
        "strategy": "vst_ai",
        "overrides": {
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
        },
    },
    {
        "key": "vst_ai_short",
        "strategy": "vst_ai",
        "overrides": {
            "ALLOW_LONG": False,
            "ALLOW_SHORT": True,
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
        },
    },
    {
        "key": "rsi_mr_paper_stack",
        "strategy": "rsi_mr",
        "overrides": {
            "PIVOT_FILTER_ENABLED": True,
            "PIVOT_FILTER_MODE": "proximity",
            "PIVOT_TOUCH_PCT": 0.35,
            "RSI_OVERBOUGHT": 80.0,
            "ENTRY_CUTOFF_TIME": "14:00",
            "EXCLUDED_SYMBOLS": frozenset({"ONGC", "SBIN", "BAJFINANCE"}),
            "ALLOW_LONG": False,
            "ALLOW_SHORT": True,
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
            "ATR_TARGET_MULT": 3.5,
            "ATR_STOP_MULT": 1.5,
        },
        "note": "Phase sprint paper stack (primary SBP gate)",
    },
    {
        "key": "sbp_tm_short",
        "strategy": "sbp_tm",
        "overrides": {
            "ALLOW_LONG": False,
            "ALLOW_SHORT": True,
            "TRAILING_STOP_ENABLED": False,
            "USE_ATR_EXITS": False,
            "SBP_USE_TRAIL_EXIT": True,
            "VWAP_FILTER_ENABLED": False,
            "VWAP_EXIT_ENABLED": False,
        },
    },
]


@contextmanager
def config_override(**overrides: Any) -> Iterator[None]:
    saved = {k: getattr(Config, k) for k in overrides}
    try:
        for k, v in overrides.items():
            setattr(Config, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(Config, k, v)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Four-track strategy portfolio bake-off")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--tier", choices=("t1", "t2"), default="t2")
    parser.add_argument("--source", type=str, default="", help="cache | angel | yahoo")
    parser.add_argument(
        "--candidates",
        type=str,
        default="",
        help="Comma subset of bake-off keys (default: all)",
    )
    parser.add_argument("--output", type=str, default="data/research/strategy_bakeoff.json")
    parser.add_argument("--verdict-path", type=str, default="data/research/strategy_bakeoff_verdict.md")
    parser.add_argument("--rolling-folds", type=int, default=4)
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=20)
    parser.add_argument("--skip-rolling", action="store_true")
    return parser.parse_args()


def _slice_by_dates(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    dates = pd.to_datetime(df["datetime"]).dt.date
    out = df.loc[(dates >= start) & (dates <= end)].copy()
    return out.reset_index(drop=True)


def run_portfolio_sim(
    symbol_dfs: dict[str, pd.DataFrame],
    strategy: BaseStrategy,
    *,
    entry_from: date | None = None,
    entry_to: date | None = None,
    regime: Any,
    source: str,
) -> list:
    windowed = symbol_dfs
    if entry_from or entry_to:
        windowed = {}
        for sym, df in symbol_dfs.items():
            start = entry_from or pd.to_datetime(df["datetime"]).dt.date.min()
            end = entry_to or pd.to_datetime(df["datetime"]).dt.date.max()
            sliced = _slice_by_dates(df, start, end)
            if not sliced.empty:
                windowed[sym] = sliced
    return simulate_portfolio(
        windowed,
        strategy=strategy,
        journal=None,
        entry_from=entry_from,
        entry_to=entry_to,
        source=source,
        regime=regime,
    )


def rolling_walk_forward(
    symbol_dfs: dict[str, pd.DataFrame],
    strategy: BaseStrategy,
    *,
    folds: int,
    train_days: int,
    test_days: int,
    regime: Any,
    key: str,
) -> dict[str, Any]:
    sample = next(iter(symbol_dfs.values()))
    dates = unique_trading_dates(sample)
    fold_size = train_days + test_days
    if len(dates) < fold_size:
        raise ValueError(f"Need at least {fold_size} trading days, have {len(dates)}")
    if len(dates) < fold_size * folds:
        folds = max(1, len(dates) // fold_size)
        logger.warning("Reduced rolling folds to %d (available days=%d)", folds, len(dates))

    results = []
    start_idx = 0
    for fold in range(folds):
        is_end = start_idx + train_days
        oos_end = is_end + test_days
        if oos_end > len(dates):
            break
        is_range = (dates[start_idx], dates[is_end - 1])
        oos_range = (dates[is_end], dates[oos_end - 1])
        is_trades = run_portfolio_sim(
            symbol_dfs,
            strategy,
            entry_from=is_range[0],
            entry_to=is_range[1],
            regime=regime,
            source=f"bakeoff_{key}_is_{fold}",
        )
        oos_trades = run_portfolio_sim(
            symbol_dfs,
            strategy,
            entry_from=oos_range[0],
            entry_to=oos_range[1],
            regime=regime,
            source=f"bakeoff_{key}_oos_{fold}",
        )
        results.append({
            "fold": fold,
            "is_range": [str(is_range[0]), str(is_range[1])],
            "oos_range": [str(oos_range[0]), str(oos_range[1])],
            "is": summarize_trades(is_trades),
            "oos": summarize_trades(oos_trades),
        })
        start_idx += test_days

    positive_oos = sum(1 for r in results if r["oos"]["net_pnl_rs"] > 0)
    return {
        "folds": results,
        "positive_oos_folds": positive_oos,
        "total_folds": len(results),
        "pass": positive_oos > len(results) / 2 if results else False,
    }


def _resolve_symbols(tier: str) -> list[str]:
    return T2_SYMBOLS if tier == "t2" else T1_SYMBOLS


def evaluate_gates(stats: dict[str, Any], rolling: dict[str, Any] | None = None) -> dict[str, Any]:
    trades = int(stats.get("trades") or 0)
    net = float(stats.get("net_pnl_rs") or 0)
    sharpe = float(stats.get("sharpe") or 0)
    pass_oos = True
    if rolling and "error" not in rolling:
        pass_oos = bool(rolling.get("pass"))
    elif rolling and "error" in rolling:
        pass_oos = False
    return {
        "pass_net": net > BASELINE_NET,
        "pass_sharpe": sharpe > BASELINE_SHARPE,
        "pass_trades": trades >= MIN_TRADES_GATE,
        "pass_oos": pass_oos,
        "pass_all": (
            net > BASELINE_NET
            and sharpe > BASELINE_SHARPE
            and trades >= MIN_TRADES_GATE
            and pass_oos
        ),
        "baseline_net": BASELINE_NET,
        "baseline_sharpe": BASELINE_SHARPE,
        "min_trades": MIN_TRADES_GATE,
    }


def write_verdict(path: str, report: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# Strategy Bake-off Verdict",
        "",
        f"Window: {report.get('days')}d | Symbols: {report.get('symbol_count')} | "
        f"Data: {report.get('data_source')} | Engine: portfolio",
        "",
        f"Baseline (rsi_mr): net ₹{BASELINE_NET:,.0f} | Sharpe {BASELINE_SHARPE:.3f} | "
        f"trades {BASELINE_TRADES}",
        "",
        f"Gates: net > baseline, Sharpe > baseline, trades ≥ {MIN_TRADES_GATE} (30% of baseline), "
        f"≥50% rolling OOS folds positive",
        "",
        "## Results",
        "",
        "| Candidate | Trades | Net ₹ | Sharpe | OOS folds | Pass |",
        "|-----------|--------|-------|--------|-----------|------|",
    ]
    for key, row in report.get("candidates", {}).items():
        g = row.get("gates", {})
        rolling = row.get("rolling") or {}
        oos_txt = "—"
        if rolling and "error" not in rolling:
            oos_txt = f"{rolling.get('positive_oos_folds', 0)}/{rolling.get('total_folds', 0)}"
        if key in WINNER_EXCLUDE:
            pass_txt = "control"
        else:
            pass_txt = "PASS" if g.get("pass_all") else "FAIL"
        lines.append(
            f"| **{key}** | {row['stats'].get('trades', 0)} | "
            f"₹{row['stats'].get('net_pnl_rs', 0):,.0f} | "
            f"{row['stats'].get('sharpe', 0):.3f} | {oos_txt} | "
            f"{pass_txt} |"
        )
    lines.extend(["", f"## Decision", "", report.get("decision", ""), ""])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


WINNER_EXCLUDE = frozenset({"rsi_mr_baseline"})


def decide(report: dict[str, Any]) -> str:
    passed = [
        (k, v) for k, v in report.get("candidates", {}).items()
        if k not in WINNER_EXCLUDE and v.get("gates", {}).get("pass_all")
    ]
    if not passed:
        baseline = report.get("candidates", {}).get("rsi_mr_baseline", {})
        bstats = baseline.get("stats", {})
        return (
            "FAIL — no candidate beats baseline on all gates. "
            f"Baseline rsi_mr: net ₹{bstats.get('net_pnl_rs', BASELINE_NET):,.0f}, "
            f"Sharpe {bstats.get('sharpe', BASELINE_SHARPE):.3f}, "
            f"{bstats.get('trades', BASELINE_TRADES)} trades. "
            "Keep current paper stack; shelve new entry strategies until exits/guards improve."
        )
    ranked = sorted(
        passed,
        key=lambda x: (x[1]["stats"].get("sharpe", 0), x[1]["stats"].get("net_pnl_rs", 0)),
        reverse=True,
    )
    winner, row = ranked[0]
    s = row["stats"]
    return (
        f"PASS — **{winner}** ({row.get('strategy')}) net ₹{s.get('net_pnl_rs', 0):,.0f}, "
        f"Sharpe {s.get('sharpe', 0):.3f}, {s.get('trades', 0)} trades. "
        f"Paper-test only; do not enable live without walk-forward on paper journal."
    )


def main() -> int:
    args = parse_args()
    setup_logger()

    source = normalize_source(args.source or None)
    _, broker = init_research_session(source)
    symbols = _resolve_symbols(args.tier)

    symbol_dfs = load_symbol_dfs(symbols, args.days, source, broker=broker)
    if not symbol_dfs:
        print("Error: no candle data", file=sys.stderr)
        return 1

    keys_filter = {k.strip() for k in args.candidates.split(",") if k.strip()}
    candidates = BAKEOFF_CANDIDATES
    if keys_filter:
        candidates = [c for c in candidates if c["key"] in keys_filter]

    report: dict[str, Any] = {
        "days": args.days,
        "data_source": source,
        "symbol_count": len(symbol_dfs),
        "candidates": {},
    }

    print(f"\n=== Strategy bake-off ({source_label(source)}, {len(symbol_dfs)} symbols) ===\n")

    for cand in candidates:
        key = cand["key"]
        strat_name = cand["strategy"]
        if strat_name not in list_strategies():
            logger.warning("Skip %s — unknown strategy %s", key, strat_name)
            continue

        overrides = dict(cand.get("overrides") or {})
        logger.info("Running %s (strategy=%s)", key, strat_name)
        with config_override(**overrides):
            strategy = get_strategy(strat_name)
            regime = build_regime(
                args.days,
                source,
                Config.REGIME_FILTER_ENABLED,
                broker=broker,
            )
            trades = run_portfolio_sim(
                symbol_dfs,
                strategy,
                regime=regime,
                source=f"bakeoff_{key}",
            )
            stats = summarize_trades(trades)
            rolling: dict[str, Any] = {}
            if not args.skip_rolling:
                try:
                    rolling = rolling_walk_forward(
                        symbol_dfs,
                        strategy,
                        folds=args.rolling_folds,
                        train_days=args.train_days,
                        test_days=args.test_days,
                        regime=regime,
                        key=key,
                    )
                except ValueError as exc:
                    logger.warning("Rolling WF skipped for %s: %s", key, exc)
                    rolling = {"error": str(exc)}
            gates = evaluate_gates(stats, rolling)

        report["candidates"][key] = {
            "strategy": strat_name,
            "overrides": overrides,
            "note": cand.get("note"),
            "stats": stats,
            "rolling": rolling,
            "gates": gates,
        }
        oos_note = ""
        if rolling and "error" not in rolling:
            oos_note = f" oos={rolling.get('positive_oos_folds')}/{rolling.get('total_folds')}"
        print(
            f"{key:<28} trades={stats.get('trades', 0):>4} "
            f"net=₹{stats.get('net_pnl_rs', 0):>8,.0f} "
            f"sharpe={stats.get('sharpe', 0):>7.3f} "
            f"{'PASS' if gates['pass_all'] else 'FAIL'}{oos_note}"
        )

    report["decision"] = decide(report)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    write_verdict(args.verdict_path, report)

    print(f"\nDecision: {report['decision']}")
    print(f"JSON: {args.output}")
    print(f"Verdict: {args.verdict_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
