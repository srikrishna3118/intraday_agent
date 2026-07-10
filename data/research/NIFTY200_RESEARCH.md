# Nifty 200 Research — Full Run (Jul 10, 2026)

Universe: **Nifty 100 + Midcap 100** (`SCAN_UNIVERSE=nifty200`, tier `t200`).

## Symbol fixes applied

| Old | New | Reason |
|-----|-----|--------|
| LTIM | **LTM** | LTIMindtree rebrand (Feb 2026) |
| ZOMATO | **ETERNAL** | Zomato rename |
| KALPATPOWR | **KALPATARU** | Kalpataru Power ticker |
| JUBILINDS | **JUBLPHARMA** | Jubilant Pharmova |
| GUJGASLTD | **GUJENERGY** | Gujarat Gas → Gujarat Energy (-BE series) |
| ISEC | **SWIGGY** | ICICI Securities delisted (Mar 2025) |

Also: instrument registry supports `GUJENERGY-BE`; prefetch waits on Angel rate-limit pause.

## Cache status

| Metric | Value |
|--------|-------|
| Bundle | `t200_180d` |
| Usable 180d | **200 / 200** |

## Sprint 4 — Mean exit ablation

**200 symbols** | 180d | cache

| Variant | Trades | Net ₹ | Sharpe |
|---------|--------|-------|--------|
| Control (ATR trail) | 136 | -4,003 | -2.56 |
| Mean RSI exit | 120 | -3,297 | -1.81 |
| Mean RSI + VWAP breakdown | 183 | -7,671 | -5.81 |
| No denylist | 119 | -2,719 | -1.57 |
| **Paper stack** | 120 | **-3,063** | -1.72 |

**Gates:** Beat control PASS | Trades ≥15 PASS | Slippage **FAIL** | Overall **FAIL**

Artifacts: `PHASE4_FINDINGS_T200.md`, `phase4_findings_t200.json`

## Sprint 5 — VWAP / volume / universe

| Variant | Trades | Net ₹ | Sharpe |
|---------|--------|-------|--------|
| Base (paper stack) | 120 | -3,063 | -1.72 |
| Volume surge block | 116 | -2,208 | -1.28 |
| No denylist | 105 | -1,420 | -0.78 |
| **Nifty 200 full** | 103 | **-1,208** | -0.66 |

**Gates:** Trades ≥15 PASS | Sample ≥150 **FAIL** | Slippage **FAIL**

Artifacts: `PHASE5_FINDINGS_T200.md`, `phase5_findings_t200.json`

## Strategy bake-off

| Candidate | Trades | Net ₹ | Sharpe | Verdict |
|-----------|--------|-------|--------|---------|
| **rsi_mr_paper_stack** | 102 | **-1,183** | -0.65 | **PASS** (vs baseline) |
| quadapt_ml_consensus | 105 | -6,135 | -5.42 | FAIL |
| quadapt_ml_short | 39 | -2,133 | -3.17 | FAIL |

Artifacts: `quadapt_ml_bakeoff_verdict_t200.md`, `quadapt_bakeoff_t200.json`

## Decision

- **200-symbol window is negative** on paper stack (−₹1,183); better than T2 baseline (−₹5,290) but not profitable.
- Mean RSI still beats control on net; slippage gate still fails.
- **Keep paper stack**; no Quadapt; no live promotion.
- Interim 80-symbol run (+₹451) was **selection bias** from partial cache — do not use those numbers.

## Rerun

```bash
python tools/fetch_history.py --bundle t200_180d --only-missing --delay 5.0
python tools/rerun_nifty200_research.py --skip-prefetch
```
