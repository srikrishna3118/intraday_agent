#!/usr/bin/env python3
"""Generate charts and summary from trade_journal.db."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from intraday_agent.config import Config
from intraday_agent.learning.costs import apply_costs, summarize_pnl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visual report from trade journal")
    parser.add_argument(
        "--source",
        default="",
        help="Filter by source: backtest, paper, live (default: all)",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(Config.DATA_DIR, "reports"),
        help="Directory for PNG reports",
    )
    parser.add_argument(
        "--db",
        default=Config.TRADE_JOURNAL_PATH,
        help="Path to trade_journal.db",
    )
    return parser.parse_args()


def load_trades(db_path: str, source: str) -> pd.DataFrame:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Journal not found: {db_path}")

    query = "SELECT * FROM trades"
    params: list[str] = []
    if source:
        query += " WHERE source = ?"
        params.append(source)
    query += " ORDER BY exit_time ASC"

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=params or None)

    if df.empty:
        raise ValueError("No trades in journal for the selected filter")

    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True, errors="coerce")
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True, errors="coerce")
    df["pnl_amount"] = pd.to_numeric(df["pnl_amount"], errors="coerce").fillna(0)
    df["pnl_pct"] = pd.to_numeric(df["pnl_pct"], errors="coerce").fillna(0)
    df["win"] = df["pnl_pct"] > 0
    df = apply_costs(df)
    return df


def compute_summary(df: pd.DataFrame) -> dict:
    wins = int(df["win"].sum())
    total = len(df)
    pnl = summarize_pnl(df)
    return {
        "trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate_pct": round(100 * wins / total, 1) if total else 0,
        "avg_pnl_pct": round(float(df["pnl_pct"].mean()), 2),
        "total_pnl_rs": pnl["gross_pnl_rs"],
        "gross_pnl_rs": pnl["gross_pnl_rs"],
        "total_costs_rs": pnl["total_costs_rs"],
        "net_pnl_rs": pnl["net_pnl_rs"],
        "avg_cost_per_trade_rs": pnl["avg_cost_per_trade_rs"],
        "avg_net_per_trade_rs": pnl["avg_net_per_trade_rs"],
        "cost_model": pnl["cost_model"],
        "best_trade_rs": round(float(df["pnl_amount"].max()), 0),
        "worst_trade_rs": round(float(df["pnl_amount"].min()), 0),
        "long_trades": int((df["side"] == "LONG").sum()),
        "short_trades": int((df["side"] == "SHORT").sum()),
        "period_start": str(df["exit_time"].min()),
        "period_end": str(df["exit_time"].max()),
    }


def _save(fig: plt.Figure, path: str) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def plot_equity_curve(df: pd.DataFrame, out_dir: str, tag: str) -> str:
    curve = df.copy()
    curve["cum_gross"] = curve["pnl_amount"].cumsum()
    curve["cum_net"] = curve["net_pnl_amount"].cumsum()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(curve["exit_time"].values, curve["cum_gross"].values, color="#94a3b8", linewidth=1.5, linestyle="--", label="Gross")
    ax.plot(curve["exit_time"].values, curve["cum_net"].values, color="#2563eb", linewidth=2, label="Net (after costs)")
    ax.axhline(0, color="#64748b", linewidth=1)
    ax.set_title("Cumulative P&L — gross vs net (₹)")
    ax.set_xlabel("Exit time")
    ax.set_ylabel("Cumulative P&L (₹)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, f"{tag}_equity_curve.png")
    _save(fig, path)
    return path


def plot_pnl_distribution(df: pd.DataFrame, out_dir: str, tag: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(df["pnl_pct"], bins=20, color="#6366f1", edgecolor="white", alpha=0.85)
    ax.axvline(0, color="#dc2626", linewidth=1.5, linestyle="--")
    ax.axvline(float(df["pnl_pct"].mean()), color="#16a34a", linewidth=1.5, linestyle="--", label="Mean")
    ax.set_title("Trade P&L Distribution (%)")
    ax.set_xlabel("P&L %")
    ax.set_ylabel("Trades")
    ax.legend()
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, f"{tag}_pnl_distribution.png")
    _save(fig, path)
    return path


def plot_by_symbol(df: pd.DataFrame, out_dir: str, tag: str) -> str:
    sym = (
        df.groupby("symbol")
        .agg(trades=("pnl_pct", "count"), win_rate=("win", "mean"), total_pnl=("pnl_amount", "sum"))
        .sort_values("trades", ascending=False)
        .head(15)
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    sym["win_rate"].mul(100).plot(kind="barh", ax=axes[0], color="#0ea5e9")
    axes[0].set_title("Win rate by symbol (top 15)")
    axes[0].set_xlabel("Win rate (%)")
    axes[0].invert_yaxis()
    axes[0].grid(True, axis="x", alpha=0.3)

    sym["total_pnl"].plot(kind="barh", ax=axes[1], color="#8b5cf6")
    axes[1].set_title("Total P&L by symbol (₹)")
    axes[1].set_xlabel("P&L (₹)")
    axes[1].invert_yaxis()
    axes[1].axvline(0, color="#94a3b8", linewidth=1)
    axes[1].grid(True, axis="x", alpha=0.3)

    path = os.path.join(out_dir, f"{tag}_by_symbol.png")
    _save(fig, path)
    return path


def plot_exit_reasons(df: pd.DataFrame, out_dir: str, tag: str) -> str:
    reasons = df["exit_reason"].value_counts().head(8)
    fig, ax = plt.subplots(figsize=(8, 5))
    reasons.plot(kind="barh", ax=ax, color="#f59e0b")
    ax.set_title("Exit reasons")
    ax.set_xlabel("Trades")
    ax.invert_yaxis()
    ax.grid(True, axis="x", alpha=0.3)
    path = os.path.join(out_dir, f"{tag}_exit_reasons.png")
    _save(fig, path)
    return path


def plot_summary_card(summary: dict, df: pd.DataFrame, out_dir: str, tag: str, source: str) -> str:
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axis("off")
    title = f"Trade Journal Report — {source or 'all sources'}"
    lines = [
        title,
        "",
        f"Trades: {summary['trades']}  |  Win rate: {summary['win_rate_pct']}%",
        f"Gross P&L: ₹{summary['gross_pnl_rs']:,.0f}  |  Costs: ₹{summary['total_costs_rs']:,.0f}",
        f"Net P&L: ₹{summary['net_pnl_rs']:,.0f}  ({summary['cost_model']})",
        f"Avg net/trade: ₹{summary['avg_net_per_trade_rs']:,.1f}  |  Avg gross/trade: {summary['avg_pnl_pct']}%",
        f"Best: ₹{summary['best_trade_rs']:,.0f}  |  Worst: ₹{summary['worst_trade_rs']:,.0f}",
        f"Long: {summary['long_trades']}  |  Short: {summary['short_trades']}",
        f"Period: {summary['period_start'][:10]} → {summary['period_end'][:10]}",
        "",
        "Top symbols by trade count:",
    ]
    top = df["symbol"].value_counts().head(5)
    for sym, n in top.items():
        sub = df[df["symbol"] == sym]
        wr = 100 * sub["win"].mean()
        pnl = sub["pnl_amount"].sum()
        lines.append(f"  {sym}: {n} trades, {wr:.0f}% win, ₹{pnl:,.0f}")

    ax.text(
        0.05,
        0.95,
        "\n".join(lines),
        transform=ax.transAxes,
        fontsize=11,
        verticalalignment="top",
        fontfamily="monospace",
        bbox=dict(boxstyle="round", facecolor="#f8fafc", edgecolor="#cbd5e1"),
    )
    path = os.path.join(out_dir, f"{tag}_summary.png")
    _save(fig, path)
    return path


def main() -> int:
    args = parse_args()
    os.makedirs(args.output, exist_ok=True)
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_label = args.source or "all"

    try:
        df = load_trades(args.db, args.source)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        print("Run: python tools/bootstrap_backtest.py --symbols RELIANCE,SBIN --days 30")
        return 1

    summary = compute_summary(df)
    files = {
        "summary_card": plot_summary_card(summary, df, args.output, tag, source_label),
        "equity_curve": plot_equity_curve(df, args.output, tag),
        "pnl_distribution": plot_pnl_distribution(df, args.output, tag),
        "by_symbol": plot_by_symbol(df, args.output, tag),
        "exit_reasons": plot_exit_reasons(df, args.output, tag),
    }

    report = {"generated_at": datetime.now().isoformat(), "source_filter": args.source or "all", **summary, "files": files}
    json_path = os.path.join(args.output, f"{tag}_report.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print("\n" + "=" * 60)
    print("Trade Journal Report")
    print("=" * 60)
    print(f"Trades: {summary['trades']}  |  Win rate: {summary['win_rate_pct']}%")
    print(f"Gross P&L: ₹{summary['gross_pnl_rs']:,.0f}  |  Est. costs: ₹{summary['total_costs_rs']:,.0f}")
    print(f"Net P&L:   ₹{summary['net_pnl_rs']:,.0f}  ({summary['cost_model']})")
    print(f"Avg net/trade: ₹{summary['avg_net_per_trade_rs']:,.1f}")
    print(f"\nCharts saved to: {args.output}/")
    for name, path in files.items():
        print(f"  {name}: {os.path.basename(path)}")
    print(f"  json: {os.path.basename(json_path)}")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
