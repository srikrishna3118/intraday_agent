#!/usr/bin/env python3
"""ATR-stop post-mortem: per-trade forensics and RSI/time/symbol clustering."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Iterator

import pandas as pd

from intraday_agent.config import Config
from intraday_agent.learning.costs import apply_costs
from intraday_agent.learning.entry_features import features_from_json
from intraday_agent.learning.journal import TradeJournal, TradeRecord
from intraday_agent.learning.metrics import summarize_trades
from intraday_agent.learning.portfolio_sim import simulate_portfolio
from intraday_agent.learning.research_data import (
    build_regime,
    init_research_session,
    load_symbol_dfs,
    normalize_source,
)
from intraday_agent.learning.sim_filters import SimEntryFilter
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import get_strategy
from intraday_agent.universe import to_ist

T2_SYMBOLS = [
    "RELIANCE", "SBIN", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "KOTAKBANK", "AXISBANK",
    "LT", "ITC", "BHARTIARTL", "HINDUNILVR", "MARUTI", "TATASTEEL", "TATACONSUM", "WIPRO",
    "HCLTECH", "TECHM", "SUNPHARMA", "NTPC", "ONGC", "POWERGRID", "TITAN", "M&M",
    "BAJFINANCE", "ASIANPAINT", "ULTRACEMCO", "JSWSTEEL", "INDUSINDBK", "COALINDIA",
]

BASELINE_OVERRIDES = {
    "RSI_OVERBOUGHT": 75.0,
    "ENTRY_CUTOFF_TIME": "14:30",
    "EXCLUDED_SYMBOLS": frozenset(),
}

NEW_STACK_OVERRIDES = {
    "RSI_OVERBOUGHT": 80.0,
    "ENTRY_CUTOFF_TIME": "14:00",
    "EXCLUDED_SYMBOLS": frozenset({"ONGC", "SBIN", "BAJFINANCE"}),
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
    parser = argparse.ArgumentParser(description="ATR stop post-mortem on portfolio sim")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--tier", choices=("t1", "t2"), default="t2")
    parser.add_argument("--source", type=str, default="cache")
    parser.add_argument("--stack", choices=("baseline", "new", "both"), default="both")
    parser.add_argument("--output", type=str, default="data/research/atr_stop_postmortem.json")
    parser.add_argument("--verdict-path", type=str, default="data/research/atr_stop_postmortem.md")
    return parser.parse_args()


def is_atr_stop(reason: str | None) -> bool:
    return bool(reason and reason.startswith("ATR stop"))


def rsi_bucket(rsi: float | None) -> str:
    if rsi is None or pd.isna(rsi):
        return "unknown"
    if rsi > 90:
        return "RSI 90+"
    if rsi > 85:
        return "RSI 85-90"
    if rsi > 82:
        return "RSI 82-85"
    if rsi > 80:
        return "RSI 80-82"
    if rsi > 75:
        return "RSI 75-80"
    return "RSI ≤75"


def hold_bucket(minutes: float | None) -> str:
    if minutes is None or pd.isna(minutes):
        return "unknown"
    m = float(minutes)
    if m <= 5:
        return "≤5 min"
    if m <= 10:
        return "5-10 min"
    if m <= 20:
        return "10-20 min"
    return ">20 min"


def trade_row(trade: TradeRecord) -> dict[str, Any]:
    enriched = TradeJournal.enrich(trade)
    feats = features_from_json(enriched.entry_features)
    entry_ist = to_ist(enriched.entry_time)
    hold = enriched.hold_minutes
    if hold is None and enriched.exit_time and enriched.entry_time:
        hold = max(
            0.0,
            (to_ist(enriched.exit_time) - entry_ist).total_seconds() / 60.0,
        )
    gross = float(enriched.pnl_amount or 0)
    df = apply_costs(pd.DataFrame([asdict(enriched)]))
    net = float(df["net_pnl_amount"].iloc[0])
    return {
        "symbol": enriched.symbol,
        "entry_time": entry_ist.strftime("%Y-%m-%d %H:%M IST"),
        "rsi": round(float(enriched.entry_rsi), 2) if enriched.entry_rsi is not None else None,
        "volume_ratio": round(float(enriched.volume_ratio), 3)
        if enriched.volume_ratio is not None
        else feats.get("volume_ratio"),
        "atr_pct": feats.get("atr_pct"),
        "vwap_distance": feats.get("vwap_distance"),
        "holding_minutes": round(float(hold), 1) if hold is not None else None,
        "loss_pct": round(float(enriched.pnl_pct), 3),
        "gross_rs": round(gross, 0),
        "net_rs": round(net, 0),
        "exit_reason": enriched.exit_reason,
        "rsi_bucket": rsi_bucket(enriched.entry_rsi),
        "hold_bucket": hold_bucket(hold),
    }


def aggregate_stops(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0, "total_gross_rs": 0, "total_net_rs": 0}

    df = pd.DataFrame(rows)
    by_rsi = (
        df.groupby("rsi_bucket")
        .agg(count=("symbol", "count"), gross_rs=("gross_rs", "sum"), net_rs=("net_rs", "sum"))
        .reset_index()
        .sort_values("count", ascending=False)
    )
    by_hold = (
        df.groupby("hold_bucket")
        .agg(count=("symbol", "count"), gross_rs=("gross_rs", "sum"), net_rs=("net_rs", "sum"))
        .reset_index()
    )
    hold_order = ["≤5 min", "5-10 min", "10-20 min", ">20 min", "unknown"]
    by_hold["sort"] = by_hold["hold_bucket"].apply(
        lambda x: hold_order.index(x) if x in hold_order else 99
    )
    by_hold = by_hold.sort_values("sort").drop(columns=["sort"])

    by_symbol = (
        df.groupby("symbol")
        .agg(count=("symbol", "count"), gross_rs=("gross_rs", "sum"), net_rs=("net_rs", "sum"))
        .reset_index()
        .sort_values("net_rs")
    )

    total_net = float(df["net_rs"].sum())
    quick = df[df["hold_bucket"] == "≤5 min"]
    return {
        "count": len(rows),
        "total_gross_rs": round(float(df["gross_rs"].sum()), 0),
        "total_net_rs": round(total_net, 0),
        "avg_hold_minutes": round(float(df["holding_minutes"].mean()), 1) if len(df) else 0,
        "by_rsi": by_rsi.to_dict("records"),
        "by_hold": by_hold.to_dict("records"),
        "by_symbol": by_symbol.to_dict("records"),
        "pct_within_5min": round(100 * len(quick) / len(df), 1) if len(df) else 0,
        "pct_within_10min": round(
            100 * len(df[df["holding_minutes"].fillna(999) <= 10]) / len(df), 1
        )
        if len(df)
        else 0,
        "pct_within_20min": round(
            100 * len(df[df["holding_minutes"].fillna(999) <= 20]) / len(df), 1
        )
        if len(df)
        else 0,
    }


def stack_metrics(trades: list[TradeRecord]) -> dict[str, Any]:
    stats = summarize_trades(trades)
    stops = [t for t in trades if is_atr_stop(t.exit_reason)]
    stop_rows = [trade_row(t) for t in stops]
    stop_agg = aggregate_stops(stop_rows)
    gross = stats.get("gross_pnl_rs", 0) or 0
    costs = stats.get("total_costs_rs", 0) or 0
    cost_ratio = round(costs / gross, 2) if gross > 0 else None
    return {
        "portfolio": stats,
        "atr_stops": stop_agg,
        "atr_stop_trades": stop_rows,
        "cost_ratio": cost_ratio,
        "success_gates": {
            "gross_gt_1000": gross > 1000,
            "cost_ratio_lt_3": cost_ratio is not None and cost_ratio < 3,
            "gross_pnl_rs": gross,
            "cost_ratio": cost_ratio,
        },
    }


def run_stack(
    name: str,
    overrides: dict[str, Any],
    symbol_dfs: dict,
    regime: Any,
    days: int,
) -> dict[str, Any]:
    with config_override(**overrides):
        strategy = get_strategy("rsi_mr")
        trades = simulate_portfolio(
            symbol_dfs,
            strategy=strategy,
            journal=None,
            source=f"atr_pm_{name}",
            regime=regime,
        )
    return {"name": name, "overrides": {k: list(v) if isinstance(v, frozenset) else v for k, v in overrides.items()}, **stack_metrics(trades)}


def answer_questions(report: dict[str, Any]) -> dict[str, str]:
    answers: dict[str, str] = {}
    for key in ("baseline", "new_stack"):
        block = report.get(key)
        if not block:
            continue
        agg = block["atr_stops"]
        prefix = "Baseline" if key == "baseline" else "New stack"

        rsi_rows = agg.get("by_rsi") or []
        if rsi_rows:
            top_rsi = max(rsi_rows, key=lambda r: r["count"])
            target = [r for r in rsi_rows if r["rsi_bucket"] in ("RSI 80-82", "RSI 82-85", "RSI 90+")]
            target_sorted = sorted(target, key=lambda r: r["count"], reverse=True)
            parts = ", ".join(
                f"{r['rsi_bucket']}: {r['count']} stops (net ₹{r['net_rs']:,.0f})"
                for r in target_sorted
            )
            answers[f"q1_{key}"] = (
                f"{prefix} — Q1 RSI concentration: dominant bucket **{top_rsi['rsi_bucket']}** "
                f"({top_rsi['count']} stops). Focus buckets: {parts or 'n/a (new stack may lack 75-80 stops)'}."
            )

        hold_rows = agg.get("by_hold") or []
        if hold_rows:
            top_hold = max(hold_rows, key=lambda r: r["count"])
            answers[f"q2_{key}"] = (
                f"{prefix} — Q2 time concentration: **{agg.get('pct_within_5min', 0):.0f}%** within 5 min, "
                f"**{agg.get('pct_within_10min', 0):.0f}%** within 10 min, "
                f"**{agg.get('pct_within_20min', 0):.0f}%** within 20 min. "
                f"Largest bucket: **{top_hold['hold_bucket']}** ({top_hold['count']} stops). "
                + (
                    "Early failures dominate — a time-based exit trial is warranted."
                    if agg.get("pct_within_10min", 0) >= 50
                    else "Holds spread beyond 10 min — time exit alone may not replace ATR stop."
                )
            )

        sym_rows = agg.get("by_symbol") or []
        if sym_rows:
            worst = sym_rows[:5]
            parts = ", ".join(f"{r['symbol']} ({r['count']}, ₹{r['net_rs']:,.0f})" for r in worst)
            answers[f"q3_{key}"] = f"{prefix} — Q3 symbol cluster (worst net): {parts}."

    b = report.get("baseline", {}).get("atr_stops", {})
    n = report.get("new_stack", {}).get("atr_stops", {})
    if b.get("total_net_rs") and n.get("total_net_rs") is not None:
        b_loss = abs(float(b["total_net_rs"]))
        n_loss = abs(float(n["total_net_rs"]))
        if b_loss > 0:
            reduction = round(100 * (b_loss - n_loss) / b_loss, 1)
            answers["atr_reduction"] = (
                f"ATR-stop net loss: baseline ₹{b['total_net_rs']:,.0f} → new stack ₹{n['total_net_rs']:,.0f} "
                f"({reduction:+.1f}% change; target was -30%+ reduction)."
            )
    return answers


def write_markdown(path: str, report: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# ATR Stop Post-Mortem (180d T2 portfolio)",
        "",
        "## Success gates (new stack — paper milestone)",
        "",
        "| Gate | Target | Result |",
        "|------|--------|--------|",
    ]
    ns = report.get("new_stack", {})
    gates = ns.get("success_gates", {})
    pf = ns.get("portfolio", {})
    lines.append(
        f"| Gross P&L | > ₹1,000 | ₹{gates.get('gross_pnl_rs', 0):,.0f} "
        f"({'PASS' if gates.get('gross_gt_1000') else 'FAIL'}) |"
    )
    cr = gates.get("cost_ratio")
    lines.append(
        f"| Cost ratio (costs/gross) | < 3 | {cr if cr is not None else 'n/a'} "
        f"({'PASS' if gates.get('cost_ratio_lt_3') else 'FAIL'}) |"
    )
    b_loss = report.get("baseline", {}).get("atr_stops", {}).get("total_net_rs", 0)
    n_loss = ns.get("atr_stops", {}).get("total_net_rs", 0)
    if b_loss:
        pct = round(100 * (abs(b_loss) - abs(n_loss)) / abs(b_loss), 1)
        lines.append(
            f"| ATR-stop net loss | -30%+ vs baseline | {pct:+.1f}% "
            f"({'PASS' if pct >= 30 else 'FAIL'}) |"
        )

    lines.extend(["", "## Portfolio summary", ""])
    for key, label in (("baseline", "Baseline (RSI>75, cutoff 14:30)"), ("new_stack", "New stack (RSI>80, hour<14, denylist)")):
        block = report.get(key)
        if not block:
            continue
        s = block["portfolio"]
        a = block["atr_stops"]
        lines.append(
            f"**{label}:** {s['trades']} trades, gross ₹{s['gross_pnl_rs']:,.0f}, "
            f"net ₹{s['net_pnl_rs']:,.0f}, {a['count']} ATR stops (net ₹{a['total_net_rs']:,.0f})"
        )

    lines.extend(["", "## Answers", ""])
    for ans in report.get("answers", {}).values():
        lines.append(f"- {ans}")

    lines.extend(["", "## New stack — ATR stop trade log", ""])
    rows = ns.get("atr_stop_trades") or []
    if rows:
        lines.extend([
            "| Symbol | Entry | RSI | Vol | ATR% | VWAP dist | Hold | Loss% | Net ₹ |",
            "|--------|-------|-----|-----|------|-----------|------|-------|-------|",
        ])
        for r in rows:
            lines.append(
                f"| {r['symbol']} | {r['entry_time']} | {r['rsi']} | {r['volume_ratio']} | "
                f"{r['atr_pct']} | {r['vwap_distance']} | {r['holding_minutes']}m | "
                f"{r['loss_pct']}% | {r['net_rs']} |"
            )
    else:
        lines.append("_No ATR stops in new stack sim._")

    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main() -> int:
    args = parse_args()
    setup_logger()

    source = normalize_source(args.source or None)
    _, broker = init_research_session(source)
    symbols = T2_SYMBOLS if args.tier == "t2" else T2_SYMBOLS[:5]
    symbol_dfs = load_symbol_dfs(symbols, args.days, source, broker=broker)
    if not symbol_dfs:
        print("Error: no candle data", file=sys.stderr)
        return 1

    regime = build_regime(args.days, source, Config.REGIME_FILTER_ENABLED, broker=broker)
    report: dict[str, Any] = {"days": args.days, "data_source": source}

    if args.stack in ("baseline", "both"):
        print("Running baseline stack...")
        report["baseline"] = run_stack("baseline", BASELINE_OVERRIDES, symbol_dfs, regime, args.days)
    if args.stack in ("new", "both"):
        print("Running new stack...")
        report["new_stack"] = run_stack("new_stack", NEW_STACK_OVERRIDES, symbol_dfs, regime, args.days)

    report["answers"] = answer_questions(report)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    # Trim full trade lists in JSON for size — keep counts + aggregates
    export = json.loads(json.dumps(report, default=str))
    for key in ("baseline", "new_stack"):
        if key in export and len(export[key].get("atr_stop_trades", [])) > 0:
            export[key]["atr_stop_trades_sample"] = export[key]["atr_stop_trades"][:5]
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    write_markdown(args.verdict_path, report)

    print("\n=== ATR Stop Post-Mortem ===\n")
    for k, v in report["answers"].items():
        print(v)
    print(f"\nReport: {args.verdict_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
