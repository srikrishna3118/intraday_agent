#!/usr/bin/env python3
"""Decompose portfolio-sim losses by symbol, hour, exit reason, and entry features."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import Any

import pandas as pd
import pytz

from intraday_agent.config import Config
from intraday_agent.learning.costs import apply_costs, summarize_pnl
from intraday_agent.learning.journal import TradeJournal, TradeRecord
from intraday_agent.learning.metrics import summarize_trades
from intraday_agent.learning.patterns import _rsi_bucket, _segment_stats, _volume_bucket
from intraday_agent.learning.portfolio_sim import simulate_portfolio
from intraday_agent.learning.research_data import (
    build_regime,
    init_research_session,
    load_symbol_dfs,
    normalize_source,
)
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import get_strategy

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.UTC

T2_SYMBOLS = [
    "RELIANCE", "SBIN", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "KOTAKBANK", "AXISBANK",
    "LT", "ITC", "BHARTIARTL", "HINDUNILVR", "MARUTI", "TATASTEEL", "TATACONSUM", "WIPRO",
    "HCLTECH", "TECHM", "SUNPHARMA", "NTPC", "ONGC", "POWERGRID", "TITAN", "M&M",
    "BAJFINANCE", "ASIANPAINT", "ULTRACEMCO", "JSWSTEEL", "INDUSINDBK", "COALINDIA",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Loss decomposition for portfolio sim trades")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--tier", choices=("t1", "t2"), default="t2")
    parser.add_argument("--source", type=str, default="cache")
    parser.add_argument("--strategy", type=str, default="rsi_mr")
    parser.add_argument("--sim-source", type=str, default="loss_decomp")
    parser.add_argument("--min-segment-trades", type=int, default=5)
    parser.add_argument("--output", type=str, default="data/research/loss_decomposition.json")
    parser.add_argument("--verdict-path", type=str, default="data/research/loss_decomposition.md")
    return parser.parse_args()


def normalize_exit_reason(reason: str | None) -> str:
    if not reason:
        return "unknown"
    base = reason.split("(")[0].strip()
    if base.startswith("ATR stop"):
        return "ATR stop"
    if base.startswith("ATR target"):
        return "ATR target"
    if base.startswith("trailing stop"):
        return "trailing stop"
    if "RSI mid-line" in reason:
        return "RSI mid-line exit"
    if "square-off" in reason.lower() or "square off" in reason.lower():
        return "EOD square-off"
    return base


def entry_hour_ist(entry_time: Any) -> int | None:
    """Candle cache stores naive UTC; convert to IST hour for attribution."""
    if entry_time is None or (isinstance(entry_time, float) and pd.isna(entry_time)):
        return None
    if hasattr(entry_time, "to_pydatetime"):
        entry_time = entry_time.to_pydatetime()
    if entry_time.tzinfo is None:
        entry_time = UTC.localize(entry_time).astimezone(IST)
    else:
        entry_time = entry_time.astimezone(IST)
    return entry_time.hour


def trades_to_df(trades: list[TradeRecord]) -> pd.DataFrame:
    enriched = [TradeJournal.enrich(t) for t in trades]
    rows = [asdict(t) for t in enriched]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["pnl_amount"] = pd.to_numeric(df["pnl_amount"], errors="coerce").fillna(0)
    df["pnl_pct"] = pd.to_numeric(df["pnl_pct"], errors="coerce").fillna(0)
    df["win"] = df["pnl_pct"] > 0
    df = apply_costs(df)
    df["rsi_bucket"] = df.apply(_rsi_bucket, axis=1)
    df["volume_bucket"] = df["volume_ratio"].apply(_volume_bucket)
    df["entry_hour"] = df["entry_time"].apply(entry_hour_ist)
    df["hour_label"] = df["entry_hour"].apply(
        lambda h: f"{int(h):02d}:00 IST" if pd.notna(h) else "unknown"
    )
    df["exit_family"] = df["exit_reason"].apply(normalize_exit_reason)
    return df


def segment_table(
    df: pd.DataFrame,
    col: str,
    min_trades: int,
    *,
    sort_by: str = "net_pnl_rs",
) -> list[dict[str, Any]]:
    if df.empty or col not in df.columns:
        return []
    grouped = (
        df.groupby(col, dropna=False)
        .agg(
            trades=("net_pnl_amount", "count"),
            wins=("win", "sum"),
            gross_rs=("pnl_amount", "sum"),
            costs_rs=("trade_cost_rs", "sum"),
            net_pnl_rs=("net_pnl_amount", "sum"),
            avg_gross_rs=("pnl_amount", "mean"),
        )
        .reset_index()
    )
    grouped["win_rate_pct"] = (100 * grouped["wins"] / grouped["trades"]).round(1)
    grouped = grouped.sort_values(sort_by, ascending=False)
    out = []
    for _, row in grouped.iterrows():
        out.append({
            col: row[col],
            "trades": int(row["trades"]),
            "win_rate_pct": float(row["win_rate_pct"]),
            "gross_rs": round(float(row["gross_rs"]), 0),
            "costs_rs": round(float(row["costs_rs"]), 0),
            "net_pnl_rs": round(float(row["net_pnl_rs"]), 0),
            "avg_gross_rs": round(float(row["avg_gross_rs"]), 1),
            "passes_min_trades": int(row["trades"]) >= min_trades,
        })
    return out


def top_bottom(rows: list[dict], key: str, n: int = 5) -> tuple[list[dict], list[dict]]:
    eligible = [r for r in rows if r.get("passes_min_trades")]
    best = sorted(eligible, key=lambda r: r["net_pnl_rs"], reverse=True)[:n]
    worst = sorted(eligible, key=lambda r: r["net_pnl_rs"])[:n]
    return best, worst


def edge_pockets(rows: list[dict], key: str, min_trades: int) -> list[dict]:
    return [
        r for r in rows
        if r.get("passes_min_trades") and r["net_pnl_rs"] > 0
    ]


def write_markdown(path: str, report: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    t = report["totals"]
    lines = [
        "# Loss Decomposition — rsi_mr baseline (180d T2 portfolio)",
        "",
        f"Strategy: `{report['strategy']}` | Trades: {t['trades']} | "
        f"Gross: ₹{t['gross_pnl_rs']:,.0f} | Costs: ₹{t['total_costs_rs']:,.0f} | "
        f"**Net: ₹{t['net_pnl_rs']:,.0f}** | Sharpe: {t.get('sharpe', 0):.3f}",
        "",
        "## Where the loss comes from",
        "",
        report.get("narrative", ""),
        "",
        "## P&L waterfall",
        "",
        "| Layer | ₹ | Share of net loss |",
        "|-------|---|-------------------|",
    ]
    for row in report.get("waterfall", []):
        lines.append(f"| {row['layer']} | {row['amount']:,.0f} | {row['share_pct']:.1f}% |")

    def _table(title: str, rows: list[dict], col: str) -> None:
        lines.extend(["", f"## {title}", ""])
        if not rows:
            lines.append("_No segments._")
            return
        lines.extend([
            f"| {col} | Trades | Win% | Gross ₹ | Costs ₹ | Net ₹ |",
            "|-------|--------|------|---------|---------|-------|",
        ])
        for r in rows:
            flag = "" if r.get("passes_min_trades") else " †"
            lines.append(
                f"| {r[col]}{flag} | {r['trades']} | {r['win_rate_pct']:.1f} | "
                f"{r['gross_rs']:,.0f} | {r['costs_rs']:,.0f} | **{r['net_pnl_rs']:,.0f}** |"
            )
        lines.append("")
        lines.append("† fewer than min-segment trades — interpret with caution")

    _table("Symbol attribution (all symbols)", report.get("by_symbol", []), "symbol")
    _table("Hour-of-day attribution (entry IST)", report.get("by_hour", []), "hour_label")
    _table("Exit reason attribution (grouped)", report.get("by_exit", []), "exit_family")
    _table("RSI bucket at entry", report.get("by_rsi", []), "rsi_bucket")
    _table("Volume ratio at entry", report.get("by_volume", []), "volume_bucket")

    lines.extend(["", "## Edge pockets (net positive, ≥ min trades)", ""])
    pockets = report.get("edge_pockets", [])
    if not pockets:
        lines.append("No segment with ≥ min trades has positive net P&L on this window.")
    else:
        lines.extend([
            "| Segment | Type | Trades | Net ₹ |",
            "|---------|------|--------|-------|",
        ])
        for p in pockets:
            lines.append(
                f"| {p['segment']} | {p['dimension']} | {p['trades']} | **{p['net_pnl_rs']:,.0f}** |"
            )

    lines.extend(["", "## Recommended focus", "", report.get("recommendations", ""), ""])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def build_narrative(report: dict[str, Any]) -> str:
    t = report["totals"]
    gross = t["gross_pnl_rs"]
    costs = t["total_costs_rs"]
    net = t["net_pnl_rs"]
    parts = []
    if gross > 0 and net < 0:
        parts.append(
            f"Gross edge is **positive** (+₹{gross:,.0f}) but **costs (₹{costs:,.0f}) "
            f"exceed gross by ₹{costs - gross:,.0f}** — the strategy is not losing on price "
            f"action alone; friction dominates."
        )
    elif gross <= 0:
        parts.append(
            f"Gross P&L is **negative** (₹{gross:,.0f}) before costs; "
            f"costs add another ₹{costs:,.0f}."
        )

    worst_sym = report.get("worst_symbols", [])
    if worst_sym:
        w = worst_sym[0]
        parts.append(
            f"Largest symbol drag: **{w['symbol']}** ({w['trades']} trades, net ₹{w['net_pnl_rs']:,.0f})."
        )

    worst_hr = report.get("worst_hours", [])
    if worst_hr:
        h = worst_hr[0]
        parts.append(
            f"Worst entry hour: **{h['hour_label']}** ({h['trades']} trades, net ₹{h['net_pnl_rs']:,.0f})."
        )

    worst_exit = report.get("worst_exits", [])
    if worst_exit:
        e = worst_exit[0]
        if e["net_pnl_rs"] < 0:
            parts.append(
                f"Largest exit leak: **{e['exit_family']}** "
                f"({e['trades']} trades, net ₹{e['net_pnl_rs']:,.0f})."
            )

    best_exit = report.get("best_exits", [])
    if best_exit:
        e = best_exit[0]
        if e["net_pnl_rs"] > 0:
            parts.append(
                f"Best exit path: **{e['exit_family']}** "
                f"({e['trades']} trades, net +₹{e['net_pnl_rs']:,.0f})."
            )

    pockets = report.get("edge_pockets", [])
    symbol_pockets = [p for p in pockets if p["dimension"] == "symbol"]
    if symbol_pockets:
        p = symbol_pockets[0]
        parts.append(
            f"Best symbol pocket: **{p['segment']}** — "
            f"{p['trades']} trades, net +₹{p['net_pnl_rs']:,.0f}."
        )
    elif not pockets:
        parts.append("No stable positive segment at ≥5 trades.")

    return " ".join(parts)


def build_recommendations(report: dict[str, Any]) -> str:
    recs = []
    t = report["totals"]
    if t["gross_pnl_rs"] > 0 and t["net_pnl_rs"] < 0:
        recs.append(
            "1. **Cut trade count** in worst hours/symbols before tuning RSI — costs scale linearly per trade."
        )
    worst_sym = report.get("worst_symbols", [])[:3]
    if worst_sym:
        names = ", ".join(s["symbol"] for s in worst_sym)
        recs.append(f"2. **Review or exclude** chronic losers: {names}.")
    worst_hr = report.get("worst_hours", [])[:2]
    if worst_hr:
        hours = ", ".join(h["hour_label"] for h in worst_hr)
        recs.append(f"3. **Time filter**: block or reduce size for entries at {hours}.")
    worst_exit = report.get("worst_exits", [])[:2]
    if worst_exit:
        exits = ", ".join(
            e["exit_family"] for e in worst_exit if e.get("net_pnl_rs", 0) < 0
        )
        if exits:
            recs.append(f"4. **Exit review**: losses concentrate in {exits} — tighten stops or skip weak entries.")
    best_exit = report.get("best_exits", [])[:1]
    if best_exit and best_exit[0].get("net_pnl_rs", 0) > 0:
        recs.append(
            f"5. **Keep winners working**: {best_exit[0]['exit_family']} "
            f"(+₹{best_exit[0]['net_pnl_rs']:,.0f} net) — don't cut this exit path while fixing stops."
        )
    rsi = report.get("by_rsi", [])
    if rsi:
        worst_rsi = min((r for r in rsi if r.get("passes_min_trades")), key=lambda r: r["net_pnl_rs"], default=None)
        if worst_rsi and worst_rsi["net_pnl_rs"] < 0:
            recs.append(
                f"6. **Entry filter test**: `{worst_rsi['rsi_bucket']}` "
                f"({worst_rsi['trades']} trades, ₹{worst_rsi['net_pnl_rs']:,.0f}) — "
                f"paper-block before any new strategy."
            )
    recs.append("Do not add strategy #6 until gross/net per trade improves after symbol+time filters.")
    return "\n".join(recs)


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

    strategy = get_strategy(args.strategy)
    regime = build_regime(args.days, source, Config.REGIME_FILTER_ENABLED, broker=broker)
    trades = simulate_portfolio(
        symbol_dfs,
        strategy=strategy,
        journal=None,
        source=args.sim_source,
        regime=regime,
    )
    df = trades_to_df(trades)
    totals = summarize_trades(trades)
    min_t = args.min_segment_trades

    by_symbol = segment_table(df, "symbol", min_t)
    by_hour = segment_table(df, "hour_label", min_t)
    by_exit = segment_table(df, "exit_family", min_t)
    by_rsi = segment_table(df, "rsi_bucket", min_t)
    by_volume = segment_table(df, "volume_bucket", min_t)

    best_sym, worst_sym = top_bottom(by_symbol, "symbol")
    best_hr, worst_hr = top_bottom(by_hour, "hour_label")
    _, worst_exit = top_bottom(by_exit, "exit_family")
    best_exit, _ = top_bottom(by_exit, "exit_family")

    pockets: list[dict] = []
    for dim, rows, col in (
        ("symbol", by_symbol, "symbol"),
        ("hour", by_hour, "hour_label"),
        ("rsi", by_rsi, "rsi_bucket"),
        ("volume", by_volume, "volume_bucket"),
    ):
        for r in edge_pockets(rows, col, min_t):
            pockets.append({
                "dimension": dim,
                "segment": r[col],
                "trades": r["trades"],
                "net_pnl_rs": r["net_pnl_rs"],
            })
    pockets.sort(key=lambda x: x["net_pnl_rs"], reverse=True)

    gross = totals["gross_pnl_rs"]
    costs = totals["total_costs_rs"]
    net = totals["net_pnl_rs"]
    loss = abs(net) if net < 0 else 1.0
    waterfall = [
        {"layer": "Gross P&L (price)", "amount": gross, "share_pct": round(100 * gross / loss, 1) if net < 0 else 0},
        {"layer": "Estimated costs", "amount": -costs, "share_pct": round(100 * costs / loss, 1) if net < 0 else 0},
        {"layer": "Net P&L", "amount": net, "share_pct": 100.0 if net < 0 else 0},
    ]

    report: dict[str, Any] = {
        "days": args.days,
        "strategy": args.strategy,
        "data_source": source,
        "symbol_count": len(symbol_dfs),
        "min_segment_trades": min_t,
        "totals": totals,
        "waterfall": waterfall,
        "by_symbol": by_symbol,
        "by_hour": by_hour,
        "by_exit": by_exit,
        "by_rsi": by_rsi,
        "by_volume": by_volume,
        "best_symbols": best_sym,
        "worst_symbols": worst_sym,
        "best_hours": best_hr,
        "worst_hours": worst_hr,
        "worst_exits": worst_exit,
        "best_exits": best_exit,
        "edge_pockets": pockets,
    }
    report["narrative"] = build_narrative(report)
    report["recommendations"] = build_recommendations(report)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    write_markdown(args.verdict_path, report)

    print(f"\n=== Loss decomposition ({len(trades)} trades) ===\n")
    print(report["narrative"])
    print(f"\nJSON: {args.output}")
    print(f"Report: {args.verdict_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
