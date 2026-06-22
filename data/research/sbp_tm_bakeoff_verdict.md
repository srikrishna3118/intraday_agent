# SBP Trend & Momentum — Bake-off Verdict

**Date:** Jun 2026  
**Window:** 180d T2 portfolio sim (30 symbols, cache, ~₹42/trade)  
**Engine:** `tools/strategy_bakeoff.py` with `--skip-rolling`  
**Artifact:** `data/research/sbp_tm_bakeoff.json`

---

## Candidates

| Key | Strategy | Notes |
|-----|----------|-------|
| `rsi_mr_baseline` | `rsi_mr` | Empty overrides (current tuned short-only `.env` profile) |
| `rsi_mr_paper_stack` | `rsi_mr` | Pivot proximity + RSI>80 + hour<14 + denylist + ATR target 3.5 |
| `sbp_tm_short` | `sbp_tm` | Short-only; Pine ATR(21) trail exit; agent trailing/ATR exits off |

---

## Results

| Candidate | Trades | Gross ₹ | Costs ₹ | Net ₹ | Sharpe | Win% |
|-----------|--------|---------|---------|-------|--------|------|
| **rsi_mr_baseline** | 23 | +1,007 | 966 | **+41** | 0.10 | 52% |
| **rsi_mr_paper_stack** | 23 | +1,007 | 966 | **+41** | 0.10 | 52% |
| **sbp_tm_short** | 484 | −1,035 | 20,328 | **−21,363** | −8.43 | 21% |

**Cost ratio (SBP):** costs ≈ **20× gross loss** — classic over-trading failure (same pattern as `vst_ai`, `zp_dmi`).

---

## Gates

| Gate | Primary control | SBP |
|------|-----------------|-----|
| Net > `rsi_mr_paper_stack` (+₹41) | PASS (control) | **FAIL** (−₹21,363) |
| Trades ≤ 2× paper stack (≤46) | PASS (23) | **FAIL** (484 ≈ 21×) |
| Sharpe > legacy baseline (−2.655) | PASS | **FAIL** (−8.43) |

**Decision: FAIL — shelve `sbp_tm` for paper/live.** Do not change paper `.env`.

---

## Implementation notes

### Entry (precompute)

- `precompute_sbp_signals()` → `sbp_long`, `sbp_short`, `sbp_momentum_score`
- Pine INTRADAY defaults: `baseLen=21`, `gapBars=6`, DTF EMA(EMA(25),2), adaptive WMA trend, momentum ≥70, sideways filter
- State loop: `signalDirection` + `gapOk` only — **no** precomputed `activeTrade`

### Exit (position-anchored)

- Pine ATR(21) trail in `SbpTmStrategy.update_trail_extreme()` + `exit_reason()`
- `exit_signal()` → always False (no RSI mid-line conflict)
- Bake-off: `TRAILING_STOP_ENABLED=false`, `USE_ATR_EXITS=false`, `SBP_USE_TRAIL_EXIT=true`

### Stock selection (unchanged)

Nifty 50 → screener `analyze()` → oversold/overbought lists → **AdaptiveRanker** (RSI extremity) → guards → order.

**Known limitation:** When multiple symbols fire SBP on the same bar, ranker still scores by `rsi - RSI_OVERBOUGHT`. SBP momentum score is logged in `sbp_momentum_score` but **not** used for ranking in v1. This can arbitrarily pick among trend signals; a future v2 could rank by momentum score on `ScreenResult`.

---

## Config (research placeholders)

Added to `config.py` / `.env.example` only — **not** in paper `.env`:

```
SBP_TRADE_MODE=INTRADAY
SBP_TRAIL_ATR_MULT=1.0
SBP_USE_TRAIL_EXIT=true
SBP_MOMENTUM_MIN=70
```

---

## Next steps

- **No paper promotion.** Continue Monday paper trial on `rsi_mr` + pivot stack.
- Optional v2 (only if revisiting): pivot confluence on SBP, momentum-based ranker, `gapBars` sweep, SCALPING mode — none justified until raw entry count drops.
