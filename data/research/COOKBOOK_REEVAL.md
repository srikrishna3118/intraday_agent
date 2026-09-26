# Cookbook Analysis & Strategy Reevaluation — Aug 4, 2026

**Source:** Pushpak Dagade, *Python Algorithmic Trading Cookbook* (Packt, 2020), 528 pp.  
**Local copy:** `/home/acharya/Downloads/python-algorithmic-trading-cookbook-strategies.pdf`  
**Scope:** Docs-only reevaluation against this repo. No new strategies implemented. No live trading.

---

## 1. Verdict

The cookbook is an **AlgoBulls / `pyalgotrading` tutorial**, not a catalog of proven NSE MIS edges. Its only two coded strategies are **EMA(4/9) crossover** and **MACD line/signal crossover** — both **trend-flip** systems.

That class is already falsified in this repo by:

| Strategy | Net (180d T2) | Trades | Artifact |
|----------|---------------|--------|----------|
| `orb` | **−₹42,430** | 1,077 | [strategy_compare_orb_vwap_tier2.md](strategy_compare_orb_vwap_tier2.md) |
| `vwap_pullback` | **−₹42,295** | 1,054 | same |

**Keep for paper:** `STRATEGY=rsi_mr` on `SCAN_UNIVERSE=t2` — edge search **+₹2,438** / Sharpe **1.49** / 26 trades ([EDGE_VALIDATED.md](EDGE_VALIDATED.md)).

**Do not implement or promote:** cookbook EMA/MACD, ORB/VWAP as MR replacements, Quadapt, Pine ports. Next priority remains **P3 paper validation**, not new entry strategies.

---

## 2. Cookbook map → repo

| Cookbook content | Repo status |
|------------------|---------------|
| Ch 1–4: datetime, broker primer, candles | Covered by Angel SmartAPI + [`broker.py`](../../intraday_agent/broker.py) / candle cache |
| Ch 5: SMA/EMA, MACD, RSI, Bollinger, ATR, OBV, VWAP | RSI / ATR / VWAP / EMA / MACD used in [`strategy.py`](../../intraday_agent/strategy.py); Bollinger & PSAR unused |
| Ch 6–7: regular / bracket / cover / trailing | Angel MIS + software ATR stop; bracket OCO not used (not required for paper) |
| Ch 8–11: EMA + MACD strategies + AlgoBulls BT/paper/live | **Not implemented**; trend class already rejected |
| Appendix III: seasons, params, BT ≠ live, broker limits, tech failures | Aligns with P3 paper gate, fixed T2 stack, cost/sizing work |

### Cookbook strategy rules (Ch 8)

**EMA-Regular-Order**

- Indicators: EMA(4), EMA(9) (parametrised)
- Orders: BUY/SELL, regular, INTRADAY, market
- Logic: EMA4 crosses EMA9 **up** → exit short + enter long; **down** → exit long + enter short

**MACD-Bracket-Order**

- Indicators: MACD line + signal (histogram unused for signals)
- Orders: BUY/SELL, bracket, INTRADAY, limit; SL / target / trailing as params
- Logic: MACD line crosses signal **up** → exit short + long; **down** → exit long + short

Both are **always-in / flip-on-crossover** designs. They generate far more trades than filtered rsi_mr (~1 trade / 10 days on T2), so ₹42/trade friction dominates — same failure mode as ORB/VWAP compares.

---

## 3. Cookbook vs production stack (side-by-side)

| Dimension | Cookbook EMA / MACD | Repo `rsi_mr` (paper) | Repo `orb` / `vwap_pullback` |
|-----------|---------------------|------------------------|------------------------------|
| Edge type | Trend flip | Mean-reversion short | Trend / breakout |
| Entry | MA crossover | RSI > 80 + volume + pivot | OR break / VWAP pullback |
| Exit | Opposite cross (EMA) or bracket SL/target/trail (MACD) | RSI 50 first; ATR stop underwater only; trailing **off** | Range/ATR + optional trail |
| Trade rate | High (every cross) | Low (filtered) | Very high (1k+ / 180d) |
| Universe fit | Book uses AlgoBulls instrument bucket | **T2 only** (30 liquid) | Failed even on T2 |
| Evidence here | Not coded (redundant) | **+₹2,438** validated stack | **−₹42k** each |
| Paper action | **Do not add** | **KEEP** | **KILL** for paper/live |

---

## 4. Full registry reevaluation (11 strategies)

Source: `STRATEGY_REGISTRY` in [`intraday_agent/strategy.py`](../../intraday_agent/strategy.py). Paper default: `STRATEGY=rsi_mr`, `REGIME_ADAPTIVE=false`.

| Key | Role | Key evidence | Reeval |
|-----|------|--------------|--------|
| **rsi_mr** | Active paper | Edge search +₹2,438 (T2, ₹50k); Sprint 4 +₹347 / 17 trades | **KEEP** — sole paper strategy |
| orb | Regime adaptive target | −₹42,430 / 1,077 trades | **KILL** for paper/live; code retained |
| vwap_pullback | Trend pullback | −₹42,295 / 1,054 trades | **KILL** |
| vwap_mr | VWAP fade entry | Handbook FAIL (negative) | **SHELVE** |
| open_fade | Gap exhaustion | Handbook FAIL | **SHELVE** |
| rs_mr | RS pullback long | Handbook FAIL | **SHELVE** |
| rsi_div | Pine divergence | −₹5,029 / 119 trades | **SHELVE** |
| zp_dmi | DMI confluence | −₹5,841 / 141 (handbook); zp_dmi_sd also FAIL | **SHELVE** |
| vst_ai | Volume SuperTrend AI | −₹12,261 / 268 trades | **SHELVE** |
| sbp_tm | SBP trend+momentum | −₹21,363 / 484 trades | **SHELVE** |
| quadapt_ml | MLMA + order blocks | T2 −₹372 / 8; T200 −₹6,135 | **SHELVE** (archive) |
| *(not registered)* Cookbook EMA / MACD | Trend flip | Same class as ORB/VWAP | **Do not implement** for paper |

Citations: [EDGE_VALIDATED.md](EDGE_VALIDATED.md), [strategy_compare_orb_vwap_tier2.md](strategy_compare_orb_vwap_tier2.md), [RESEARCH_HANDBOOK.md](RESEARCH_HANDBOOK.md) §strategy table, `*_bakeoff_verdict*.md`.

---

## 5. Appendix III caveats → current plan

| Cookbook caveat | Repo response |
|-----------------|---------------|
| Profitability is seasonal | Log paper sessions by date/month in [paper_trial_log.md](paper_trial_log.md); do not overfit one week |
| Params + instrument matter | Fixed validated stack: T2, ATR 1.25, entry cutoff 13:00, ₹50k; no free param sweep |
| Backtest alone ≠ profitability | **P3:** ≥15 paper sessions before any live discussion |
| Bracket compulsory SL | ATR stop when underwater already on; time-stop ablation failed → keep `TIME_STOP_BARS=0` |
| Broker API / tech failures | Angel rate-limit pause, paper default, no dual-host same day ([ROADMAP_STATUS.md](ROADMAP_STATUS.md)) |

---

## 6. Explicit non-goals (from this review)

- Do **not** add EMA/MACD strategies to `STRATEGY_REGISTRY` for paper
- Do **not** integrate `pyalgotrading` / AlgoBulls
- Do **not** port Bollinger / PSAR as new entry strategies
- Do **not** enable `REGIME_ADAPTIVE=true` (ORB path)
- Do **not** expand `SCAN_UNIVERSE` beyond `t2` until P3 gate passes

A dedicated EMA/MACD falsification bake-off is **unnecessary** given ORB/VWAP precedent on the same cost model and universe.

---

## 7. Next step

**P3 paper validation** on the validated stack only:

```env
STRATEGY=rsi_mr
SCAN_UNIVERSE=t2
CAPITAL_PER_TRADE=50000
ATR_STOP_MULT=1.25
ENTRY_CUTOFF_TIME=13:00
TRAILING_STOP_ENABLED=false
LIVE_TRADING=false
```

```bash
python run_agent.py
```

Gate: ≥15 sessions, net ≥ 0 after ₹42/trade, zero trailing micro-exits. See [FINDINGS_AND_NEXT_STEPS.md](FINDINGS_AND_NEXT_STEPS.md) §P3.
