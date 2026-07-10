# Nifty 250 Research — Rerun Report

**Last updated:** 2026-07-10 (pass 3)  
**Universe:** Nifty 50 + Next 50 + Midcap 150 (~260 symbols)  
**Cache:** **76/260** symbols sim-loadable (Angel prefetch; ~184 still missing)  
**Window:** 180d portfolio sim | **Friction:** ₹42/trade

> **T2 baseline (30 symbols):** Sprint 4 mean exit **+₹347** / 17 trades.  
> **T250 pass 3 (76 symbols):** Sprint 4 mean exit **+₹49** / 54 trades; Sprint 5 base **+₹319**; best variant **p5_vwap_fade +₹744**.

---

## Prefetch status (3 passes)

| Pass | Sim-loadable | Notes |
|------|--------------|-------|
| 1 | 51 | Bulk rate-limit; 209 missing |
| 2 | 70 | `--only-missing --delay 2.5` |
| 3 | **76** | `--only-missing --delay 3.0` |

**Blocker:** ~184 symbols still have no Angel 15m parquet (mostly Nifty Next 50). Commands:

```bash
python tools/fetch_history.py --bundle t250_180d --only-missing --delay 3.0
python tools/candle_cache_status.py --bundle t250_180d --min-bars 500
```

---

## Sprint 4 — 76 symbols (2026-07-10)

| Variant | Trades | Net ₹ | Sharpe |
|---------|--------|-------|--------|
| p4_control | 57 | −896 | −0.933 |
| **p4_mean_rsi** | 54 | **+49** | 0.053 |
| p4_mean_rsi_slip | 55 | −130 | slip **−858** |
| p4_no_denylist | 60 | +130 | 0.143 |

**Gates:** Beat control PASS | Trades≥15 PASS | Slippage **FAIL** | Overall **FAIL**

**Exit leak:** ATR stops **−₹3,095** on 17 trades (dominant loss).

**Artifact:** `PHASE4_FINDINGS_T250.md`

---

## Sprint 5 — 76 symbols

| Variant | Trades | Net ₹ | Sharpe |
|---------|--------|-------|--------|
| p5_base | 51 | **+319** | 0.343 |
| **p5_vwap_fade** | 48 | **+744** | 0.845 |
| p5_vol_surge | 51 | +427 | 0.462 |
| p5_no_denylist | 57 | +544 | 0.620 |
| p5_nifty250 | 56 | **+728** | 0.849 |

**Gates:** Sample≥150 **FAIL** | Slippage gate logic **FAIL** (base slip +₹611 on 50 trades in bake-off)

**Artifact:** `PHASE5_FINDINGS_T250.md`

---

## Quadapt bake-off — 76 symbols

| Candidate | Trades | Net ₹ | Sharpe |
|-----------|--------|-------|--------|
| **rsi_mr_paper_stack** | 50 | **+611** | 0.674 |
| quadapt_ml_consensus | 29 | −1,811 | −2.984 |
| quadapt_ml_short | 7 | −984 | −1.925 |

**rsi_mr paper stack:** bake-off tool **PASS** on this window (vs legacy T2 baseline gates).  
**Quadapt:** **FAIL** — do not promote.

**Artifact:** `quadapt_ml_bakeoff_verdict_t250.md`

---

## Interpretation

1. **Wider universe adds trades (50–60)** but **ATR stop leak scales** — still the #1 fix.
2. **Mean exit still beats control** (+₹49 vs −₹896) on 76 names — directionally consistent with T2.
3. **VWAP fade gate helps on t250** (+₹744 vs base +₹319) — worth ablation on full cache when available.
4. **Verdict provisional** — 76/260 is **29% coverage**; full Nifty 250 sim may differ.

---

## Re-run when cache ≥200 symbols

```bash
python tools/rerun_nifty250_research.py --skip-prefetch --min-cached 200
```
