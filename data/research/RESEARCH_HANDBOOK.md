# Research Handbook — Intraday RSI Mean-Reversion (India)

**Generated:** 2026-07-05  
**Sim window:** 180d T2 portfolio (30 symbols, Angel parquet cache)  
**Final paper stack:** `rsi_mr` Sprint 4 mean-exit (config A below)  
**Live trading:** OFF (`LIVE_TRADING=false`)

> Master research document. Operations: [USER_GUIDE.md](../../USER_GUIDE.md). Code map: [AGENTS.md](../../AGENTS.md). Living implementation ledger: [IMPLEMENTATIONS_AND_NEXT_RESEARCH.md](IMPLEMENTATIONS_AND_NEXT_RESEARCH.md).

---

## 1. Executive summary

**Does rsi_mr have net edge on 15m MIS?**  
**Tentatively yes on a heavily filtered stack, but not statistically proven.** Sprint 4 mean-exit configuration yields **+₹347 net on 17 trades** (Sharpe 1.024) on 180d T2 — ~₹20/trade after ₹42 friction. Sample size is far below the 150-trade gate. Gross edge exists; unfiltered baseline remains **−₹5,290 / 146 trades**.

**What ships in paper?** Config A: short-only rsi_mr, RSI>80, entry before 14:00 IST, pivot proximity, symbol denylist, ATR stop 1.5×, **RSI 50 mean exit** (no ATR target, trailing off).

**What failed?** Nine prior entry strategies (rsi_div, zp_dmi, vst_ai, sbp_tm, vwap_mr, open_fade, rs_mr, orb, quadapt_ml). Root cause: **friction + over-trading + ATR stop leak**, not missing alpha in screening.

**Quadapt:** Ported (`quadapt_ml`) but **bake-off FAIL** (−₹372, 8 trades). Research archive only.

**5m candles:** **DEFERRED.** Stay on 15m; expand universe (Nifty 100) for sample size instead.

**REGIME_ADAPTIVE:** **OFF.** ORB regime switch loses −₹42k on 180d T2.

---

## 2. Research methodology

| Element | Setting |
|---------|---------|
| Engine | Portfolio sim: `MAX_POSITIONS`, `TradeGuard`, `AdaptiveRanker`, regime VIX gate |
| Universe | T2 bundle — 30 liquid Nifty names (`research/bundles/t2_180d.json`) |
| Data | `RESEARCH_DATA_SOURCE=cache` → `data/candles/*_FIFTEEN_MINUTE.parquet` |
| Friction | Flat **₹42/trade** (`ESTIMATED_COST_PER_TRADE`) |
| Slippage stress | +0.05% per leg (Sprint 4 `*_slip` variants) |
| Gates | Min trades, Sharpe, beat control, slippage survival, denylist falsification |
| Walk-forward | `tools/walk_forward.py`; rolling OOS in `strategy_bakeoff.py` |

**Reproduce cache:**

```bash
python tools/fetch_history.py --bundle t2_180d --source angel
python tools/candle_cache_status.py --bundle t2_180d
```

---

## 3. The core problem

| Bucket | Baseline rsi_mr (180d T2) | Filtered + mean exit (Sprint 4) |
|--------|---------------------------|----------------------------------|
| Gross | ~+₹1,000–1,300 | +₹1,061 |
| Costs (₹42×N) | Dominates | ₹714 (17 trades) |
| ATR stops | ~−₹9k gross leak | −₹382 (2 trades) |
| **Net** | **−₹5,290** | **+₹347** |

**Design rule:** Tune **filters + exits** on rsi_mr; do not swap entry strategy until net-positive on ≥150 trades.

---

## 4. Strategy scorecard

| Key | Role | 180d T2 net | Trades | Verdict |
|-----|------|-------------|--------|---------|
| `rsi_mr` (unfiltered) | Control | −₹5,290 | 146 | FAIL |
| `rsi_mr_paper_stack` | Production candidate | **+₹347** | 17 | **TENTATIVE PASS** |
| `orb` | Regime adaptive target | −₹42k | many | FAIL / blocked |
| `vwap_mr` | VWAP fade entries | negative | — | FAIL |
| `open_fade` | Gap exhaustion | negative | — | FAIL |
| `rs_mr` | RS pullback long | negative | — | FAIL |
| `rsi_div` | Pine divergence | negative | — | FAIL |
| `zp_dmi` | DMI confluence | −₹5,841 | 141 | FAIL |
| `vst_ai` | Volume SuperTrend AI | −₹12k | 258 | FAIL |
| `sbp_tm` | SBP trend+momentum | −₹21k | 484 | FAIL |
| `quadapt_ml` | MLMA + order blocks | −₹372 | 8 | FAIL (archive) |
| `vwap_pullback` | Trend pullback | research | — | not promoted |

---

## 5. Winning stack (paper `.env`)

```env
STRATEGY=rsi_mr
ALLOW_SHORT=true
ALLOW_LONG=false
RSI_OVERBOUGHT=80
ENTRY_CUTOFF_TIME=14:00
EXCLUDED_SYMBOLS=ONGC,SBIN,BAJFINANCE
PIVOT_FILTER_ENABLED=true
PIVOT_FILTER_MODE=proximity
PIVOT_TOUCH_PCT=0.35
ATR_STOP_MULT=1.5
ATR_TARGET_MULT=50
USE_ATR_EXITS=true
TRAILING_STOP_ENABLED=false
RSI_EXIT=50
VWAP_FILTER_ENABLED=false
VWAP_EXIT_ENABLED=false
CANDLE_INTERVAL=FIFTEEN_MINUTE
CANDLE_LOOKBACK=100
LIVE_TRADING=false
REGIME_ADAPTIVE=false
```

| Knob | Rationale |
|------|-----------|
| RSI>80 | Extreme only; cuts marginal fades |
| hour<14 | Worst hour bucket after 14:00 IST |
| Denylist | ONGC, SBIN, BAJFINANCE chronic losers |
| Pivot proximity | Fade at prior-session S/R |
| ATR stop 1.5× | Risk cap; still −₹382 on 2 stops in Sprint 4 |
| RSI 50 exit | Mean-reversion anchor; beats ATR target 3.5 (+₹63 control) |
| Trailing off | Trailing stops hurt control (−₹248 bucket) |

---

## 6. What we tried and rejected

| Experiment | Result | Why rejected |
|------------|--------|--------------|
| ATR target 3.5 + trailing | +₹63 net | Mean exit +₹347 |
| VWAP breakdown exit | −₹753 | Worse than RSI 50 |
| VWAP extension entry gate (Sprint 5) | +₹142 | Cuts edge vs base |
| Volume surge block (>200% 10d) | +₹347 | No change on T2 window |
| No denylist | +₹8 / 22 trades | Selection bias falsified — small effect |
| Nifty 100 universe | +₹32 / 24 trades | Sample still <150 |
| Quadapt consensus 15m | −₹372 / 8 | FAIL bake-off |
| REGIME_ADAPTIVE → ORB | −₹42k sim | Hard guardrail: keep false |
| Meta-label / new ML entries | — | Deferred until rsi_mr net-positive |

---

## 7. Architecture research applied

From [INTRADAY_TRADING_ARCHITECTURE_INDIA.md](INTRADAY_TRADING_ARCHITECTURE_INDIA.md):

| Item | Status |
|------|--------|
| VWAP MR fade gate (`VWAP_MR_FADE_SHORT`) | Implemented; marginal sim benefit |
| VWAP touch exit | Rejected (Sprint 4/5) |
| Volume surge block | Implemented |
| Upper circuit proximity guard | Implemented (`CIRCUIT_GUARD_*`) |
| Nifty 100 scan (`SCAN_UNIVERSE`) | Implemented |
| RISK_PCT sizing | Implemented; **0 until backtested** |
| REGIME_ADAPTIVE | Implemented; **must stay false** |
| Telegram alerts | Stub (`alerts.py`); env-gated |
| SmartStream WebSocket | Stub (`broker.connect_stream`); REST default |
| CPR / paid data | Deferred |

---

## 8. Timeframe decision

**15m is default.** All 180d artifacts use `FIFTEEN_MINUTE`. Five-minute bars triple signal frequency and worsen over-trading (ORB, vst_ai, sbp_tm). Fixed ₹42/trade friction punishes volume.

**5m:** **DEFERRED** unless Sprint 5 stalls on sample size after Nifty 100. Would require new parquet cache, `CANDLE_LOOKBACK=300`, rescaled RSI/ATR, gate net/trade ≥ 15m baseline.

**Quadapt on 15m:** Pine 60m defaults (`LEN1=120`, `WINDOW=200`) produce zero signals with `CANDLE_LOOKBACK=100`. Use 15m bundle: LEN1=30, WINDOW=60, LOOKBACK=120.

---

## 9. Paper vs sim validation

| Metric | Sim (Sprint 4) | Paper (as of 2026-07-05) |
|--------|----------------|--------------------------|
| Sessions | 180d backtest | 1 day (2026-06-22) |
| Entries | 17 | 0 (power cut; old stack) |
| Net | +₹347 | ₹0 |

**Next:** Resume 5–10 sessions per [paper_trial_log.md](paper_trial_log.md). Promotion if paper ≥ ~₹16/trade (20% below sim).

---

## 10. Adversarial lessons

1. **Friction dominates** — ₹42×trades erases gross MR edge on unfiltered stacks.
2. **Over-trading kills** — sbp_tm (484 trades), vst_ai (258) are cautionary.
3. **Denylist bias is small** — removing denylist: +₹8 vs +₹347 (22 vs 17 trades).
4. **Sample size matters** — 17 trades is not significance; target ≥150 via Nifty 100 + time.
5. **Mean exit > ATR target on MR** — RSI 50 captures reversion; wide ATR targets rarely hit.
6. **Do not enable REGIME_ADAPTIVE** until ORB passes bake-off.
7. **Infrastructure ≠ alpha** — WebSocket/Telegram only after net-positive robustness.

---

## 11. Reproduce commands

```bash
# Sprint 4 — exit ablation
python tools/research_phases.py --phase 4 --days 180 --source cache

# Sprint 5 — VWAP, volume, Nifty 100
python tools/research_phases.py --phase 5 --days 180 --source cache

# Quadapt vs paper stack
python tools/strategy_bakeoff.py --tier t2 --days 180 --source cache \
  --candidates rsi_mr_paper_stack,quadapt_ml_consensus,quadapt_ml_short --skip-rolling \
  --output data/research/quadapt_bakeoff.json \
  --verdict-path data/research/quadapt_ml_bakeoff_verdict.md

# Filter ablations
python tools/filter_backtests.py

# Paper smoke test
python run_agent.py --once
python tools/status.py
```

---

## 12. Artifact index

| File | Description |
|------|-------------|
| `PHASE4_FINDINGS.md` | Sprint 4 mean-exit ablation |
| `phase4_findings.json` | Sprint 4 machine-readable results |
| `PHASE5_FINDINGS.md` | Sprint 5 robustness variants |
| `phase5_findings.json` | Sprint 5 JSON |
| `quadapt_ml_bakeoff_verdict.md` | Quadapt FAIL verdict |
| `quadapt_bakeoff.json` | Quadapt bake-off numbers |
| `strategy_bakeoff_verdict.md` | Full strategy registry bake-off |
| `paper_trial_log.md` | Live paper session log |
| `IMPLEMENTATIONS_AND_NEXT_RESEARCH.md` | Implementation ledger |
| `INTRADAY_TRADING_ARCHITECTURE_INDIA.md` | India intraday architecture checklist |
| `GEMINI_CRITIQUE_AND_SPRINT4.md` | Sprint 4 rationale |
| `filter_backtests.md` | Pivot/time/RSI ablations |
| `rsi_mr_verdict.md` | Phase B portfolio FAIL |
| `loss_decomposition.md` | Exit bucket P&L |

---

## Appendix A — Config snapshots

### A — rsi_mr paper stack (production candidate)

See §5 above.

### B — Quadapt research bundle (not paper)

```env
STRATEGY=quadapt_ml
CANDLE_INTERVAL=FIFTEEN_MINUTE
CANDLE_LOOKBACK=120
QUADAPT_LEN1=30
QUADAPT_LEN2=14
QUADAPT_WINDOW=60
QUADAPT_MIN_QUALITY=55
QUADAPT_SIGNAL_MODE=consensus
ALLOW_SHORT=true
ALLOW_LONG=false
ENTRY_CUTOFF_TIME=14:00
LIVE_TRADING=false
```

### C — 5m (do not use)

Deferred. See §8.

---

## Appendix B — Quadapt Pine → Python port

| Pine "How To Use" | Ported? | Notes |
|-------------------|---------|-------|
| MLMA cloud + trend | Yes | Quality engine 38% weight |
| Labels need trend + OB + quality | Yes | `QUADAPT_MIN_QUALITY` + no-trade regime |
| Order blocks | Partial | Levels scored; retest not hard gate |
| TP/SL projections | No | Agent uses ATR + MLMA flip |
| Tune LEN / Signal Mode / Quality | Yes | 15m rescale required |
| Paper first | Yes | Bake-off FAIL — do not promote |

---

## Appendix C — Sprint timeline

| Date | Sprint | Key numbers | Decision |
|------|--------|-------------|----------|
| 2026 Q1 | Phase B | −₹5,290 / 146 trades | Stop unfiltered entry research |
| 2026-06 | Filter ablation | Test 9: −₹133 → pivot stack tuning | Pivot + denylist |
| 2026-07-05 | Sprint 4 | Mean exit +₹347 vs control +₹63 | **PASS** — adopt mean exit |
| 2026-07-05 | Sprint 5 | Base +₹347; Nifty100 +₹32/24 | PASS friction; FAIL n≥150 |
| 2026-07-05 | Quadapt bake-off | −₹372 / 8 trades | **FAIL** — archive |
| 2026-06-22 | Paper day 1 | 0 entries | Resume pending |
