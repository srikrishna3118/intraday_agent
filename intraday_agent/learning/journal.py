"""SQLite trade journal for adaptive learning and pattern mining."""

from __future__ import annotations

import csv
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytz

from intraday_agent.config import Config
from intraday_agent.learning.costs import summarize_pnl

IST = pytz.timezone("Asia/Kolkata")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_rsi REAL,
    volume_ratio REAL,
    entry_price REAL,
    exit_price REAL,
    quantity INTEGER,
    entry_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    hold_minutes REAL,
    entry_hour INTEGER,
    day_of_week INTEGER,
    exit_reason TEXT,
    pnl_pct REAL NOT NULL,
    pnl_amount REAL,
    source TEXT NOT NULL DEFAULT 'paper',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time);
CREATE INDEX IF NOT EXISTS idx_trades_source ON trades(source);
"""

_EXTRA_COLUMNS = (
    ("entry_price", "REAL"),
    ("exit_price", "REAL"),
    ("quantity", "INTEGER"),
    ("hold_minutes", "REAL"),
    ("entry_hour", "INTEGER"),
    ("day_of_week", "INTEGER"),
    ("entry_features", "TEXT"),
)


@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_rsi: float | None
    volume_ratio: float | None
    entry_time: datetime
    exit_time: datetime
    exit_reason: str
    pnl_pct: float
    pnl_amount: float | None
    source: str
    entry_price: float | None = None
    exit_price: float | None = None
    quantity: int | None = None
    hold_minutes: float | None = None
    entry_hour: int | None = None
    day_of_week: int | None = None
    entry_features: str | None = None


class TradeJournal:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or Config.TRADE_JOURNAL_PATH
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
            for name, col_type in _EXTRA_COLUMNS:
                if name not in existing:
                    conn.execute(f"ALTER TABLE trades ADD COLUMN {name} {col_type}")
            conn.commit()

    @staticmethod
    def _as_ist(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return IST.localize(dt)
        return dt.astimezone(IST)

    @classmethod
    def enrich(cls, trade: TradeRecord) -> TradeRecord:
        """Fill derived timing fields used for pattern mining."""
        entry_ist = cls._as_ist(trade.entry_time)
        exit_ist = cls._as_ist(trade.exit_time)
        hold = trade.hold_minutes
        if hold is None:
            hold = max(0.0, (exit_ist - entry_ist).total_seconds() / 60.0)
        return TradeRecord(
            symbol=trade.symbol,
            side=trade.side,
            entry_rsi=trade.entry_rsi,
            volume_ratio=trade.volume_ratio,
            entry_time=trade.entry_time,
            exit_time=trade.exit_time,
            exit_reason=trade.exit_reason,
            pnl_pct=trade.pnl_pct,
            pnl_amount=trade.pnl_amount,
            source=trade.source,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            quantity=trade.quantity,
            hold_minutes=round(hold, 1),
            entry_hour=trade.entry_hour if trade.entry_hour is not None else entry_ist.hour,
            day_of_week=trade.day_of_week if trade.day_of_week is not None else entry_ist.weekday(),
            entry_features=trade.entry_features,
        )

    def record_trade(self, trade: TradeRecord) -> int:
        trade = self.enrich(trade)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO trades (
                    symbol, side, entry_rsi, volume_ratio, entry_price, exit_price,
                    quantity, entry_time, exit_time, hold_minutes, entry_hour,
                    day_of_week, exit_reason, pnl_pct, pnl_amount, source, entry_features
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.symbol.upper(),
                    trade.side,
                    trade.entry_rsi,
                    trade.volume_ratio,
                    trade.entry_price,
                    trade.exit_price,
                    trade.quantity,
                    trade.entry_time.isoformat(),
                    trade.exit_time.isoformat(),
                    trade.hold_minutes,
                    trade.entry_hour,
                    trade.day_of_week,
                    trade.exit_reason,
                    trade.pnl_pct,
                    trade.pnl_amount,
                    trade.source,
                    trade.entry_features,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def fetch_trades(
        self,
        symbol: str | None = None,
        lookback_days: int | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM trades WHERE 1=1"
        params: list[Any] = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if lookback_days is not None:
            query += " AND datetime(exit_time) >= datetime('now', ?)"
            params.append(f"-{lookback_days} days")
        if source:
            query += " AND source = ?"
            params.append(source)

        query += " ORDER BY exit_time DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def export_csv(self, path: str, source: str | None = None) -> int:
        rows = self.fetch_trades(source=source)
        if not rows:
            return 0
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def trade_count(self, source: str | None = None) -> int:
        with self._connect() as conn:
            if source:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM trades WHERE source = ?", (source,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM trades").fetchone()
            return int(row["c"]) if row else 0

    def clear_source(self, source: str) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM trades WHERE source = ?", (source,))
            conn.commit()
            return cur.rowcount

    def summary(self, source: str | None = None) -> dict[str, Any]:
        rows = self.fetch_trades(source=source)
        pnl = summarize_pnl(rows)
        wins = sum(1 for r in rows if r.get("pnl_pct", 0) > 0)
        total = len(rows)
        by_source: dict[str, int] = {}
        with self._connect() as conn:
            for r in conn.execute("SELECT source, COUNT(*) AS n FROM trades GROUP BY source"):
                by_source[r["source"]] = r["n"]
        avg_pct = sum(r.get("pnl_pct", 0) for r in rows) / total if total else 0
        return {
            "total_trades": total,
            "win_rate_pct": round(100 * wins / total, 1) if total else 0,
            "avg_pnl_pct": round(avg_pct, 2),
            "total_pnl_rs": pnl["gross_pnl_rs"],
            "gross_pnl_rs": pnl["gross_pnl_rs"],
            "total_costs_rs": pnl["total_costs_rs"],
            "net_pnl_rs": pnl["net_pnl_rs"],
            "avg_cost_per_trade_rs": pnl["avg_cost_per_trade_rs"],
            "avg_net_per_trade_rs": pnl["avg_net_per_trade_rs"],
            "cost_model": pnl["cost_model"],
            "by_source": by_source,
            "db_path": self.db_path,
        }
