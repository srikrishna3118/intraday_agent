#!/usr/bin/env python3
"""Iterative edge search — P2/P4 ablations until net-positive stack found."""

from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeRecord
from intraday_agent.learning.research_data import (
    build_regime,
    init_research_session,
    load_symbol_dfs,
    normalize_source,
)
from intraday_agent.learning.sim_filters import SimEntryFilter
from intraday_agent.logging_setup import setup_logger
from intraday_agent.universe import NIFTY_50, symbols_for_tier
from tools.research_phases import (
    ENTRY_FILTER,
    SPRINT4_PAPER_STACK,
    apply_slippage,
    config_override,
    run_sim,
    summarize_with_slippage,
)


def _exit_breakdown(trades: list[TradeRecord]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in trades:
        reason = t.exit_reason or "unknown"
        if reason.startswith("ATR stop"):
            key = "ATR stop"
        elif reason.startswith("RSI"):
            key = "RSI exit"
        elif "square-off" in reason.lower():
            key = "EOD"
        else:
            key = reason.split("(")[0].strip()
        out[key] = out.get(key, 0) + 1
    return out


def _run(
    symbol_dfs: dict,
    regime: Any,
    *,
    label: str,
    config: dict[str, Any],
    entry_filter: SimEntryFilter,
    capital: float,
    max_qty: int,
) -> dict[str, Any]:
    with config_override(
        CAPITAL_PER_TRADE=capital,
        MAX_QUANTITY=max_qty,
        MAX_DAILY_LOSS=max(600, int(capital * 0.04)),
        MAX_DAILY_PROFIT=max(1500, int(capital * 0.06)),
    ):
        trades, stats = run_sim(
            symbol_dfs,
            regime,
            config=config,
            source=label,
            entry_filter=entry_filter,
        )
    slip = summarize_with_slippage(trades)
    return {
        "label": label,
        "config": _cfg_export(config),
        "filter": _filter_export(entry_filter),
        "stats": stats,
        "slip_stats": slip,
        "exits": _exit_breakdown(trades),
        "edge_pass": _edge_pass(stats, slip),
    }


def _cfg_export(cfg: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "ATR_STOP_MULT", "ATR_TARGET_MULT", "RSI_OVERBOUGHT", "RSI_EXIT",
        "VOLUME_SURGE_BLOCK_MULT", "RSI_MOMENTUM_TRAP_RSI", "RSI_MOMENTUM_TRAP_VOLR",
        "EXCLUDED_SYMBOLS", "TRAILING_STOP_ENABLED", "TIME_STOP_BARS",
        "PIVOT_FILTER_ENABLED", "ENTRY_CUTOFF_TIME",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in cfg:
            v = cfg[k]
            out[k] = sorted(v) if isinstance(v, frozenset) else v
    return out


def _filter_export(f: SimEntryFilter) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if f.max_entry_hour is not None:
        d["max_entry_hour"] = f.max_entry_hour
    if f.min_rsi is not None:
        d["min_rsi"] = f.min_rsi
    if f.momentum_trap_rsi is not None:
        d["momentum_trap_rsi"] = f.momentum_trap_rsi
        d["momentum_trap_vol_ratio"] = f.momentum_trap_vol_ratio
    return d


def _edge_pass(stats: dict, slip: dict) -> bool:
    return (
        stats.get("trades", 0) >= 10
        and stats.get("net_pnl_rs", 0) > 0
        and stats.get("sharpe", 0) > 0.5
        and slip.get("net_pnl_rs", 0) > 0
    )


def _base_filter(**kw) -> SimEntryFilter:
    return replace(ENTRY_FILTER, **kw)


def round1_variants() -> list[tuple[str, dict, SimEntryFilter]]:
    base = dict(SPRINT4_PAPER_STACK)
    f = ENTRY_FILTER
    return [
        ("r1_baseline", base, f),
        ("r1_surge2", {**base, "VOLUME_SURGE_BLOCK_MULT": 2.0}, f),
        ("r1_trap86", base, _base_filter(momentum_trap_rsi=86.0, momentum_trap_vol_ratio=1.7)),
        ("r1_surge_trap", {**base, "VOLUME_SURGE_BLOCK_MULT": 2.0},
         _base_filter(momentum_trap_rsi=86.0, momentum_trap_vol_ratio=1.7)),
        ("r1_no_deny", {**base, "EXCLUDED_SYMBOLS": frozenset()}, f),
        ("r1_surge_no_deny", {**base, "VOLUME_SURGE_BLOCK_MULT": 2.0, "EXCLUDED_SYMBOLS": frozenset()}, f),
        ("r1_atr125", {**base, "ATR_STOP_MULT": 1.25}, f),
        ("r1_atr20", {**base, "ATR_STOP_MULT": 2.0}, f),
        ("r1_rsi82", {**base, "RSI_OVERBOUGHT": 82.0}, f),
        ("r1_rsi84", {**base, "RSI_OVERBOUGHT": 84.0}, f),
        ("r1_hour13", base, _base_filter(max_entry_hour=13)),
        ("r1_minrsi82", base, _base_filter(min_rsi=82.0)),
        ("r1_surge_atr20", {**base, "VOLUME_SURGE_BLOCK_MULT": 2.0, "ATR_STOP_MULT": 2.0}, f),
        ("r1_surge_trap_atr20",
         {**base, "VOLUME_SURGE_BLOCK_MULT": 2.0, "ATR_STOP_MULT": 2.0,
          "RSI_MOMENTUM_TRAP_RSI": 86.0, "RSI_MOMENTUM_TRAP_VOLR": 1.7},
         _base_filter(momentum_trap_rsi=86.0, momentum_trap_vol_ratio=1.7)),
        ("r1_live_stack",
         {**base, "VOLUME_SURGE_BLOCK_MULT": 2.0, "RSI_MOMENTUM_TRAP_RSI": 86.0, "RSI_MOMENTUM_TRAP_VOLR": 1.7},
         _base_filter(momentum_trap_rsi=86.0, momentum_trap_vol_ratio=1.7)),
    ]


def round2_variants(best: dict) -> list[tuple[str, dict, SimEntryFilter]]:
    """Refine around the best round-1 config."""
    cfg = dict(SPRINT4_PAPER_STACK)
    cfg.update(best.get("config", {}))
    if "EXCLUDED_SYMBOLS" in cfg and not isinstance(cfg["EXCLUDED_SYMBOLS"], frozenset):
        cfg["EXCLUDED_SYMBOLS"] = frozenset(cfg["EXCLUDED_SYMBOLS"])

    filt_kw = best.get("filter", {})
    base_f = _base_filter(**{k: v for k, v in filt_kw.items() if k in SimEntryFilter.__dataclass_fields__})

    atr = float(cfg.get("ATR_STOP_MULT", 1.5))
    surge = float(cfg.get("VOLUME_SURGE_BLOCK_MULT", 0))
    trap_rsi = float(cfg.get("RSI_MOMENTUM_TRAP_RSI", 0))
    trap_vol = float(cfg.get("RSI_MOMENTUM_TRAP_VOLR", 0))

    variants: list[tuple[str, dict, SimEntryFilter]] = []
    for atr_m in sorted({1.25, 1.5, 1.75, 2.0, atr}):
        c = {**cfg, "ATR_STOP_MULT": atr_m}
        variants.append((f"r2_atr{atr_m}", c, base_f))

    for surge_m in (0, 1.8, 2.0, 2.2) if surge > 0 else (0, 2.0):
        c = {**cfg, "VOLUME_SURGE_BLOCK_MULT": surge_m}
        if trap_rsi > 0:
            c["RSI_MOMENTUM_TRAP_RSI"] = trap_rsi
            c["RSI_MOMENTUM_TRAP_VOLR"] = trap_vol
        variants.append((f"r2_surge{surge_m}", c, base_f))

    for rsi_ob in (80, 81, 82, 83, 84):
        variants.append((f"r2_ob{rsi_ob}", {**cfg, "RSI_OVERBOUGHT": float(rsi_ob)}, base_f))

    # Best combo re-run with live strategy traps
    live = {**cfg, "VOLUME_SURGE_BLOCK_MULT": max(surge, 2.0)}
    if trap_rsi <= 0:
        live["RSI_MOMENTUM_TRAP_RSI"] = 86.0
        live["RSI_MOMENTUM_TRAP_VOLR"] = 1.7
    variants.append((
        "r2_live_combo", live,
        _base_filter(momentum_trap_rsi=86.0, momentum_trap_vol_ratio=1.7),
    ))
    return variants


def _rank(results: list[dict]) -> list[dict]:
    return sorted(
        results,
        key=lambda r: (
            r["edge_pass"],
            r["slip_stats"]["net_pnl_rs"],
            r["stats"]["net_pnl_rs"],
            r["stats"]["sharpe"],
        ),
        reverse=True,
    )


def _tier_symbols(tier: str) -> list[str]:
    if tier == "nifty50":
        return list(NIFTY_50)
    return symbols_for_tier(tier)


def write_report(path: str, report: dict) -> None:
    lines = [
        "# Edge Search — Iterative Results",
        "",
        f"Generated: {report['generated_at']}",
        f"Tier: {report['tier']} ({report['symbol_count']} symbols) | "
        f"{report['days']}d | capital ₹{report['capital']:,.0f}",
        "",
        "## Winner",
        "",
    ]
    w = report["winner"]
    lines.append(f"**{w['label']}** — net **₹{w['stats']['net_pnl_rs']:,.0f}** | "
                 f"slip **₹{w['slip_stats']['net_pnl_rs']:,.0f}** | "
                 f"Sharpe {w['stats']['sharpe']:.3f} | {w['stats']['trades']} trades | "
                 f"edge_pass={w['edge_pass']}")
    lines.extend(["", "```json", json.dumps(w["config"], indent=2), "```", ""])

    for round_name in ("round1", "round2", "round3_universe"):
        rows = report.get(round_name, [])
        if not rows:
            continue
        lines.extend([
            f"## {round_name}",
            "",
            "| Label | Trades | Net ₹ | Slip ₹ | Sharpe | ATR | RSI ex | edge |",
            "|-------|--------|-------|--------|--------|-----|--------|------|",
        ])
        for r in _rank(rows)[:15]:
            s, sl = r["stats"], r["slip_stats"]
            ex = r["exits"]
            lines.append(
                f"| {r['label']} | {s['trades']} | {s['net_pnl_rs']:,.0f} | "
                f"{sl['net_pnl_rs']:,.0f} | {s['sharpe']:.3f} | "
                f"{ex.get('ATR stop', 0)} | {ex.get('RSI exit', 0)} | "
                f"{'✓' if r['edge_pass'] else '·'} |"
            )
        lines.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main() -> int:
    p = argparse.ArgumentParser(description="Iterative edge search on cache")
    p.add_argument("--tier", default="t2", help="t2 | t1 | nifty50")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--source", default="cache")
    p.add_argument("--capital", type=float, default=50000)
    p.add_argument("--max-qty", type=int, default=200)
    p.add_argument("--rounds", type=int, default=2, help="1=entry sweep, 2=refine winner")
    p.add_argument("--universe-test", action="store_true", help="Round 3: test winner on nifty50")
    p.add_argument("--output-json", default="data/research/edge_search.json")
    p.add_argument("--output-md", default="data/research/EDGE_SEARCH.md")
    args = p.parse_args()

    setup_logger()
    source = normalize_source(args.source)
    _, broker = init_research_session(source)
    symbols = _tier_symbols(args.tier)
    symbol_dfs = load_symbol_dfs(symbols, args.days, source, broker=broker)
    if not symbol_dfs:
        print("Error: no candle data", file=sys.stderr)
        return 1

    regime = build_regime(args.days, source, Config.REGIME_FILTER_ENABLED, broker=broker)
    print(f"Edge search: {args.tier} {len(symbol_dfs)}/{len(symbols)} symbols\n")

    r1: list[dict] = []
    for label, cfg, filt in round1_variants():
        print(f"  R1 {label}...")
        r1.append(_run(symbol_dfs, regime, label=label, config=cfg, entry_filter=filt,
                       capital=args.capital, max_qty=args.max_qty))

    best = _rank(r1)[0]
    print(f"\nR1 best: {best['label']} net ₹{best['stats']['net_pnl_rs']:,.0f} "
          f"(slip ₹{best['slip_stats']['net_pnl_rs']:,.0f})\n")

    r2: list[dict] = []
    if args.rounds >= 2:
        for label, cfg, filt in round2_variants(best):
            print(f"  R2 {label}...")
            r2.append(_run(symbol_dfs, regime, label=label, config=cfg, entry_filter=filt,
                           capital=args.capital, max_qty=args.max_qty))
        best = _rank(r1 + r2)[0]
        print(f"\nR2 best: {best['label']} net ₹{best['stats']['net_pnl_rs']:,.0f}\n")

    r3: list[dict] = []
    if args.universe_test and args.tier != "nifty50":
        n50 = load_symbol_dfs(_tier_symbols("nifty50"), args.days, source, broker=broker)
        if n50:
            print(f"R3 universe test on nifty50 ({len(n50)} symbols)...")
            cfg = dict(SPRINT4_PAPER_STACK)
            cfg.update(best.get("config", {}))
            if "EXCLUDED_SYMBOLS" in cfg and not isinstance(cfg["EXCLUDED_SYMBOLS"], frozenset):
                cfg["EXCLUDED_SYMBOLS"] = frozenset(cfg["EXCLUDED_SYMBOLS"])
            filt_kw = best.get("filter", {})
            filt = _base_filter(**{k: v for k, v in filt_kw.items()
                                   if k in SimEntryFilter.__dataclass_fields__})
            r3.append(_run(n50, regime, label="r3_nifty50_winner", config=cfg, entry_filter=filt,
                           capital=args.capital, max_qty=args.max_qty))
            r3.append(_run(n50, regime, label="r3_nifty50_baseline",
                           config=dict(SPRINT4_PAPER_STACK), entry_filter=ENTRY_FILTER,
                           capital=args.capital, max_qty=args.max_qty))
            best_all = _rank(r1 + r2 + r3)
            if best_all[0]["label"].startswith("r3"):
                print(f"R3 nifty50: {best_all[0]['stats']['net_pnl_rs']:,.0f}")
            else:
                print("R3: winner did not hold on nifty50 — keep t2/nifty50 scan only")

    winner = _rank(r1 + r2 + r3)[0]
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "tier": args.tier,
        "symbol_count": len(symbol_dfs),
        "days": args.days,
        "capital": args.capital,
        "winner": winner,
        "round1": r1,
        "round2": r2,
        "round3_universe": r3,
        "edge_found": winner["edge_pass"],
    }

    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    write_report(args.output_md, report)

    print(f"\n{'='*60}")
    print(f"WINNER: {winner['label']}")
    print(f"  Net ₹{winner['stats']['net_pnl_rs']:,.0f} | Slip ₹{winner['slip_stats']['net_pnl_rs']:,.0f}")
    print(f"  Sharpe {winner['stats']['sharpe']:.3f} | Trades {winner['stats']['trades']}")
    print(f"  Edge pass: {winner['edge_pass']}")
    print(f"  Config: {winner['config']}")
    return 0 if winner["edge_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
