"""Mine patterns from trade journal for strategy tuning."""

from __future__ import annotations

from typing import Any

import pandas as pd

from intraday_agent.learning.costs import apply_costs, summarize_pnl
from intraday_agent.learning.journal import TradeJournal

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _segment_stats(df: pd.DataFrame, col: str, min_trades: int) -> list[dict[str, Any]]:
    if col not in df.columns or df[col].isna().all():
        return []

    grouped = (
        df.groupby(col, dropna=False)
        .agg(
            trades=("pnl_pct", "count"),
            win_rate=("win", "mean"),
            avg_pnl_pct=("pnl_pct", "mean"),
            total_pnl_rs=("net_pnl_amount", "sum"),
            gross_pnl_rs=("pnl_amount", "sum"),
        )
        .reset_index()
    )
    grouped = grouped[grouped["trades"] >= min_trades].sort_values("avg_pnl_pct", ascending=False)
    results = []
    for _, row in grouped.iterrows():
        results.append(
            {
                col: row[col],
                "trades": int(row["trades"]),
                "win_rate_pct": round(float(row["win_rate"]) * 100, 1),
                "avg_pnl_pct": round(float(row["avg_pnl_pct"]), 2),
                "total_pnl_rs": round(float(row["total_pnl_rs"]), 0),
            }
        )
    return results


def _rsi_bucket(row: pd.Series) -> str:
    rsi = row.get("entry_rsi")
    side = row.get("side")
    if pd.isna(rsi):
        return "unknown"
    if side == "LONG":
        if rsi < 20:
            return "long_rsi_<20"
        if rsi < 25:
            return "long_rsi_20-25"
        if rsi < 30:
            return "long_rsi_25-30"
        return "long_rsi_30+"
    if rsi > 80:
        return "short_rsi_>80"
    if rsi > 75:
        return "short_rsi_75-80"
    if rsi > 70:
        return "short_rsi_70-75"
    return "short_rsi_<70"


def _volume_bucket(ratio: float | None) -> str:
    if ratio is None or pd.isna(ratio):
        return "unknown"
    if ratio < 1.2:
        return "vol_<1.2x"
    if ratio < 1.5:
        return "vol_1.2-1.5x"
    if ratio < 2.0:
        return "vol_1.5-2x"
    return "vol_>2x"


class PatternMiner:
    """Analyze closed trades and surface segments worth keeping or avoiding."""

    def __init__(self, journal: TradeJournal | None = None, min_trades: int = 5):
        self.journal = journal or TradeJournal()
        self.min_trades = min_trades

    def load_df(self, source: str | None = None, lookback_days: int | None = None) -> pd.DataFrame:
        rows = self.journal.fetch_trades(source=source, lookback_days=lookback_days)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["pnl_amount"] = pd.to_numeric(df["pnl_amount"], errors="coerce").fillna(0)
        df["pnl_pct"] = pd.to_numeric(df["pnl_pct"], errors="coerce").fillna(0)
        df["win"] = df["pnl_pct"] > 0
        df["rsi_bucket"] = df.apply(_rsi_bucket, axis=1)
        df["volume_bucket"] = df["volume_ratio"].apply(_volume_bucket)
        if "entry_hour" in df.columns:
            df["hour_label"] = df["entry_hour"].apply(
                lambda h: f"{int(h):02d}:00" if pd.notna(h) else "unknown"
            )
        if "day_of_week" in df.columns:
            df["day_label"] = df["day_of_week"].apply(
                lambda d: DAY_NAMES[int(d)] if pd.notna(d) and 0 <= int(d) <= 6 else "unknown"
            )
        return apply_costs(df)

    def analyze(self, source: str | None = None, lookback_days: int | None = None) -> dict[str, Any]:
        df = self.load_df(source=source, lookback_days=lookback_days)
        if df.empty:
            return {"error": "No trades in journal", "trade_count": 0}

        total = len(df)
        wins = int(df["win"].sum())
        pnl = summarize_pnl(df)

        by_symbol_side = (
            df.groupby(["symbol", "side"])
            .agg(trades=("pnl_pct", "count"), win_rate=("win", "mean"), avg_pnl_pct=("pnl_pct", "mean"))
            .reset_index()
        )
        by_symbol_side = by_symbol_side[by_symbol_side["trades"] >= self.min_trades]
        best_symbols = by_symbol_side.nlargest(5, "avg_pnl_pct")
        worst_symbols = by_symbol_side.nsmallest(5, "avg_pnl_pct")

        insights: list[str] = []
        if not best_symbols.empty:
            top = best_symbols.iloc[0]
            insights.append(
                f"Best segment: {top['symbol']} {top['side']} "
                f"({top['avg_pnl_pct']:.2f}% avg, {100*top['win_rate']:.0f}% win, {int(top['trades'])} trades)"
            )
        if not worst_symbols.empty:
            bot = worst_symbols.iloc[0]
            insights.append(
                f"Avoid segment: {bot['symbol']} {bot['side']} "
                f"({bot['avg_pnl_pct']:.2f}% avg, {100*bot['win_rate']:.0f}% win, {int(bot['trades'])} trades)"
            )

        long_wr = df.loc[df["side"] == "LONG", "win"].mean()
        short_wr = df.loc[df["side"] == "SHORT", "win"].mean()
        if pd.notna(long_wr) and pd.notna(short_wr):
            better = "LONG" if long_wr >= short_wr else "SHORT"
            insights.append(
                f"{better} side performs better "
                f"(LONG {100*long_wr:.0f}% win vs SHORT {100*short_wr:.0f}% win)"
            )

        def _fmt_symbol_side(frame: pd.DataFrame) -> list[dict[str, Any]]:
            records = []
            for _, row in frame.iterrows():
                records.append(
                    {
                        "symbol": row["symbol"],
                        "side": row["side"],
                        "trades": int(row["trades"]),
                        "win_rate_pct": round(float(row["win_rate"]) * 100, 1),
                        "avg_pnl_pct": round(float(row["avg_pnl_pct"]), 2),
                    }
                )
            return records

        return {
            "trade_count": total,
            "win_rate_pct": round(100 * wins / total, 1),
            "avg_pnl_pct": round(float(df["pnl_pct"].mean()), 2),
            "gross_pnl_rs": pnl["gross_pnl_rs"],
            "total_costs_rs": pnl["total_costs_rs"],
            "net_pnl_rs": pnl["net_pnl_rs"],
            "total_pnl_rs": pnl["net_pnl_rs"],
            "avg_net_per_trade_rs": pnl["avg_net_per_trade_rs"],
            "cost_model": pnl["cost_model"],
            "insights": insights,
            "best_symbol_side": _fmt_symbol_side(best_symbols),
            "worst_symbol_side": _fmt_symbol_side(worst_symbols),
            "by_exit_reason": _segment_stats(df, "exit_reason", self.min_trades),
            "by_rsi_bucket": _segment_stats(df, "rsi_bucket", self.min_trades),
            "by_volume_bucket": _segment_stats(df, "volume_bucket", self.min_trades),
            "by_entry_hour": _segment_stats(df, "hour_label", self.min_trades) if "hour_label" in df.columns else [],
            "by_day": _segment_stats(df, "day_label", self.min_trades) if "day_label" in df.columns else [],
            "by_side": _segment_stats(df, "side", self.min_trades),
        }
