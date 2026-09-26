# AGENTS.md — Intraday RSI+Volume Agent (Angel One)

Guide for AI agents and developers working in this repository.

## Project purpose

Autonomous **intraday** trading on **Angel One SmartAPI**. Default path is equity MIS. A paper-only NIFTY F&O path runs via `--mode fno` or `--mode both`. Equity cycle:

1. Screen configured universe (`SCAN_UNIVERSE`: **t2** paper default, or nifty50/100/200) on **15-min candles**
2. Find RSI extremes with **volume confirmation** (`screener.py` + `strategy.py`)
3. Apply optional **regime filters** (India VIX, Nifty EMA) via `market_regime.py`
4. Enter mean-reversion trades as **NSE MIS** (tuned profile: short-only)
5. Manage exits: RSI 50 mean exit, ATR stop (underwater only), optional time stop, EOD square-off (`agent.py` + `orders.py`)

**Paper trading is the default** (`LIVE_TRADING=false`). Never enable live trading unless the user explicitly asks.

## Architecture

```
run_agent.py          → CLI entry (--once, --mode equity|fno|both)
intraday_agent/
  agent.py            → Equity loop, market hours, square-off, guards
  agent_fno.py        → Paper NIFTY options loop (multi-arm, 15:10 exit)
  runner.py           → Shared Angel session for --mode both
  guard.py            → Anti-overtrading guards
  market_regime.py    → India VIX / Nifty EMA entry gate
  screener.py         → Universe scan (rate-limited candle fetches)
  strategy.py         → RSI + volume + VWAP + ATR + mean-reversion exits
  strategy_fno.py     → Intraday F&O arms (iron fly, EMA spread/buy, ORB short, expiry strangle)
  orders.py           → Paper/live OrderManager, position sizing
  orders_fno.py       → Multi-leg paper F&O (live placement refused)
  broker.py           → Angel SmartAPI: login, candles, LTP, orders
  instruments.py      → Scrip master cache → symboltoken lookup
  instruments_fno.py  → NFO OPTIDX resolve, nearest expiry, trading_dte
  config.py           → All settings from .env
  universe.py         → NIFTY_50, T2_SYMBOLS, nifty100/200 lists; SCAN_UNIVERSE routing
  learning/           → Journal, stats, ranker, backtest, walk-forward, meta_label, costs
tools/
  status.py, e2e_test.py, bootstrap_backtest.py, walk_forward.py, train_meta_label.py
  research_validation.py, report_journal.py, mine_patterns.py, export_journal.py
  research_phases.py, edge_search.py, time_stop_ablation.py, rerun_nifty200_research.py
  fno_smoke_test.py, fno_signal_study.py, capture_fno_candles.py
```

Data flow: `agent` → `screener` → `AdaptiveRanker` (optional) → `MetaLabelFilter` (optional) → `orders` → `broker.place_order`. On close, `orders` writes to `TradeJournal` (including `entry_features` when logged at entry).

Instrument tokens **must** come from `instruments.resolve()` — never pass bare symbols as tokens.

## Commands

```bash
python tools/status.py
python tools/e2e_test.py
python run_agent.py          # paper equity loop (default)
python run_agent.py --once   # single scan/manage cycle
python run_agent.py --mode fno --once
python run_agent.py --mode both   # equity + paper F&O, one Angel login
python tools/fno_smoke_test.py
python tools/fno_signal_study.py
python tools/capture_fno_candles.py
python tools/bootstrap_backtest.py --symbols RELIANCE,SBIN,TCS,HDFCBANK,INFY --days 60
python tools/walk_forward.py --symbols RELIANCE,SBIN,TCS,HDFCBANK,INFY --days 80 --train-days 40 --test-days 20
python tools/train_meta_label.py --source backtest,paper --min-samples 80 --evaluate --train
python tools/research_validation.py --meta-label --skip-rolling --skip-sizing --source yahoo --tier t1
python tools/candle_cache_status.py --bundle t2_180d
python tools/fetch_history.py --bundle t2_180d --source angel
python tools/edge_search.py --tier t2 --rounds 2 --universe-test --capital 50000
python tools/time_stop_ablation.py --capital 50000
python tools/research_phases.py --phase 4 --tier t200
python tools/report_journal.py --source backtest
python tools/mine_patterns.py --source backtest
```

Backtest learnings and tuned defaults: see `USER_GUIDE.md` §11b. Meta-label workflow: §11d.

**Backtest data:** `RESEARCH_DATA_SOURCE=cache` (default) reads `data/candles/` parquet; prefetch with `fetch_history.py`, force live API with `--source angel`.

Market hours: **09:15–15:30 IST**, weekdays. Square-off default: **15:15 IST**.

## Configuration

- Secrets and tunables: `.env` (never commit; see `.env.example` for template)
- New env vars: add to `intraday_agent/config.py` **and** `.env.example` with sensible defaults
- Strategy thresholds: `RSI_*`, `VOLUME_MA_*`, `STOP_LOSS_PCT`, `TARGET_PCT`, `MAX_POSITIONS`
- Learning: `LEARNING_*` in `config.py` / `.env.example`; see `.cursor/rules/learning.mdc`

## Safety rules (mandatory)

1. **Do not commit** `.env`, credentials, or TOTP secrets
2. **Default to paper mode** — do not set `LIVE_TRADING=true` in code or docs without user request
3. **Do not remove** EOD square-off, stop-loss, or max-position guards without explicit approval
4. **Respect Angel rate limits** — keep `SCREENER_DELAY_SEC` when scanning 50 symbols
5. **Validate** Angel credentials via `Config.validate()` before broker login

## Coding conventions

- Keep logic in `intraday_agent/`; root holds only `run_agent.py`, docs, config templates
- Extend behavior via the `Strategy` ABC in `strategy.py` — avoid duplicating signal logic in `agent.py`
- Use `logging` (via `logging_setup.py`); log trades through `log_trade()`
- Prefer small, focused diffs; match existing module style (dataclasses, type hints, `from __future__ import annotations`)
- Python 3.9+ compatible

## Out of scope (unless user requests)

- Heavy ML (XGBoost/RL/neural nets) — use lightweight journal stats and optional **logistic meta-label** only (`learning/meta_label.py`)
- TradingView webhooks / ZP Pine script integration (deferred; use pluggable Strategy if adding later)
- Live NFO order placement, naked shorts, futures, crypto (Delta), Docker deployment
- Paper NIFTY options are in-repo (`*_fno.py`); see `data/research/OPTIONS_FNO_ANALYSIS.md`. Live F&O stays blocked.
- NSE website scraping — use Angel `getCandleData` only

## Common tasks

| Task | Where to change |
|------|-----------------|
| Adjust RSI/volume entry rules | `strategy.py`, `.env.example` |
| Change watchlist | `universe.py`, `SCAN_UNIVERSE` in `.env` |
| Position sizing / paper vs live | `orders.py`, `config.py` |
| Broker API / candles | `broker.py` |
| New exit rule | `agent.py` `manage_positions()` |
| Token / symbol resolution | `instruments.py` |
| Adaptive symbol ranking | `learning/ranker.py`, `learning/stats.py`, `LEARNING_*` env |
| Bootstrap / walk-forward | `tools/bootstrap_backtest.py`, `tools/walk_forward.py`, `learning/backtest.py`, `learning/walk_forward.py` |
| Meta-label filter | `learning/meta_label.py`, `learning/entry_features.py`, `tools/train_meta_label.py`, `META_LABEL_*` env |
| Research ablations | `tools/research_validation.py` (`--meta-label`, `--source yahoo|angel|cache`) |
| Regime filter (VIX/Nifty) | `market_regime.py`, `REGIME_*`, `VIX_MAX` in config |
| Net P&L reporting | `learning/costs.py`, `ESTIMATED_COST_PER_TRADE` |
| Paper F&O arms / exits | `strategy_fno.py`, `orders_fno.py`, `agent_fno.py`, `FNO_*` env |
| F&O research / paper log | `data/research/OPTIONS_FNO_ANALYSIS.md`, `tools/fno_signal_study.py` |

## Testing changes

- Syntax: `python3 -m py_compile run_agent.py intraday_agent/*.py intraday_agent/learning/*.py tools/*.py`
- Health: `python tools/status.py`
- Strategy unit test pattern: synthetic DataFrame in `strategy.py` `__main__` or inline script with oversold + volume spike
- Full integration requires Angel credentials and market hours; use `--once` in paper mode

## Legacy / ignore

- `backtest_results/` — root-owned artifacts from old project; not used by current agent
- Do not reintroduce deleted modules: webhook server, Delta crypto, `strategies/` folder
