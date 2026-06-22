# Intraday RSI+Volume Agent (Angel One)

Autonomous intraday equity trading agent for **Angel One SmartAPI**. Each cycle it screens the **Nifty 50** on 15-minute candles for RSI extremes confirmed by volume, applies optional **market regime** filters, and trades **NSE intraday MIS** setups.

**Current tuned profile (after backtesting):** short-only mean reversion, ATR exits, ATR trailing stop, India VIX gate. See [Backtesting learnings](#backtesting-learnings) below.

**Paper trading is the default.** Set `LIVE_TRADING=true` only after paper validation and walk-forward checks.

**Full documentation:** [USER_GUIDE.md](USER_GUIDE.md) — setup, configuration, strategy, backtesting, troubleshooting.

For AI agents and contributors, see [AGENTS.md](AGENTS.md). Cursor rules live in `.cursor/rules/`.

## Strategy (current)

| Layer | Rule |
|-------|------|
| **Entry (short)** | RSI > `RSI_OVERBOUGHT` + volume in band (`VOLUME_MA_MULT`–`VOLUME_MA_MAX_MULT` × SMA) + before `ENTRY_CUTOFF_TIME` |
| **Entry (long)** | Disabled by default (`ALLOW_LONG=false`) — backtests showed longs were net-negative after costs |
| **Regime** | Skip shorts when India VIX > `VIX_MAX` (default 18). Optional Nifty < EMA filter (`NIFTY_REGIME_ENABLED`) |
| **Exit** | ATR stop/target (`USE_ATR_EXITS`), ATR **trailing stop**, RSI mid-line, EOD square-off |
| **Risk** | `TradeGuard` daily caps, cooldowns, daily loss/profit halts |

Optional filters (off in tuned profile): session VWAP entry filter (`VWAP_FILTER_ENABLED`), VWAP breakdown exit (`VWAP_EXIT_ENABLED` — backtests showed this hurt net P&L).

This is a **research-tuned scaffold**, not a guaranteed edge. Always validate with **net P&L** (after costs) and **walk-forward OOS** before live trading.

## Prerequisites

- Python 3.9+
- Angel One trading account + SmartAPI credentials (API key, client ID, password, TOTP secret)
- Market hours: 09:15–15:30 IST, weekdays

## Setup

```bash
cd /home/acharya/trading/Auto_trading
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Angel credentials
```

## Run

Health check and smoke test:

```bash
python tools/status.py
python tools/e2e_test.py              # login + candles + LTP
python tools/e2e_test.py --symbol SBIN
```

Paper mode (default):

```bash
python run_agent.py
python run_agent.py --once            # single cycle during market hours
```

Go live (real orders — only after validation):

```bash
# In .env: LIVE_TRADING=true
python run_agent.py
```

## Backtesting

Seed journal and report **gross + net P&L** (₹42/trade default cost):

```bash
python tools/bootstrap_backtest.py --symbols RELIANCE,SBIN,TCS,HDFCBANK,INFY --days 60
python tools/walk_forward.py --symbols RELIANCE,SBIN,TCS,HDFCBANK,INFY --days 80 --train-days 40 --test-days 20
python tools/report_journal.py --source backtest
python tools/mine_patterns.py --source backtest
```

**Meta-label filter** (optional; default off — see [USER_GUIDE.md §11d](USER_GUIDE.md#11d-meta-label-trade-filter)):

```bash
# Bootstrap labels → train + OOS evaluate → save model
python tools/bootstrap_backtest.py --symbols RELIANCE,SBIN,TCS,HDFCBANK,INFY --days 60
python tools/train_meta_label.py --source backtest,paper --min-samples 80 --evaluate --train

# Compare meta_label vs VIX+ADX ablations (Yahoo-aligned with paper screener)
python tools/research_validation.py --meta-label --skip-rolling --skip-sizing --source yahoo --tier t1
```

Walk-forward splits history into **in-sample** and **out-of-sample** windows with the same `.env` params (no tuning on OOS). See [USER_GUIDE.md § Backtesting learnings](USER_GUIDE.md#11b-backtesting-learnings).

### Offline 6-month cache (T2 bundle)

**Backtests default to local parquet** (`RESEARCH_DATA_SOURCE=cache`) — no Angel login unless you pass `--source angel`.

Prefetched Angel 15m candles live in `data/candles/*.parquet` (gitignored). Reuse without API calls:

```bash
# Prefetch + manifest (once, or to refresh)
python tools/fetch_history.py --bundle t2_180d --source angel

# Inspect coverage
python tools/candle_cache_status.py --bundle t2_180d

# Portfolio backtest offline (~180d, 30 T2 symbols + VIX/Nifty)
python tools/research_validation.py --days 180 --tier t2 --source cache --skip-sizing
```

Bundle definition: `research/bundles/t2_180d.json`. Manifest: `data/research/candle_cache_t2_180d.json`.

## Backtesting learnings

Tested on 5 symbols (RELIANCE, SBIN, TCS, HDFCBANK, INFY) over ~60–80 trading days, 15m bars, ₹42/trade estimated Angel MIS cost.

| Finding | Action taken |
|---------|--------------|
| Gross profit ≠ edge — 70 trades at +₹605 gross was **−₹2,335 net** | Always report net P&L; use `ESTIMATED_COST_PER_TRADE` |
| **Longs lost after costs**; shorts profitable | `ALLOW_LONG=false` |
| More trades ≠ better net — 65 trades net −₹2,702 vs 28 shorts net +₹164 | Prefer selective entries over loose thresholds |
| VWAP **exit** cut winners early (7/9 on VWAP breakdown) | `VWAP_EXIT_ENABLED=false` |
| VWAP **entry** filter very selective (9 vs 28 trades) | `VWAP_FILTER_ENABLED=false` for more activity |
| ATR exits + **trailing** (activate 1.0× ATR, trail 1.0× ATR) | +₹94 net vs no trailing on same 28 trades |
| **VIX ≤ 18** gate passes walk-forward IS **and** OOS | `REGIME_FILTER_ENABLED=true`, `VIX_MAX=18` |
| Nifty < 20 EMA gate blocked almost all IS trades | `NIFTY_REGIME_ENABLED=false` |
| RSI 28/75 + volume 1.2–2.0× + entry cutoff 14:30 | Reduced noise vs 30/70 defaults |
| Walk-forward OOS +₹223 (no regime) → **+₹101 IS / +₹101 OOS** with VIX-only | Validates regime filter generalizes |

**Recommended validation workflow:** bootstrap backtest → walk-forward → pattern mining → paper trade → live (small size).

Research uses **offline cache by default** (`RESEARCH_DATA_SOURCE=cache`). See [USER_GUIDE.md §11e](USER_GUIDE.md#11e-offline-candle-cache--phase-b-research) and Phase B verdict there.

## Project layout

```
Auto_trading/
  run_agent.py              # CLI entry
  intraday_agent/
    agent.py                # Main loop + guards
    broker.py               # Angel SmartAPI
    guard.py                # Anti-overtrading guards
    market_regime.py        # India VIX / Nifty EMA gate
    instruments.py          # Scrip master / token lookup
    universe.py             # Nifty 50 list
    screener.py             # RSI + volume scan
    strategy.py             # RSI, VWAP, ATR, trailing exits
    orders.py               # Paper/live execution + trade journal
    config.py               # Settings from .env
    learning/
      journal.py            # SQLite trade log
      stats.py              # Per-symbol rolling stats
      ranker.py             # AdaptiveRanker
      backtest.py           # Bar-by-bar simulation
      walk_forward.py       # IS/OOS validation
      meta_label.py         # Logistic meta-label filter (train/predict)
      entry_features.py     # Entry-time feature vector for journal + ML
      costs.py              # Net P&L after commissions
  tools/
    status.py               # Health check
    e2e_test.py             # Login + candle smoke test
    bootstrap_backtest.py   # Historical backtest → journal
    walk_forward.py         # In-sample / out-of-sample validation
    train_meta_label.py     # Train/evaluate meta-label from journal
    research_validation.py  # Portfolio ablations (base/vix/adx/both/meta_label)
    report_journal.py       # P&L charts + summary
    mine_patterns.py        # Pattern mining by exit/symbol/hour
    export_journal.py       # CSV export
  data/
    instruments.json        # Cached scrip master (auto-created)
    trade_journal.db        # Trade outcomes (auto-created)
  logs/                     # Daily logs
```

## Configuration

All settings live in `.env`. See `.env.example` and [USER_GUIDE.md § Configuration](USER_GUIDE.md#5-configuration-reference).

**Key groups:**

| Group | Variables |
|-------|-----------|
| Sizing | `CAPITAL_PER_TRADE`, `MAX_QUANTITY`, `MAX_POSITIONS` |
| Signals | `RSI_*`, `VOLUME_MA_*`, `ENTRY_CUTOFF_TIME`, `ALLOW_LONG`, `ALLOW_SHORT` |
| Exits | `USE_ATR_EXITS`, `ATR_*`, `TRAILING_STOP_*`, `STOP_LOSS_PCT`, `TARGET_PCT` |
| Filters | `VWAP_*`, `REGIME_FILTER_ENABLED`, `VIX_MAX`, `NIFTY_REGIME_ENABLED` |
| Costs | `ESTIMATED_COST_PER_TRADE` (0 = Angel MIS formula) |
| Guards | `MAX_TRADES_PER_DAY`, `MAX_DAILY_LOSS`, `MAX_DAILY_PROFIT`, … |
| Learning | `LEARNING_ENABLED`, `LEARNING_*` |
| Meta-label | `META_LABEL_ENABLED`, `META_LABEL_THRESHOLD`, `META_LABEL_MODEL_PATH` |

### Adaptive learning (optional)

When `LEARNING_ENABLED=true`, the agent ranks screener candidates using rolling win rates from closed trades. RSI+volume rules still generate signals; learning only filters chronic losers and re-orders entries.

Bootstrap the journal from historical data before paper trading with learning on:

```bash
python tools/bootstrap_backtest.py --days 60
python tools/bootstrap_backtest.py --symbols RELIANCE,SBIN --days 60
```

For the optional meta-label filter workflow (bootstrap → train → evaluate), see [USER_GUIDE.md §11d](USER_GUIDE.md#11d-meta-label-trade-filter).

Edit `intraday_agent/universe.py` when Nifty 50 constituents change.

## Disclaimer

For educational use. Trading involves substantial risk. Backtest and paper results do not guarantee live performance. Test thoroughly in paper mode. The authors are not responsible for financial losses.
