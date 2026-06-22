#!/usr/bin/env python3
"""Phase B research validation: ablations, sizing sweep, rolling walk-forward."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from typing import Any, Iterator

import pandas as pd

from intraday_agent.broker import AngelBroker
from intraday_agent.config import Config
from intraday_agent.instruments import get_registry
from intraday_agent.learning.backtest import simulate_symbol
from intraday_agent.learning.meta_label import MetaLabelFilter, build_dataset, train_meta_model, save_meta_model
from intraday_agent.learning.metrics import summarize_trades
from intraday_agent.learning.portfolio_sim import simulate_portfolio
from intraday_agent.learning.research_data import (
    build_regime,
    load_symbol_dfs,
    needs_angel_login,
    normalize_source,
    source_label,
)
from intraday_agent.learning.walk_forward import unique_trading_dates
from intraday_agent.logging_setup import setup_logger
from intraday_agent.market_regime import MarketRegime
from intraday_agent.strategy import get_strategy

logger = logging.getLogger(__name__)

T1_SYMBOLS = ["RELIANCE", "SBIN", "TCS", "HDFCBANK", "INFY"]
T2_SYMBOLS = T1_SYMBOLS + [
    "ICICIBANK", "KOTAKBANK", "AXISBANK", "LT", "ITC", "BHARTIARTL", "HINDUNILVR",
    "MARUTI", "TATASTEEL", "TATACONSUM", "WIPRO", "HCLTECH", "TECHM", "SUNPHARMA",
    "NTPC", "ONGC", "POWERGRID", "TITAN", "M&M", "BAJFINANCE", "ASIANPAINT",
    "ULTRACEMCO", "JSWSTEEL", "INDUSINDBK", "COALINDIA",
]

ABLATION_PRESETS: dict[str, dict[str, Any]] = {
    "base": {"REGIME_FILTER_ENABLED": False, "ADX_MR_MIN": 0.0, "ADX_MR_MAX": 0.0},
    "vix": {"REGIME_FILTER_ENABLED": True, "ADX_MR_MIN": 0.0, "ADX_MR_MAX": 0.0},
    "adx": {"REGIME_FILTER_ENABLED": False, "ADX_MR_MIN": 0.0, "ADX_MR_MAX": 20.0},
    "both": {"REGIME_FILTER_ENABLED": True, "ADX_MR_MIN": 0.0, "ADX_MR_MAX": 20.0},
    "adx_band_12_18": {"REGIME_FILTER_ENABLED": False, "ADX_MR_MIN": 12.0, "ADX_MR_MAX": 18.0},
    "adx_band_10_15": {"REGIME_FILTER_ENABLED": False, "ADX_MR_MIN": 10.0, "ADX_MR_MAX": 15.0},
    "adx_band_15_20": {"REGIME_FILTER_ENABLED": False, "ADX_MR_MIN": 15.0, "ADX_MR_MAX": 20.0},
    "both_band_12_18": {"REGIME_FILTER_ENABLED": True, "ADX_MR_MIN": 12.0, "ADX_MR_MAX": 18.0},
    "meta_label": {"REGIME_FILTER_ENABLED": False, "ADX_MR_MIN": 0.0, "ADX_MR_MAX": 0.0},
}


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
    parser = argparse.ArgumentParser(description="Phase B rsi_mr research validation")
    parser.add_argument("--days", type=int, default=252)
    parser.add_argument("--symbols", type=str, default="", help="Comma list or empty for T2")
    parser.add_argument("--tier", choices=("t1", "t2"), default="t2")
    parser.add_argument(
        "--ablations",
        type=str,
        default="base,vix,adx,both",
        help=f"Comma keys: {', '.join(ABLATION_PRESETS)}",
    )
    parser.add_argument("--sizing", type=str, default="", help="Comma CAPITAL_PER_TRADE values")
    parser.add_argument("--rolling-folds", type=int, default=4)
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=20)
    parser.add_argument("--per-symbol", action="store_true", help="Independent per-symbol sim (not portfolio)")
    parser.add_argument(
        "--source",
        type=str,
        default="",
        help="angel | yahoo | cache (default: RESEARCH_DATA_SOURCE; cache = offline parquet)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Alias for --source cache",
    )
    parser.add_argument("--output", type=str, default="data/research/rsi_mr_validation.json")
    parser.add_argument("--verdict-path", type=str, default="data/research/rsi_mr_verdict.md")
    parser.add_argument("--skip-ablations", action="store_true")
    parser.add_argument("--skip-sizing", action="store_true")
    parser.add_argument("--skip-rolling", action="store_true")
    parser.add_argument(
        "--meta-label",
        action="store_true",
        help="Include meta_label ablation (trains from journal if model missing)",
    )
    parser.add_argument("--meta-label-train", action="store_true", help="Retrain meta model before ablation")
    return parser.parse_args()


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols.strip():
        return [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    return T1_SYMBOLS if args.tier == "t1" else T2_SYMBOLS


def _slice_by_dates(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    dates = pd.to_datetime(df["datetime"]).dt.date
    out = df.loc[(dates >= start) & (dates <= end)].copy()
    return out.reset_index(drop=True)


def run_simulation(
    symbol_dfs: dict[str, pd.DataFrame],
    *,
    portfolio: bool,
    entry_from: date | None = None,
    entry_to: date | None = None,
    regime: MarketRegime | None = None,
    source: str = "research",
    meta_filter: MetaLabelFilter | None = None,
) -> list:
    if portfolio:
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
            get_strategy(),
            journal=None,
            entry_from=entry_from,
            entry_to=entry_to,
            source=source,
            regime=regime,
            meta_filter=meta_filter,
        )

    trades = []
    for symbol, df in symbol_dfs.items():
        window = df
        if entry_from or entry_to:
            start = entry_from or pd.to_datetime(df["datetime"]).dt.date.min()
            end = entry_to or pd.to_datetime(df["datetime"]).dt.date.max()
            window = _slice_by_dates(df, start, end)
        trades.extend(
            simulate_symbol(
                symbol,
                window,
                get_strategy(),
                journal=None,
                entry_from=entry_from,
                entry_to=entry_to,
                source=source,
                regime=regime,
                meta_filter=meta_filter,
            )
        )
    return trades


def rolling_walk_forward(
    symbol_dfs: dict[str, pd.DataFrame],
    *,
    folds: int,
    train_days: int,
    test_days: int,
    portfolio: bool,
    regime: MarketRegime | None,
) -> dict[str, Any]:
    sample = next(iter(symbol_dfs.values()))
    dates = unique_trading_dates(sample)
    fold_size = train_days + test_days
    needed = fold_size * folds
    if len(dates) < fold_size:
        raise ValueError(f"Need at least {fold_size} trading days, have {len(dates)}")

    if len(dates) < needed:
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

        is_trades = run_simulation(
            symbol_dfs,
            portfolio=portfolio,
            entry_from=is_range[0],
            entry_to=is_range[1],
            regime=regime,
            source=f"rolling_is_{fold}",
        )
        oos_trades = run_simulation(
            symbol_dfs,
            portfolio=portfolio,
            entry_from=oos_range[0],
            entry_to=oos_range[1],
            regime=regime,
            source=f"rolling_oos_{fold}",
        )
        is_stats = summarize_trades(is_trades)
        oos_stats = summarize_trades(oos_trades)
        results.append({
            "fold": fold,
            "is_range": [str(is_range[0]), str(is_range[1])],
            "oos_range": [str(oos_range[0]), str(oos_range[1])],
            "is": is_stats,
            "oos": oos_stats,
        })
        start_idx += test_days

    positive_oos = sum(1 for r in results if r["oos"]["net_pnl_rs"] > 0)
    return {
        "folds": results,
        "positive_oos_folds": positive_oos,
        "total_folds": len(results),
        "pass": positive_oos > len(results) / 2 if results else False,
    }


def _ensure_meta_model(force_train: bool = False) -> MetaLabelFilter | None:
    """Load meta-label model; optionally train from journal first."""
    path = Config.META_LABEL_MODEL_PATH
    if force_train or not os.path.isfile(path):
        df = build_dataset(source_filter="paper,backtest,portfolio_sim,ablation_base", min_trades=20)
        if df.empty or df["label"].nunique() < 2:
            logger.warning("Meta-label train skipped — insufficient journal rows with labels")
            return None
        pipeline, meta = train_meta_model(df)
        save_meta_model(path, pipeline, meta)
    filt = MetaLabelFilter(enabled=True, model_path=path)
    return filt if filt.ready else None


def run_ablations(
    symbol_dfs: dict[str, pd.DataFrame],
    keys: list[str],
    *,
    portfolio: bool,
    data_source,
    broker: AngelBroker | None,
    days: int,
    meta_label_train: bool = False,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key in keys:
        preset = ABLATION_PRESETS.get(key)
        if not preset:
            logger.warning("Unknown ablation %s", key)
            continue
        with config_override(**preset):
            regime = build_regime(
                days,
                data_source,
                preset.get("REGIME_FILTER_ENABLED", False),
                broker=broker,
            )
            meta_filter = None
            if key == "meta_label":
                meta_filter = _ensure_meta_model(force_train=meta_label_train)
                if meta_filter is None:
                    logger.warning("Skipping meta_label ablation — no model")
                    continue
            trades = run_simulation(
                symbol_dfs,
                portfolio=portfolio,
                regime=regime,
                source=f"ablation_{key}",
                meta_filter=meta_filter,
            )
            out[key] = summarize_trades(trades)
            out[key]["regime"] = preset
    return out


def run_sizing_sweep(
    symbol_dfs: dict[str, pd.DataFrame],
    capitals: list[float],
    *,
    portfolio: bool,
    best_ablation: dict[str, Any] | None,
    data_source,
    broker: AngelBroker | None,
    days: int,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    overrides = best_ablation or ABLATION_PRESETS["both"]
    for cap in capitals:
        with config_override(
            **overrides,
            CAPITAL_PER_TRADE=cap,
            ESTIMATED_COST_PER_TRADE=0.0,
        ):
            regime = build_regime(
                days,
                data_source,
                overrides.get("REGIME_FILTER_ENABLED", False),
                broker=broker,
            )
            trades = run_simulation(
                symbol_dfs,
                portfolio=portfolio,
                regime=regime,
                source=f"sizing_{int(cap)}",
            )
            base = Config.MAX_POSITIONS * cap
            stats = summarize_trades(trades, use_return_sharpe=True, capital_base=base)
            stats["capital_per_trade"] = cap
            stats["capital_base"] = base
            out[str(int(cap))] = stats
    return out


def _best_ablation(ablations: dict[str, dict]) -> tuple[str, dict]:
    ranked = sorted(ablations.items(), key=lambda x: (x[1].get("sharpe", 0), x[1].get("net_pnl_rs", 0)), reverse=True)
    key, stats = ranked[0]
    preset = ABLATION_PRESETS.get(key, {})
    return key, preset


def write_verdict(path: str, report: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# RSI MR Research Verdict",
        "",
        f"Symbols: {report.get('symbol_count')} | Days: {report.get('days')} | "
        f"Data: {report.get('data_source', 'angel')} | "
        f"Engine: {'portfolio' if report.get('portfolio') else 'per-symbol'}",
        "",
        "## Q1 Rolling walk-forward",
    ]
    rolling = report.get("rolling", {})
    lines.append(
        f"- Positive OOS folds: {rolling.get('positive_oos_folds')}/{rolling.get('total_folds')} "
        f"({'PASS' if rolling.get('pass') else 'FAIL'})"
    )
    full = report.get("full_period", {})
    lines.append(f"- Full-period net: ₹{full.get('net_pnl_rs', 0):,.0f} | Sharpe: {full.get('sharpe', 0):.3f}")
    lines.append("")
    lines.append("## Q3 Filter ablation (Sharpe primary)")
    for key, stats in report.get("ablations", {}).items():
        lines.append(
            f"- **{key}**: Sharpe {stats.get('sharpe', 0):.3f} | "
            f"net ₹{stats.get('net_pnl_rs', 0):,.0f} | trades {stats.get('trades', 0)}"
        )
    best = report.get("best_ablation_key", "—")
    lines.append(f"- Best ablation by Sharpe: **{best}**")
    lines.append("")
    lines.append("## Q4 Sizing sweep (return-based Sharpe, formula costs)")
    for cap, stats in report.get("sizing", {}).items():
        lines.append(
            f"- ₹{cap}/trade: Sharpe {stats.get('sharpe', 0):.3f} | "
            f"net ₹{stats.get('net_pnl_rs', 0):,.0f}"
        )
    lines.append("")
    lines.append(f"## Decision\n\n{report.get('decision', 'Review manually.')}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def decide(report: dict[str, Any]) -> str:
    rolling = report.get("rolling", {})
    full = report.get("full_period", {})
    ablations = report.get("ablations", {})

    if full.get("net_pnl_rs", 0) <= 0 or not rolling.get("pass"):
        return "FAIL Q1 — stop entry research; revisit exits/guards or shelve MR."

    if report.get("portfolio") and full.get("net_pnl_rs", 0) <= 0:
        return "FAIL Q2 — portfolio net negative; shrink universe or enable ranker."

    if ablations:
        base = ablations.get("base", {})
        best_key, best = _best_ablation(ablations)
        best_stats = ablations[best_key]
        if best_stats.get("sharpe", 0) > base.get("sharpe", 0) + 0.05:
            if best_stats.get("net_pnl_rs", 0) >= base.get("net_pnl_rs", 0) * 0.9:
                if "adx" in best_key:
                    return f"PASS Q3 — keep {best_key} filters; consider AdaptiveMeanReversionStrategy."
                return f"PASS Q3 — keep {best_key} filters on rsi_mr."
        return "Q3 inconclusive — keep plain rsi_mr (filters do not clearly help Sharpe)."

    return "Phase B complete — review JSON for details."


def main() -> int:
    args = parse_args()
    setup_logger()

    data_source = normalize_source("cache" if args.offline else (args.source or None))
    if needs_angel_login(data_source):
        Config.validate()

    symbols = _resolve_symbols(args)
    portfolio = not args.per_symbol
    ablation_keys = [k.strip() for k in args.ablations.split(",") if k.strip()]
    if args.meta_label and "meta_label" not in ablation_keys:
        ablation_keys.append("meta_label")
    sizing_vals = [float(x) for x in args.sizing.split(",") if x.strip()] or [10000, 15000, 25000, 40000]

    broker: AngelBroker | None = None
    if needs_angel_login(data_source):
        get_registry().load()
        broker = AngelBroker()
        broker.login()

    symbol_dfs = load_symbol_dfs(symbols, args.days, data_source, broker=broker)
    if not symbol_dfs:
        print("Error: no candle data", file=sys.stderr)
        return 1

    regime = build_regime(args.days, data_source, Config.REGIME_FILTER_ENABLED, broker=broker)
    report: dict[str, Any] = {
        "days": args.days,
        "data_source": data_source,
        "symbol_count": len(symbol_dfs),
        "portfolio": portfolio,
        "symbols": list(symbol_dfs.keys()),
    }

    # Full period (Q1/Q2)
    full_trades = run_simulation(
        symbol_dfs,
        portfolio=portfolio,
        regime=regime,
        source="full_period",
    )
    report["full_period"] = summarize_trades(full_trades)

    # Per-symbol contribution (Q2)
    per_symbol = {}
    for sym, df in symbol_dfs.items():
        trades = simulate_symbol(sym, df, get_strategy(), journal=None, regime=regime, source="q2_symbol")
        per_symbol[sym] = summarize_trades(trades)
    report["per_symbol"] = per_symbol
    report["symbols_net_positive"] = sum(1 for s in per_symbol.values() if s.get("net_pnl_rs", 0) > 0)

    if not args.skip_rolling:
        try:
            report["rolling"] = rolling_walk_forward(
                symbol_dfs,
                folds=args.rolling_folds,
                train_days=args.train_days,
                test_days=args.test_days,
                portfolio=portfolio,
                regime=regime,
            )
        except ValueError as exc:
            logger.warning("Rolling WF skipped: %s", exc)
            report["rolling"] = {"error": str(exc)}

    if not args.skip_ablations:
        report["ablations"] = run_ablations(
            symbol_dfs,
            ablation_keys,
            portfolio=portfolio,
            data_source=data_source,
            broker=broker,
            days=args.days,
            meta_label_train=args.meta_label_train,
        )
        report["best_ablation_key"], _ = _best_ablation(report["ablations"])

    if not args.skip_sizing and report.get("ablations"):
        _, best_preset = _best_ablation(report["ablations"])
        report["sizing"] = run_sizing_sweep(
            symbol_dfs,
            sizing_vals,
            portfolio=portfolio,
            best_ablation=best_preset,
            data_source=data_source,
            broker=broker,
            days=args.days,
        )

    report["decision"] = decide(report)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    write_verdict(args.verdict_path, report)

    print(f"\n=== Phase B validation ({source_label(data_source)}) ===")
    print(f"Full period: net ₹{report['full_period']['net_pnl_rs']:,.0f} | "
          f"Sharpe {report['full_period'].get('sharpe', 0):.3f}")
    if "rolling" in report and "error" not in report["rolling"]:
        r = report["rolling"]
        print(f"Rolling OOS: {r.get('positive_oos_folds')}/{r.get('total_folds')} folds positive")
    if report.get("ablations"):
        print("\nAblation Sharpe:")
        for k, s in report["ablations"].items():
            print(f"  {k:<6} sharpe={s.get('sharpe', 0):.3f} net=₹{s.get('net_pnl_rs', 0):,.0f}")
    print(f"\nDecision: {report['decision']}")
    print(f"JSON: {args.output}")
    print(f"Verdict: {args.verdict_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
