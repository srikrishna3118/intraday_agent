#!/usr/bin/env python3
"""Run Phase 1–4 research sprint and write findings to data/research/."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterator

from intraday_agent.config import Config
from intraday_agent.learning.journal import TradeRecord
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

T2_SYMBOLS = [
    "RELIANCE", "SBIN", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "KOTAKBANK", "AXISBANK",
    "LT", "ITC", "BHARTIARTL", "HINDUNILVR", "MARUTI", "TATASTEEL", "TATACONSUM", "WIPRO",
    "HCLTECH", "TECHM", "SUNPHARMA", "NTPC", "ONGC", "POWERGRID", "TITAN", "M&M",
    "BAJFINANCE", "ASIANPAINT", "ULTRACEMCO", "JSWSTEEL", "INDUSINDBK", "COALINDIA",
]

DENYLIST = frozenset({"ONGC", "SBIN", "BAJFINANCE"})
PIVOT_STACK = {
    "PIVOT_FILTER_ENABLED": True,
    "PIVOT_FILTER_MODE": "proximity",
    "PIVOT_TOUCH_PCT": 0.35,
    "RSI_OVERBOUGHT": 80.0,
    "ENTRY_CUTOFF_TIME": "14:00",
    "EXCLUDED_SYMBOLS": DENYLIST,
    "ALLOW_LONG": False,
    "ALLOW_SHORT": True,
    "VWAP_FILTER_ENABLED": False,
    "VWAP_EXIT_ENABLED": False,
}
ENTRY_FILTER = SimEntryFilter(max_entry_hour=14, min_rsi=80.0)

# Phase 2 winner (Jun 2026 sprint) — pinned for Sprint 4 control
PHASE2_WINNER = {
    **PIVOT_STACK,
    "ATR_STOP_MULT": 1.5,
    "ATR_TARGET_MULT": 3.5,
    "USE_ATR_EXITS": True,
    "TRAILING_STOP_ENABLED": True,
    "TRAILING_STOP_ATR_MULT": 1.0,
    "TRAILING_ACTIVATION_ATR_MULT": 1.0,
}

# Mean-reversion exits: ATR stop only; target mult set high so fixed target rarely fires
MEAN_EXIT_RSI = {
    **PIVOT_STACK,
    "ATR_STOP_MULT": 1.5,
    "ATR_TARGET_MULT": 50.0,
    "USE_ATR_EXITS": True,
    "TRAILING_STOP_ENABLED": False,
    "RSI_EXIT": 50.0,
    "VWAP_EXIT_ENABLED": False,
}

SLIPPAGE_PCT_PER_LEG = 0.0005  # 0.05% per entry/exit leg (Gemini microstructure stress)


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


def run_sim(
    symbol_dfs: dict,
    regime: Any,
    *,
    config: dict[str, Any],
    source: str,
) -> tuple[list, dict[str, Any]]:
    with config_override(**config):
        trades = simulate_portfolio(
            symbol_dfs,
            strategy=get_strategy("rsi_mr"),
            journal=None,
            source=source,
            regime=regime,
            entry_filter=ENTRY_FILTER,
        )
    stats = summarize_trades(trades)
    return trades, stats


def apply_slippage(trades: list[TradeRecord], pct_per_leg: float = SLIPPAGE_PCT_PER_LEG) -> list[TradeRecord]:
    """Deduct per-leg slippage from gross P&L (post-sim stress test; not in live agent)."""
    adjusted: list[TradeRecord] = []
    for t in trades:
        entry = float(t.entry_price or 0)
        exit_p = float(t.exit_price or entry)
        qty = int(t.quantity or 0)
        slip = qty * (entry + exit_p) * pct_per_leg
        gross = float(t.pnl_amount or 0)
        adjusted.append(replace(t, pnl_amount=gross - slip))
    return adjusted


def summarize_with_slippage(
    trades: list[TradeRecord],
    pct_per_leg: float = SLIPPAGE_PCT_PER_LEG,
) -> dict[str, Any]:
    stats = summarize_trades(apply_slippage(trades, pct_per_leg))
    stats["slippage_pct_per_leg"] = pct_per_leg
    stats["cost_model"] = (
        f"{stats.get('cost_model', 'costs')} + slippage {pct_per_leg * 100:.2f}%/leg"
    )
    return stats


def _cfg_for_json(cfg: dict[str, Any]) -> dict[str, Any]:
    return {k: list(v) if isinstance(v, frozenset) else v for k, v in cfg.items()}


def phase4(symbol_dfs: dict, regime: Any) -> dict[str, Any]:
    """Sprint 4 — mean exits, slippage stress, denylist falsification (see GEMINI_CRITIQUE_AND_SPRINT4.md)."""
    print("\n=== PHASE 4 — Mean exit ablation + friction (Sprint 4) ===\n")
    print("See data/research/GEMINI_CRITIQUE_AND_SPRINT4.md for rationale.\n")

    variants: list[tuple[str, str, dict[str, Any], bool]] = [
        ("p4_control", "Phase 2 winner (ATR stop 1.5 / target 3.5, trailing on)", PHASE2_WINNER, False),
        ("p4_mean_rsi", "Test 9 + ATR stop only + RSI_EXIT=50 (no trailing)", MEAN_EXIT_RSI, False),
        (
            "p4_mean_rsi_vwap",
            "Test 9 + ATR stop + RSI 50 + VWAP breakdown exit",
            {**MEAN_EXIT_RSI, "VWAP_EXIT_ENABLED": True},
            False,
        ),
        ("p4_mean_rsi_slip", "Mean RSI exit + 0.05% slippage per leg", MEAN_EXIT_RSI, True),
        ("p4_control_slip", "Phase 2 winner + 0.05% slippage per leg", PHASE2_WINNER, True),
        (
            "p4_no_denylist",
            "Mean RSI exit, EXCLUDED_SYMBOLS cleared (selection-bias test)",
            {**MEAN_EXIT_RSI, "EXCLUDED_SYMBOLS": frozenset()},
            False,
        ),
    ]

    results: list[dict[str, Any]] = []
    for key, label, cfg, use_slip in variants:
        trades, stats = run_sim(symbol_dfs, regime, config=cfg, source=key)
        slip_stats = summarize_with_slippage(trades) if use_slip else None
        ex = exit_breakdown(trades)
        row = {
            "id": key,
            "label": label,
            "config": _cfg_for_json(cfg),
            "stats": stats,
            "slippage_stats": slip_stats,
            "exits": ex,
            "slippage_applied": use_slip,
        }
        results.append(row)
        if use_slip and slip_stats:
            print(
                f"{label:<52} trades={stats['trades']:>3}  "
                f"net=₹{stats['net_pnl_rs']:>6,.0f}  "
                f"slip_net=₹{slip_stats['net_pnl_rs']:>6,.0f}  sharpe={stats['sharpe']:.3f}"
            )
        else:
            print(
                f"{label:<52} trades={stats['trades']:>3}  "
                f"net=₹{stats['net_pnl_rs']:>6,.0f}  sharpe={stats['sharpe']:.3f}"
            )

    by_id = {r["id"]: r for r in results}
    control = by_id["p4_control"]["stats"]
    mean_rsi = by_id["p4_mean_rsi"]["stats"]
    mean_slip = by_id["p4_mean_rsi_slip"]["slippage_stats"] or {}
    control_slip = by_id["p4_control_slip"]["slippage_stats"] or {}

    beat_control = mean_rsi["net_pnl_rs"] >= control["net_pnl_rs"]
    slip_positive = mean_slip.get("net_pnl_rs", 0) > 0
    min_trades = mean_rsi["trades"] >= 15
    gate_passed = beat_control and min_trades

    print(
        f"\nPhase 4 gates: beat control={beat_control}  trades≥15={min_trades}  "
        f"mean+slip>0={slip_positive}"
    )
    if gate_passed and slip_positive:
        decision = (
            "PASS — mean RSI exit beats Phase 2 control and survives slippage stress. "
            "Review paper journal before changing .env exits."
        )
    elif beat_control:
        decision = (
            "PARTIAL — mean RSI exit beats control on net, but slippage or sample size fails. "
            "Keep paper stack; do not promote mean exit yet."
        )
    else:
        decision = (
            "FAIL — Phase 2 target-3.5 stack still wins vs mean exits on this window. "
            "Paper trial remains observational."
        )

    return {
        "results": results,
        "control_net_rs": control["net_pnl_rs"],
        "mean_rsi_net_rs": mean_rsi["net_pnl_rs"],
        "mean_rsi_slip_net_rs": mean_slip.get("net_pnl_rs"),
        "control_slip_net_rs": control_slip.get("net_pnl_rs"),
        "gates": {
            "beat_control": beat_control,
            "min_trades": min_trades,
            "slippage_positive": slip_positive,
            "pass_all": gate_passed and slip_positive,
        },
        "gate_passed": gate_passed and slip_positive,
        "decision": decision,
        "deferred": [
            "TIME_STOP_BARS exit (4–6 bars) — needs strategy/sim hook",
            "Top-100 volume universe — Sprint 5 (needs symbol list + cache)",
            "VWAP extension entry + volume surge block — Sprint 5 (strategy.py)",
            "≥150 trades statistical gate — Sprint 5",
        ],
    }


def write_phase4_findings(path: str, report: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    p4 = report["phase4"]
    lines = [
        "# Sprint 4 — Mean Exit Ablation + Friction",
        "",
        f"Generated: {report['generated_at']} | Window: {report['days']}d T2 | Source: {report['source']}",
        "",
        "Rationale: `data/research/GEMINI_CRITIQUE_AND_SPRINT4.md`",
        "",
        "## Variants",
        "",
        "| ID | Trades | Net ₹ | Sharpe | Slippage net ₹ |",
        "|----|--------|-------|--------|----------------|",
    ]
    for row in p4["results"]:
        s = row["stats"]
        slip = row.get("slippage_stats") or {}
        slip_net = f"**{slip['net_pnl_rs']:,.0f}**" if slip else "—"
        lines.append(
            f"| {row['id']} | {s['trades']} | **{s['net_pnl_rs']:,.0f}** | {s['sharpe']:.3f} | {slip_net} |"
        )

    g = p4["gates"]
    lines.extend([
        "",
        "## Gates",
        "",
        f"- Beat Phase 2 control (₹{p4['control_net_rs']:,.0f}): **{'PASS' if g['beat_control'] else 'FAIL'}** "
        f"(mean RSI net ₹{p4['mean_rsi_net_rs']:,.0f})",
        f"- Trades ≥ 15: **{'PASS' if g['min_trades'] else 'FAIL'}**",
        f"- Mean exit + slippage > 0: **{'PASS' if g['slippage_positive'] else 'FAIL'}** "
        f"(₹{p4.get('mean_rsi_slip_net_rs') or 0:,.0f})",
        f"- Overall: **{'PASS' if g['pass_all'] else 'FAIL'}**",
        "",
        "## Exit breakdown (mean RSI variant)",
        "",
        "| Exit | Trades | Net ₹ |",
        "|------|--------|-------|",
    ])
    mean_row = next(r for r in p4["results"] if r["id"] == "p4_mean_rsi")
    for ex in mean_row["exits"]["by_family"]:
        lines.append(f"| {ex['family']} | {ex['trades']} | {ex['net_pnl_rs']:,.0f} |")

    lines.extend([
        "",
        "## Deferred",
        "",
    ])
    for item in p4.get("deferred", []):
        lines.append(f"- {item}")

    lines.extend([
        "",
        "## Decision",
        "",
        p4["decision"],
        "",
    ])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def exit_breakdown(trades: list) -> dict[str, Any]:
    families: dict[str, list] = {}
    for t in trades:
        reason = t.exit_reason or "unknown"
        fam = reason.split(" (")[0] if " (" in reason else reason.split()[0:3]
        key = fam if isinstance(fam, str) else " ".join(fam)
        if key.startswith("ATR stop"):
            key = "ATR stop"
        elif key.startswith("ATR target"):
            key = "ATR target"
        families.setdefault(key, []).append(t)
    rows = []
    for key, subset in sorted(families.items(), key=lambda x: -len(x[1])):
        st = summarize_trades(subset)
        rows.append({
            "family": key,
            "trades": st["trades"],
            "net_pnl_rs": st["net_pnl_rs"],
            "gross_pnl_rs": st["gross_pnl_rs"],
        })
    stops = [t for t in trades if t.exit_reason and t.exit_reason.startswith("ATR stop")]
    stop_net = summarize_trades(stops).get("net_pnl_rs", 0) if stops else 0
    return {"by_family": rows, "atr_stop_count": len(stops), "atr_stop_net_rs": stop_net}


def phase1(symbol_dfs: dict, regime: Any) -> dict[str, Any]:
    print("\n=== PHASE 1 — Entry stack ===\n")
    results: list[dict[str, Any]] = []

    variants = [
        ("p1_test9_ref", "Test 9 ref (pivot + RSI>80 + hour<14 + denylist)", {**PIVOT_STACK}),
        ("p1_atr125", "Test 9 + ATR_STOP_MULT=1.25", {**PIVOT_STACK, "ATR_STOP_MULT": 1.25}),
        ("p1_atr100", "Test 9 + ATR_STOP_MULT=1.0", {**PIVOT_STACK, "ATR_STOP_MULT": 1.0}),
    ]
    for rsi in (82, 84, 85):
        variants.append((
            f"p1_rsi_{rsi}",
            f"Pivot stack + RSI>{rsi}",
            {**PIVOT_STACK, "RSI_OVERBOUGHT": float(rsi)},
        ))

    for key, label, cfg in variants:
        _, stats = run_sim(symbol_dfs, regime, config=cfg, source=key)
        row = {"id": key, "label": label, "config": {k: list(v) if isinstance(v, frozenset) else v for k, v in cfg.items()}, "stats": stats}
        results.append(row)
        print(
            f"{label:<45} trades={stats['trades']:>3}  gross=₹{stats['gross_pnl_rs']:>6,.0f}  "
            f"net=₹{stats['net_pnl_rs']:>6,.0f}  sharpe={stats['sharpe']:.3f}"
        )

    eligible = [r for r in results if r["stats"]["trades"] >= 15]
    pool = eligible if eligible else results
    best = max(pool, key=lambda r: r["stats"]["net_pnl_rs"])
    print(f"\nPhase 1 winner: {best['label']} — net ₹{best['stats']['net_pnl_rs']:,.0f}, {best['stats']['trades']} trades")
    return {"results": results, "winner": best, "gate_passed": best["stats"]["net_pnl_rs"] > -133 and best["stats"]["trades"] >= 15}


def phase2(symbol_dfs: dict, regime: Any, base_config: dict[str, Any]) -> dict[str, Any]:
    print("\n=== PHASE 2 — Exit tuning (on Phase 1 winner) ===\n")
    results: list[dict[str, Any]] = []

    for mult in (1.0, 1.25, 1.5, 1.75):
        cfg = {**base_config, "ATR_STOP_MULT": mult}
        trades, stats = run_sim(symbol_dfs, regime, config=cfg, source=f"p2_stop_{mult}")
        ex = exit_breakdown(trades)
        row = {"atr_stop_mult": mult, "stats": stats, "exits": ex}
        results.append(row)
        print(
            f"ATR stop {mult:<4}  trades={stats['trades']:>3}  net=₹{stats['net_pnl_rs']:>6,.0f}  "
            f"atr_stops={ex['atr_stop_count']}  stop_net=₹{ex['atr_stop_net_rs']:,.0f}"
        )

    best_stop = max(results, key=lambda r: r["stats"]["net_pnl_rs"])
    base_stop = best_stop["atr_stop_mult"]

    print(f"\n--- Target mult sweep (stop={base_stop}) ---\n")
    target_results: list[dict[str, Any]] = []
    for tgt in (2.5, 3.0, 3.5):
        cfg = {**base_config, "ATR_STOP_MULT": base_stop, "ATR_TARGET_MULT": tgt}
        trades, stats = run_sim(symbol_dfs, regime, config=cfg, source=f"p2_tgt_{tgt}")
        ex = exit_breakdown(trades)
        row = {"atr_target_mult": tgt, "atr_stop_mult": base_stop, "stats": stats, "exits": ex}
        target_results.append(row)
        print(
            f"ATR target {tgt:<3}  trades={stats['trades']:>3}  net=₹{stats['net_pnl_rs']:>6,.0f}  "
            f"sharpe={stats['sharpe']:.3f}"
        )

    best_tgt = max(target_results, key=lambda r: r["stats"]["net_pnl_rs"])
    final_cfg = {
        **base_config,
        "ATR_STOP_MULT": base_stop,
        "ATR_TARGET_MULT": best_tgt["atr_target_mult"],
    }
    trades, final_stats = run_sim(symbol_dfs, regime, config=final_cfg, source="p2_final")
    final_exits = exit_breakdown(trades)

    print(
        f"\nPhase 2 winner: stop={base_stop}, target={best_tgt['atr_target_mult']} — "
        f"net ₹{final_stats['net_pnl_rs']:,.0f}, sharpe {final_stats['sharpe']:.3f}"
    )
    return {
        "stop_sweep": results,
        "target_sweep": target_results,
        "final_config": {k: list(v) if isinstance(v, frozenset) else v for k, v in final_cfg.items()},
        "final_stats": final_stats,
        "final_exits": final_exits,
        "gate_passed": final_stats["net_pnl_rs"] >= 0 or final_stats["sharpe"] > 0,
    }


def phase3(final_config: dict[str, Any], final_stats: dict[str, Any]) -> dict[str, Any]:
    """Paper promotion checklist — sim validation only (no live market days in batch)."""
    print("\n=== PHASE 3 — Paper promotion checklist ===\n")
    env_lines = [
        "STRATEGY=rsi_mr",
        "ALLOW_SHORT=true",
        "ALLOW_LONG=false",
        "LIVE_TRADING=false",
        f"RSI_OVERBOUGHT={final_config.get('RSI_OVERBOUGHT', 80)}",
        "ENTRY_CUTOFF_TIME=14:00",
        "EXCLUDED_SYMBOLS=ONGC,SBIN,BAJFINANCE",
        "PIVOT_FILTER_ENABLED=true",
        "PIVOT_FILTER_MODE=proximity",
        "PIVOT_TOUCH_PCT=0.35",
        f"ATR_STOP_MULT={final_config.get('ATR_STOP_MULT', 1.5)}",
        f"ATR_TARGET_MULT={final_config.get('ATR_TARGET_MULT', 3.0)}",
        "USE_ATR_EXITS=true",
        "VWAP_FILTER_ENABLED=false",
    ]
    checklist = [
        "Sim net ≥ ₹0 or Sharpe > 0 before enabling pivot in paper .env",
        "Run 5–10 market days: python run_agent.py --once (paper)",
        "Compare journal net vs sim expectancy per trade",
        "Do not set LIVE_TRADING=true without explicit approval",
    ]
    promote = final_stats["net_pnl_rs"] >= 0 or final_stats["sharpe"] > 0
    if promote:
        checklist.insert(0, "PASS: sim gate met — safe to trial pivot stack in paper .env")
    else:
        checklist.insert(0, "HOLD: sim still negative — keep PIVOT_FILTER_ENABLED=false in paper")

    for line in checklist:
        print(f"  • {line}")
    print("\nRecommended paper .env block:")
    for line in env_lines:
        print(f"  {line}")

    return {
        "paper_env": env_lines,
        "checklist": checklist,
        "promote_pivot_to_paper": promote,
    }


def write_findings(path: str, report: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    p1 = report["phase1"]
    p2 = report["phase2"]
    p3 = report["phase3"]
    w1 = p1["winner"]
    fs = p2["final_stats"]

    lines = [
        "# Research Phase Findings",
        "",
        f"Generated: {report['generated_at']} | Window: {report['days']}d T2 | Source: {report['source']}",
        "",
        "## Phase 1 — Entry stack",
        "",
        "Goal: beat Test 9 reference (net −₹133, ≥15 trades).",
        "",
        "| Variant | Trades | Gross ₹ | Net ₹ | Sharpe |",
        "|---------|--------|---------|-------|--------|",
    ]
    for row in p1["results"]:
        s = row["stats"]
        lines.append(
            f"| {row['label']} | {s['trades']} | {s['gross_pnl_rs']:,.0f} | "
            f"**{s['net_pnl_rs']:,.0f}** | {s['sharpe']:.3f} |"
        )
    lines.extend([
        "",
        f"**Winner:** {w1['label']} — net ₹{w1['stats']['net_pnl_rs']:,.0f}, "
        f"{w1['stats']['trades']} trades, Sharpe {w1['stats']['sharpe']:.3f}.",
        f"**Gate:** {'PASS' if p1['gate_passed'] else 'FAIL'} (beat −₹133 with ≥15 trades).",
        "",
        "## Phase 2 — Exit tuning",
        "",
        f"Base: Phase 1 winner config.",
        "",
        "### ATR stop mult",
        "",
        "| ATR_STOP_MULT | Trades | Net ₹ | ATR stops | Stop net ₹ |",
        "|---------------|--------|-------|-----------|------------|",
    ])
    for row in p2["stop_sweep"]:
        s, e = row["stats"], row["exits"]
        lines.append(
            f"| {row['atr_stop_mult']} | {s['trades']} | **{s['net_pnl_rs']:,.0f}** | "
            f"{e['atr_stop_count']} | {e['atr_stop_net_rs']:,.0f} |"
        )
    lines.extend([
        "",
        "### ATR target mult (best stop)",
        "",
        "| ATR_TARGET_MULT | Trades | Net ₹ | Sharpe |",
        "|-----------------|--------|-------|--------|",
    ])
    for row in p2["target_sweep"]:
        s = row["stats"]
        lines.append(
            f"| {row['atr_target_mult']} | {s['trades']} | **{s['net_pnl_rs']:,.0f}** | {s['sharpe']:.3f} |"
        )
    lines.extend([
        "",
        f"**Final stack net:** ₹{fs['net_pnl_rs']:,.0f} | Sharpe {fs['sharpe']:.3f} | "
        f"{fs['trades']} trades | gross ₹{fs['gross_pnl_rs']:,.0f}.",
        f"**Gate:** {'PASS' if p2['gate_passed'] else 'FAIL'} (net ≥ 0 or Sharpe > 0).",
        "",
        "### Exit family breakdown (final stack)",
        "",
        "| Exit | Trades | Net ₹ |",
        "|------|--------|-------|",
    ])
    for row in p2["final_exits"]["by_family"]:
        lines.append(f"| {row['family']} | {row['trades']} | {row['net_pnl_rs']:,.0f} |")

    lines.extend([
        "",
        "## Phase 3 — Paper promotion",
        "",
        f"**Promote pivot to paper .env:** {'Yes' if p3['promote_pivot_to_paper'] else 'No — hold current Tier 1'}.",
        "",
        "### Checklist",
        "",
    ])
    for item in p3["checklist"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "### Recommended paper `.env` (research winner)",
        "",
        "```env",
        *p3["paper_env"],
        "```",
        "",
        "## Decision",
        "",
        report["decision"],
        "",
    ])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run research phases 1–4")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--source", type=str, default="cache")
    p.add_argument(
        "--phase",
        type=str,
        default="1,2,3",
        help="Comma-separated phases to run (1,2,3,4). Example: --phase 4",
    )
    p.add_argument("--output-json", type=str, default="data/research/phase_findings.json")
    p.add_argument("--output-md", type=str, default="data/research/PHASE_FINDINGS.md")
    p.add_argument("--output-json-4", type=str, default="data/research/phase4_findings.json")
    p.add_argument("--output-md-4", type=str, default="data/research/PHASE4_FINDINGS.md")
    return p.parse_args()


def _parse_phases(raw: str) -> set[int]:
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        n = int(part)
        if n not in (1, 2, 3, 4):
            raise ValueError(f"Invalid phase {n}; use 1, 2, 3, or 4")
        out.add(n)
    return out


def main() -> int:
    args = parse_args()
    setup_logger()

    try:
        phases = _parse_phases(args.phase)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    source = normalize_source(args.source or None)
    _, broker = init_research_session(source)
    symbol_dfs = load_symbol_dfs(T2_SYMBOLS, args.days, source, broker=broker)
    if not symbol_dfs:
        print("Error: no candle data", file=sys.stderr)
        return 1

    regime = build_regime(args.days, source, Config.REGIME_FILTER_ENABLED, broker=broker)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if 4 in phases and phases != {4}:
        print("Note: Phase 4 runs independently; phases 1–3 outputs unchanged.\n")

    report: dict[str, Any] = {
        "generated_at": generated_at,
        "days": args.days,
        "source": source,
        "phases_run": sorted(phases),
    }

    if phases & {1, 2, 3}:
        p1 = phase1(symbol_dfs, regime) if 1 in phases else None
        if 1 in phases and 2 in phases:
            winner_cfg = p1["winner"]["config"]
            base = dict(winner_cfg)
            if "EXCLUDED_SYMBOLS" in base and not isinstance(base["EXCLUDED_SYMBOLS"], frozenset):
                base["EXCLUDED_SYMBOLS"] = frozenset(base["EXCLUDED_SYMBOLS"])
            p2 = phase2(symbol_dfs, regime, base)
        elif 2 in phases:
            print("Error: phase 2 requires phase 1 winner config; run --phase 1,2 or 1,2,3", file=sys.stderr)
            return 1
        else:
            p2 = None

        if 3 in phases:
            if p2 is None:
                print("Error: phase 3 requires phase 2; run --phase 1,2,3", file=sys.stderr)
                return 1
            final_cfg = dict(p2["final_config"])
            if "EXCLUDED_SYMBOLS" in final_cfg and not isinstance(final_cfg["EXCLUDED_SYMBOLS"], frozenset):
                final_cfg["EXCLUDED_SYMBOLS"] = frozenset(final_cfg["EXCLUDED_SYMBOLS"])
            p3 = phase3(final_cfg, p2["final_stats"])
        else:
            p3 = None

        if p1 is not None:
            report["phase1"] = p1
        if p2 is not None:
            report["phase2"] = p2
        if p3 is not None:
            report["phase3"] = p3

        if p2 is not None and p3 is not None:
            final_cfg = p2["final_config"]
            if p2["gate_passed"]:
                report["decision"] = (
                    f"Proceed to paper trial with pivot stack (stop={final_cfg.get('ATR_STOP_MULT')}, "
                    f"target={final_cfg.get('ATR_TARGET_MULT')}, RSI>{final_cfg.get('RSI_OVERBOUGHT', 80)}). "
                    f"Sim net ₹{p2['final_stats']['net_pnl_rs']:,.0f}."
                )
            elif p1 is not None and p1["gate_passed"]:
                report["decision"] = (
                    "Entry stack improved vs Test 9 but exits still net negative. "
                    "Paper: enable pivot only after manual review; prioritize exit experiments."
                )
            else:
                report["decision"] = (
                    "Neither entry nor exit gate fully met. Keep paper Tier 1 without pivot; "
                    "continue exit-focused research on filtered rsi_mr."
                )
        elif p1 is not None:
            report["decision"] = "Phase 1 complete — run phases 2–3 for exit tuning."
        else:
            report["decision"] = "Phases 2–3 complete."

        os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
        if p1 is not None and p2 is not None and p3 is not None:
            write_findings(args.output_md, report)
            print(f"Report: {args.output_md}")
        print(f"JSON: {args.output_json}")

    if 4 in phases:
        p4 = phase4(symbol_dfs, regime)
        report4 = {
            "generated_at": generated_at,
            "days": args.days,
            "source": source,
            "phase4": p4,
            "decision": p4["decision"],
        }
        os.makedirs(os.path.dirname(args.output_json_4) or ".", exist_ok=True)
        with open(args.output_json_4, "w", encoding="utf-8") as fh:
            json.dump(report4, fh, indent=2, default=str)
        write_phase4_findings(args.output_md_4, report4)
        print(f"\nPhase 4 report: {args.output_md_4}")
        print(f"Phase 4 JSON: {args.output_json_4}")
        print(f"DECISION: {p4['decision']}")

    if not phases:
        print("Error: no phases selected", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
