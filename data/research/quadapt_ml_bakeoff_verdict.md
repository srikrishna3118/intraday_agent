# Quadapt ML Bake-off Verdict

**Generated:** 2026-07-05  
**Window:** 180d T2 (30 symbols) | **Data:** cache | **Engine:** portfolio sim  
**Reference stack:** `rsi_mr_paper_stack` (Sprint 4 mean-exit winner)

## Plan pass criteria (all required)

| Gate | rsi_mr_paper_stack | quadapt_ml_consensus | quadapt_ml_short |
|------|-------------------|----------------------|------------------|
| Net ≥ paper stack (+₹347) | ✅ ₹347 | ❌ −₹372 | ❌ −₹126 |
| Trades ≤ 2× paper (≤44) | ✅ 17 | ✅ 8 | ✅ 2 |
| Sharpe > 0 | ✅ 1.024 | ❌ −3.254 | ❌ −2.721 |

## Results

| Candidate | Trades | Net ₹ | Sharpe | Verdict |
|-----------|--------|-------|--------|---------|
| **rsi_mr_paper_stack** | 17 | **+347** | 1.024 | **KEEP** (paper production) |
| quadapt_ml_consensus | 8 | −372 | −3.254 | **FAIL** |
| quadapt_ml_short | 2 | −126 | −2.721 | **FAIL** |

**Config (15m tuned):** `QUADAPT_LEN1=30`, `LEN2=14`, `WINDOW=60`, `MIN_QUALITY=55`, `SIGNAL_MODE=consensus`, `CANDLE_LOOKBACK=120`.

## Decision

**FAIL — archive for research only.** Quadapt does not beat the Sprint 4 rsi_mr paper stack on net or Sharpe. Do **not** promote to paper until a future bake-off passes all gates. One retry at `MIN_QUALITY=60` was not warranted (consensus mode already strict; 8 trades with negative expectancy).

**Adversarial note:** Matches prior ML-style over-trading failures (vst_ai −₹12k/258, sbp_tm −₹21k/484). Quality filter cut volume but not losses.

**Artifact:** `data/research/quadapt_bakeoff.json`
