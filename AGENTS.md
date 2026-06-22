# AGENTS.md — Intraday RSI+Volume Agent (Angel One)

Guide for AI agents and developers working in this repository.

## Project purpose

Autonomous **intraday equity** trading on **Angel One SmartAPI**. Each cycle:

1. Screen **Nifty 50** (`intraday_agent/universe.py`) on **15-min candles**
2. Find RSI extremes with **volume confirmation** (`screener.py` + `strategy.py`)
3. Apply optional **regime filters** (India VIX, Nifty EMA) via `market_regime.py`
4. Enter mean-reversion trades as **NSE MIS** (tuned profile: short-only)
5. Manage exits: ATR stop/target, trailing stop, RSI mid-line, EOD square-off (`agent.py` + `orders.py`)

**Paper trading is the default** (`LIVE_TRADING=false`). Never enable live trading unless the user explicitly asks.

## Architecture

```
run_agent.py          → CLI entry (--once for single cycle)
intraday_agent/
  agent.py            → Main loop, market hours, square-off, guards
  guard.py            → Anti-overtrading guards
  market_regime.py    → India VIX / Nifty EMA entry gate
  screener.py         → Nifty 50 scan (rate-limited candle fetches)
  strategy.py         → RSI + volume + VWAP + ATR + trailing exits
  orders.py           → Paper/live OrderManager, position sizing
  broker.py           → Angel SmartAPI: login, candles, LTP, orders
  instruments.py      → Scrip master cache → symboltoken lookup
  config.py           → All settings from .env
  universe.py         → Static NIFTY_50 list (edit when index changes)
  learning/           → Journal, stats, ranker, backtest, walk-forward, meta_label, costs
tools/
  status.py, e2e_test.py, bootstrap_backtest.py, walk_forward.py, train_meta_label.py
  research_validation.py, report_journal.py, mine_patterns.py, export_journal.py
```

Data flow: `agent` → `screener` → `AdaptiveRanker` (optional) → `MetaLabelFilter` (optional) → `orders` → `broker.place_order`. On close, `orders` writes to `TradeJournal` (including `entry_features` when logged at entry).

Instrument tokens **must** come from `instruments.resolve()` — never pass bare symbols as tokens.

## Commands

```bash
python tools/status.py
python tools/e2e_test.py
python run_agent.py          # paper loop (default)
python run_agent.py --once   # single scan/manage cycle
python tools/bootstrap_backtest.py --symbols RELIANCE,SBIN,TCS,HDFCBANK,INFY --days 60
python tools/walk_forward.py --symbols RELIANCE,SBIN,TCS,HDFCBANK,INFY --days 80 --train-days 40 --test-days 20
python tools/train_meta_label.py --source backtest,paper --min-samples 80 --evaluate --train
python tools/research_validation.py --meta-label --skip-rolling --skip-sizing --source yahoo --tier t1
python tools/candle_cache_status.py --bundle t2_180d
python tools/fetch_history.py --bundle t2_180d --source angel
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
- Options, futures, crypto (Delta), Docker deployment
- NSE website scraping — use Angel `getCandleData` only

## Common tasks

| Task | Where to change |
|------|-----------------|
| Adjust RSI/volume entry rules | `strategy.py`, `.env.example` |
| Change watchlist | `universe.py` |
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

## Testing changes

- Syntax: `python3 -m py_compile run_agent.py intraday_agent/*.py intraday_agent/learning/*.py tools/*.py`
- Health: `python tools/status.py`
- Strategy unit test pattern: synthetic DataFrame in `strategy.py` `__main__` or inline script with oversold + volume spike
- Full integration requires Angel credentials and market hours; use `--once` in paper mode

## Legacy / ignore

- `backtest_results/` — root-owned artifacts from old project; not used by current agent
- Do not reintroduce deleted modules: webhook server, Delta crypto, `strategies/` folder
