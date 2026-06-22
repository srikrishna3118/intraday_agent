#!/usr/bin/env python3
"""Compare pluggable strategies on bootstrap and walk-forward net P&L.

Note: uses per-symbol simulation (no MAX_POSITIONS / TradeGuard). For portfolio-realistic
comparison use tools/strategy_bakeoff.py on the 180d T2 cache.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict

from intraday_agent.config import Config
from intraday_agent.learning.backtest import simulate_symbol
from intraday_agent.learning.costs import summarize_pnl
from intraday_agent.learning.journal import TradeJournal
from intraday_agent.learning.research_data import (
    build_regime,
    init_research_session,
    load_symbol_dfs,
    normalize_source,
    source_label,
)
from intraday_agent.learning.walk_forward import run_walk_forward
from intraday_agent.logging_setup import setup_logger
from intraday_agent.strategy import get_strategy, list_strategies

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = "RELIANCE,SBIN,TCS,HDFCBANK,INFY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy bake-off: net P&L comparison")
    parser.add_argument("--days", type=int, default=80, help="History days to fetch")
    parser.add_argument("--train-days", type=int, default=40, help="Walk-forward IS days")
    parser.add_argument("--test-days", type=int, default=20, help="Walk-forward OOS days")
    parser.add_argument("--symbols", type=str, default=DEFAULT_SYMBOLS, help="Comma-separated symbols")
    parser.add_argument(
        "--strategies",
        type=str,
        default="",
        help=f"Comma-separated strategy keys (default: all). Choices: {', '.join(list_strategies())}",
    )
    parser.add_argument(
        "--skip-walk-forward",
        action="store_true",
        help="Only run full-period bootstrap comparison",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="",
        help="cache | angel | yahoo (default: RESEARCH_DATA_SOURCE=cache)",
    )
    return parser.parse_args()


def _win_rate(trades) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    return round(100 * wins / len(trades), 1)


def run_bootstrap_compare(
    symbol_dfs: dict,
    strategy_names: list[str],
    regime: MarketRegime | None,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in strategy_names:
        strategy = get_strategy(name)
        trades = []
        for symbol, df in symbol_dfs.items():
            trades.extend(
                simulate_symbol(
                    symbol,
                    df,
                    strategy,
                    journal=None,
                    regime=regime,
                    source=f"compare_{name}",
                )
            )
        stats = summarize_pnl([asdict(t) for t in trades])
        stats["win_rate_pct"] = _win_rate(trades)
        out[name] = stats
        logger.info(
            "%s bootstrap: %d trades net Rs %s",
            name,
            stats["trades"],
            stats["net_pnl_rs"],
        )
    return out


def run_walkforward_compare(
    symbol_dfs: dict,
    strategy_names: list[str],
    train_days: int,
    test_days: int,
    regime: MarketRegime | None,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in strategy_names:
        journal = TradeJournal()
        journal.clear_source("walkforward_is")
        journal.clear_source("walkforward_oos")
        try:
            result = run_walk_forward(
                symbol_dfs,
                train_days=train_days,
                test_days=test_days,
                strategy=get_strategy(name),
                journal=journal,
                warmup_days=5,
                clear_existing=True,
                regime=regime,
            )
        except ValueError as exc:
            logger.warning("%s walk-forward skipped: %s", name, exc)
            out[name] = {"error": str(exc)}
            continue
        out[name] = {
            "is": result["is"],
            "oos": result["oos"],
            "verdict": result["verdict"],
        }
    return out


def _print_bootstrap_table(results: dict[str, dict]) -> None:
    print("\n=== Bootstrap comparison (full period, net P&L) ===")
    print(f"{'Strategy':<16} {'Trades':>6} {'Win%':>6} {'Gross':>10} {'Costs':>10} {'Net':>10} {'Avg/trade':>10}")
    print("-" * 72)
    for name, s in sorted(results.items(), key=lambda x: x[1].get("net_pnl_rs", 0), reverse=True):
        print(
            f"{name:<16} {s['trades']:>6} {s.get('win_rate_pct', 0):>5.1f}% "
            f"₹{s['gross_pnl_rs']:>8,.0f} ₹{s['total_costs_rs']:>8,.0f} "
            f"₹{s['net_pnl_rs']:>8,.0f} ₹{s['avg_net_per_trade_rs']:>8,.1f}"
        )


def _print_walkforward_table(results: dict[str, dict]) -> None:
    print("\n=== Walk-forward comparison (IS / OOS net P&L) ===")
    print(f"{'Strategy':<16} {'IS net':>10} {'OOS net':>10} {'IS tr':>6} {'OOS tr':>7} {'Verdict'}")
    print("-" * 72)
    ranked = []
    for name, r in results.items():
        if "error" in r:
            print(f"{name:<16} {'—':>10} {'—':>10} {'—':>6} {'—':>7} {r['error']}")
            continue
        is_n = r["is"]["net_pnl_rs"]
        oos_n = r["oos"]["net_pnl_rs"]
        ranked.append((name, oos_n, r))
        print(
            f"{name:<16} ₹{is_n:>8,.0f} ₹{oos_n:>8,.0f} "
            f"{r['is']['trades']:>6} {r['oos']['trades']:>7} {r['verdict']}"
        )
    if ranked:
        winner = max(ranked, key=lambda x: x[1])
        print(f"\nRecommended (by OOS net): **{winner[0]}** (OOS ₹{winner[1]:,.0f})")


def main() -> int:
    args = parse_args()
    setup_logger()

    strategy_names = (
        [s.strip().lower() for s in args.strategies.split(",") if s.strip()]
        if args.strategies
        else list_strategies()
    )
    for name in strategy_names:
        get_strategy(name)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    source = normalize_source(args.source or None)
    _, broker = init_research_session(source)

    symbol_dfs = load_symbol_dfs(symbols, args.days, source, broker=broker)
    if not symbol_dfs:
        print(
            f"Error: no candle data (source={source}). "
            "Prefetch: python tools/fetch_history.py --bundle t2_180d --source angel",
            file=sys.stderr,
        )
        return 1

    regime = build_regime(args.days, source, Config.REGIME_FILTER_ENABLED, broker=broker)

    print(f"\nStrategy bake-off: {len(symbol_dfs)} symbols, ~{args.days} days ({source_label(source)})")
    print(f"Strategies: {', '.join(strategy_names)}")
    print(f"Regime filter: {'on' if Config.REGIME_FILTER_ENABLED else 'off'}")

    bootstrap = run_bootstrap_compare(symbol_dfs, strategy_names, regime)
    _print_bootstrap_table(bootstrap)

    if not args.skip_walk_forward:
        wf = run_walkforward_compare(
            symbol_dfs,
            strategy_names,
            args.train_days,
            args.test_days,
            regime,
        )
        _print_walkforward_table(wf)

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
