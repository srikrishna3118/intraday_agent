# Research Implementations & Next Steps

**Project:** Auto_trading intraday agent (Angel One, 15m, MIS, paper default)  
**Window:** 180d T2 portfolio sim (30 symbols, ~₹42/trade costs) unless noted  
**Last updated:** Jun 2026

---

## 1. Executive summary

| Finding | Detail |
|---------|--------|
| **Gross edge exists** | rsi_mr baseline gross ≈ +₹1,000–1,300 on 180d T2 |
| **Costs + ATR stops dominate net** | ~₹42/trade × N trades; ATR stop bucket ≈ −₹9,342 gross on 49 trades (baseline decomposition) |
| **No replacement entry strategy passed bake-off** | rsi_div, zp_dmi, vst_ai, **sbp_tm**, vwap_mr, open_fade, rs_mr all **FAIL** vs rsi_mr |
| **Best filter stack so far** | **RSI>80 + hour<14 + pivot proximity** → net **−₹133**, 22 trades, Sharpe **−0.31** (still slightly negative) |
| **Paper Tier 1 (live `.env.example`)** | RSI>80, ENTRY_CUTOFF 14:00, EXCLUDED_SYMBOLS=ONGC,SBIN,BAJFINANCE — **pivot filter not yet enabled in paper** |

**Research direction:** Stop adding new entry tracks. Combine proven **rsi_mr filters + exit tuning** before any paper promotion of pivot stack.

---

## 2. Strategy implementations (`STRATEGY_REGISTRY`)

| Key | Class | Role | Status |
|-----|-------|------|--------|
| `rsi_mr` | `RsiVolumeMeanReversionStrategy` | RSI extreme + volume; short-only paper default | **Production / research control** |
| `orb` | `OpeningRangeBreakoutStrategy` | OR break + VWAP | Research only |
| `vwap_pullback` | `VwapPullbackStrategy` | Trend pullback to VWAP | Research only |
| `vwap_mr` | `VwapMeanReversionStrategy` | Fade distance from VWAP | Bake-off FAIL |
| `open_fade` | `OpeningDriveFadeStrategy` | Gap-up exhaustion short | Bake-off FAIL |
| `rs_mr` | `RelativeStrengthPullbackStrategy` | RSI(2) pullback long | Bake-off FAIL |
| `rsi_div` | `RsiDivergenceStrategy` | Pine RSI divergence port | Bake-off FAIL |
| `zp_dmi` | `ZpDmiConfluenceStrategy` | ZPayab DMI + multi-confirm | Bake-off FAIL |
| `vst_ai` | `VstAiStrategy` | Zeiierman Volume SuperTrend AI + KNN | Bake-off FAIL |
| `sbp_tm` | `SbpTmStrategy` | SBP Trend & Momentum + Pine ATR trail | Bake-off FAIL (484 trades, −₹21k net) |

**Shared infrastructure:** `BaseStrategy.precompute_df()`, portfolio sim EOD IST fix, `AdaptiveRanker`, regime (VIX), guards, journal features.

### 2.1 SBP Trend & Momentum (`sbp_tm`) — Jun 2026 port

**Code:** `precompute_sbp_signals()`, `SbpTmStrategy` (entry precompute + entry-anchored Pine ATR(21) trail exit).

**Config (research only):** `SBP_TRADE_MODE`, `SBP_TRAIL_ATR_MULT`, `SBP_USE_TRAIL_EXIT`, `SBP_MOMENTUM_MIN`

**180d T2 bake-off vs `rsi_mr_paper_stack`:** FAIL — 484 trades, net **−₹21,363**, Sharpe **−8.43** (costs dominate; over-trading). Primary gate control: paper stack +₹41, 23 trades.

**Ranker caveat:** SBP entries still ranked by RSI extremity; `sbp_momentum_score` not used in v1.

**Artifact:** `data/research/sbp_tm_bakeoff_verdict.md`, `sbp_tm_bakeoff.json`

---

## 3. Filter & overlay implementations (on rsi_mr or all strategies)

### 3.1 Classic pivot points (prior-session H/L/C)

**Code:** `classic_pivot_levels()`, `compute_session_pivot_points()`, `ScreenResult.pivot_*`, `BaseStrategy.pivot_allows_entry()`

| Level | Formula |
|-------|---------|
| PP | (H+L+C)/3 |
| S1 | 2×PP − H |
| R1 | 2×PP − L |
| S2/R2/S3/R3 | standard floor pivots |

**Config:** `PIVOT_FILTER_ENABLED`, `PIVOT_FILTER_MODE` (`zone` \| `proximity` \| `both`), `PIVOT_TOUCH_PCT`

**Profiles:**
- **MR** (rsi_mr, vwap_mr, …): fade at S/R proximity or zone
- **Trend** (orb, vwap_pullback, zp_dmi, vst_ai): long above PP, short below PP

**180d filter ablation (rsi_mr):**

| Test | Trades | Net ₹ | Sharpe |
|------|--------|-------|--------|
| Baseline | 98 | −3,122 | −2.63 |
| Pivot proximity only | 64 | −1,597 | −1.79 |
| **Hour<14 + RSI>80 + pivot proximity** | **22** | **−133** | **−0.31** |

Artifacts: `filter_backtests.md`, `filter_backtests_combined_pivot.md`

---

### 3.2 Time, RSI, symbol filters (research / paper Tier 1)

| Filter | Config / tool | 180d effect |
|--------|---------------|-------------|
| Hour < 14 IST | `ENTRY_CUTOFF_TIME=14:00` | Cuts 14:00 bucket (−₹1,905 worst hour) |
| RSI > 80 | `RSI_OVERBOUGHT=80` | 43 trades, net −₹724 vs baseline −₹3,122 |
| Symbol denylist | `EXCLUDED_SYMBOLS=ONGC,SBIN,BAJFINANCE` | Removes chronic losers |
| Volume cap <1.5× | `SimEntryFilter` | **Not deployed** — poor per-trade quality in ablation |

**Paper Tier 1 in `.env.example`:** RSI>80, cutoff 14:00, denylist. Pivot **off**.

---

### 3.3 ZPayab supply/demand S/R (`zp_dmi` only)

**Code:** `compute_zp_sd_zone_flags()` — swing pivots (len 10) + ATR(50) box, overlap skip, zone break on close through top/bottom.

**Config:** `ZP_SD_FILTER_ENABLED`, `ZP_SD_FILTER_MODE` (`avoid` \| `at_zone`), `ZP_SD_SWING_LEN`, `ZP_SD_HISTORY`, `ZP_SD_BOX_WIDTH`, `ZP_SD_ATR_LEN`, `ZP_SD_TOUCH_PCT`

| Mode | Long | Short |
|------|------|-------|
| `avoid` (default) | Skip if in/at **supply** | Skip if in/at **demand** |
| `at_zone` | Require **demand** | Require **supply** |

**Bake-off:** zp_dmi 141 trades −₹5,841 → zp_dmi+SD 124 trades −₹5,091 (still FAIL vs rsi_mr). `at_zone` → **0 trades**.

Artifact: `zp_dmi_sd_bakeoff_verdict.md`

---

### 3.4 ZPayab DMI confluence (`zp_dmi`)

**Leading:** +DI/−DI + ADX ≥ 20  
**Confirm:** RQK slope, VWAP side, Chandelier dir, MACD cross, volume > SMA(20)  
**Logic:** signal expiry 3 bars, alternate signal

**Config:** `ZP_*` in `.env.example`

**180d bake-off:** 149–159 trades, net −₹6,302 to −₹6,788, Sharpe ≈ −8.1 to −8.5 → **FAIL**

---

### 3.5 RSI divergence (`rsi_div`)

Pine RSI divergence port; precompute `rsi_div` signals; optional ATR chandelier trail.

**180d bake-off:** ~119 trades, net ≈ −₹5,029, Sharpe ≈ −4.4 → **FAIL**

---

### 3.6 Volume SuperTrend AI (`vst_ai`)

Zeiierman port: volume-weighted SuperTrend + KNN classification; entries on trend start + direction flip.

**180d bake-off:** 258–268 trades, net −₹11,877 to −₹12,261, Sharpe ≈ −9.3 → **FAIL** (over-trading)

---

### 3.7 ADX band gate (rsi_mr variant)

**Config:** `ADX_MR_MIN`, `ADX_MR_MAX`  
Tested bands 10–15, 12–18, 15–20 + regime — no bake-off pass documented as beating baseline net.

Artifact: `rsi_mr_adx_band_verdict.md`

---

## 4. Exit & risk implementations

| Mechanism | Config | Research note |
|-----------|--------|---------------|
| ATR stop/target | `USE_ATR_EXITS`, `ATR_STOP_MULT=1.5`, `ATR_TARGET_MULT=3.0` | **Largest loss bucket:** ATR stop 49 trades, net −₹9,342 (decomposition) |
| ATR mult sweep | `tools/` + `atr_sensitivity.md` | Best net at **1.25** (−₹683) on RSI>80+hour+denylist stack — **not in paper .env** |
| Trailing stop | `TRAILING_STOP_ENABLED=true` | 56 trades, net −₹652 |
| RSI mid-line exit | `RSI_EXIT=50` | 22 trades, net **+₹2,230** |
| ATR target | — | 15 trades, net **+₹2,975** |
| VST flip exit | `VST_EXIT_ON_FLIP` | vst_ai only |
| EOD square-off | `SQUARE_OFF_TIME=15:15` | IST session fix applied in backtest |

---

## 5. Research tooling

| Tool | Purpose |
|------|---------|
| `tools/strategy_bakeoff.py` | Compare strategies vs rsi_mr baseline (gates: net, Sharpe, min trades, rolling OOS) |
| `tools/filter_backtests.py` | Sequential filter ablation on rsi_mr (Tests 1–9 incl. pivot combo) |
| `tools/research_validation.py` | Portfolio-realistic sim + meta-label path |
| `tools/bootstrap_backtest.py` / `walk_forward.py` | Symbol-level backtest / WF |
| Loss / exit forensics | `loss_decomposition.md`, `atr_stop_postmortem.md`, `rsi_threshold_sweep.md`, `atr_sensitivity.md` |

**Artifacts directory:** `data/research/*.md`, `*.json`

---

## 6. Bake-off scorecard (180d T2, selected)

| Candidate | Trades | Net ₹ | Sharpe | Verdict |
|-----------|--------|-------|--------|---------|
| rsi_mr baseline | 93–110 | −2,620 to −3,387 | −2.3 to −2.8 | Control |
| **rsi_mr + filters Test 9** | **22** | **−133** | **−0.31** | Best filter combo; not full paper stack |
| rsi_mr RSI>80 only | 43 | −724 | −0.90 | Strong single filter |
| rsi_mr pivot proximity | 64 | −1,597 | −1.79 | Good trade reduction |
| rsi_mr RSI>84 + stack (partial) | 13 | −299 | −0.57 | Few trades; threshold sweep |
| rsi_div | 119 | −5,029 | −4.4 | FAIL |
| zp_dmi | 141–159 | −5,841 to −6,788 | −7.2 to −8.5 | FAIL |
| zp_dmi + S/D avoid | 124 | −5,091 | −7.2 | FAIL (marginal vs zp_dmi) |
| vst_ai | 258–268 | −11,877 to −12,261 | −9.3 | FAIL |

*Exact baseline trade count varies slightly by run/config snapshot; compare within same JSON artifact.*

---

## 7. What we learned (design rules)

1. **Do not swap entry strategy** — tune rsi_mr + filters + exits.
2. **Gross is positive; friction is the enemy** — every filter that cuts low-quality trades helps.
3. **RSI>80 alone** removes most of the RSI 75–80 drag (−₹4,552 on 96 trades).
4. **14:00+ entries** are toxic (−₹1,905 on 20 trades).
5. **Pivot proximity** adds confluence for shorts fading near R1/PP (MR profile).
6. **Trend stacks** (zp_dmi, vst_ai) over-trade on 15m MIS; S/R `at_zone` conflicts with trend entries.
7. **ATR stops** need tuning (1.25 > 1.5 on filtered stack) or fewer entries that trigger them.
8. **Winners to preserve:** ATR target, RSI mid-line exit paths.
9. **External MR framework:** single-asset fade + **exit at the mean** (RSI 50 / VWAP / band trail), not isolated hero strategy — see `MEAN_REVERSION_REFERENCE.md` (Sandeep Rao / Long & Short Ep. 17 summary).

---

## 8. Next research — prioritized combinations

### Tier A — Highest priority (rsi_mr only, likely to move net toward breakeven)

| # | Combination | Rationale | Command sketch |
|---|-------------|-----------|----------------|
| **A1** | **Test 9 + denylist** (RSI>80, hour<14, pivot proximity, EXCLUDED_SYMBOLS) | Test 9 never run with symbol exclusions together; denylist already in paper | Extend `filter_backtests.py` test10 + run 180d |
| **A2** | **A1 + ATR_STOP_MULT=1.25** | Best exit sweep on filtered stack (−₹683 vs −₹798 at 1.5) | Config override in sim |
| **A3** | **A1 + RSI>84** | Threshold sweep: 13 trades, −₹299 (trade count risk) | Sweep 82/84/85 on full Test 9 stack |
| **A4** | **Paper promote pivot** | After A1–A2 sim pass: enable `PIVOT_FILTER_ENABLED=true` in paper only | Manual `.env` + `--once` paper sessions |

### Tier B — Exit-first (same entries, fix the −₹9k ATR stop leak)

| # | Combination | Rationale |
|---|-------------|-----------|
| **B1** | Filtered stack + **ATR stop 1.25 + target 3.0** | Already partially tested; combine with Test 9 |
| **B2** | Filtered stack + **disable ATR stop, RSI-only exit** for RSI>85 entries | Extreme RSI may mean-revert without wide stop |
| **B3** | Filtered stack + **time stop** (e.g. exit if no target in 90m) | Post-mortem: stops spread >20m; cull slow losers |
| **B4** | **Ranker / MAX_TRADES** tighten on Test 9 stack | 22 trades → fewer, higher-conviction picks |

### Tier C — Confluence experiments (only if Tier A stalls)

| # | Combination | Rationale | Risk |
|---|-------------|-----------|------|
| **C1** | Test 9 + **ZP S/D avoid on rsi_mr** (not zp_dmi) | Two S/R layers: pivots + swing zones | Double filter → too few trades |
| **C2** | Test 9 + **REGIME VIX<18** | Already in config; measure incremental | May shrink sample |
| **C3** | Test 9 + **meta-label** (`research_validation.py --meta-label`) | ML gate on journal features | Needs labels; may overfit |
| **C4** | **Symbol whitelist** (MARUTI, M&M, NTPC only) | Edge pockets from decomposition | Overfit / capacity loss |

### Tier E — Sprint 5 (post Sprint 4, Gemini Round 2 + VWAP research)

| # | Work | Rationale |
|---|------|-----------|
| **E1** | Nifty 100 liquid universe, **no denylist** | Falsify curve-fit; target ≥150 trades / 180d |
| **E2** | VWAP MR entry: short only when **above VWAP** + min extension | Institutional gravity; fix inverted `vwap_allows_entry` SHORT logic for fade-from-above |
| **E3** | VWAP touch as primary exit (ATR target off) | Structural mean per Round 2 + video reference |
| **E4** | Volume surge block (e.g. vol >200% 10d avg) | Skip breakout days when RSI>80 = strength |
| **E5** | Test 9 + `REGIME_FILTER` (VIX + Nifty EMA) | Dynamic regime vs static pivot only |

Command sketch (after implementation): `python tools/research_phases.py --phase 5`

---

### Tier D — Deprioritize (documented FAIL)

- New leading indicators: vst_ai, zp_dmi, rsi_div as primary entry
- zp_dmi + S/D `at_zone` (0 trades)
- Volume cap <1.5× (quality degradation)
- vwap_mr / open_fade / rs_mr as rsi_mr replacement

---

## 9. Recommended next sprint (2–3 runs)

**Executed (Jun 2026):** Phase 1–3 → `PHASE_FINDINGS.md` (+₹45 sim, paper trial).

**Scheduled Sprint 4 (post paper session, after 15:30 IST):**

```bash
python tools/research_phases.py --phase 4
```

See **`GEMINI_CRITIQUE_AND_SPRINT4.md`** for external critique + repo analysis. Outputs: `PHASE4_FINDINGS.md`, `phase4_findings.json`.

**Theoretical anchor:** `MEAN_REVERSION_REFERENCE.md` (MR taxonomy, video BB-trail vs our ATR-target paper stack, Sprint 4 mean-exit rationale).

| Variant | Purpose |
|---------|---------|
| `p4_control` | Reproduce Phase 2 winner (target 3.5) |
| `p4_mean_rsi` | Test 9 + RSI 50 exit, no ATR target / trailing |
| `p4_mean_rsi_vwap` | + VWAP breakdown exit |
| `p4_mean_rsi_slip` / `p4_control_slip` | 0.05% slippage per leg stress |
| `p4_no_denylist` | Falsify symbol exclusion bias |

**Deferred:** time stop (N bars), top-100 universe expansion.

**After Sprint 4 (Gemini Round 2):** Sprint 5 — VWAP entry extension gate, volume-surge block, Nifty 100 unfalsified test, ≥150-trade gate. See `GEMINI_CRITIQUE_AND_SPRINT4.md` §6.

Legacy sketch (pre-Sprint 4):

```
Run 1: filter_backtests — test10 = Test9 + denylist (+ optional ATR 1.25)
Run 2: rsi_threshold_sweep on Test9 stack (80/82/84/85)
Run 3: exit ablation on best stack from Run 1 (ATR mult, time stop, RSI-only exit)
Gate:  net > −₹133 AND Sharpe > −0.31 AND trades ≥ 15 → paper pivot enable
```

---

## 10. Paper vs research config snapshot

**Current paper (`.env.example`, pivot off):**
```
STRATEGY=rsi_mr
ALLOW_SHORT=true
ALLOW_LONG=false
RSI_OVERBOUGHT=80
ENTRY_CUTOFF_TIME=14:00
EXCLUDED_SYMBOLS=ONGC,SBIN,BAJFINANCE
PIVOT_FILTER_ENABLED=false
ATR_STOP_MULT=1.5
LIVE_TRADING=false
```

**Best sim stack (research only, not paper):**
```
PIVOT_FILTER_ENABLED=true
PIVOT_FILTER_MODE=proximity
PIVOT_TOUCH_PCT=0.35
(+ RSI>80, hour<14, denylist)
```

---

## 11. File index

| Topic | Path |
|-------|------|
| **Phase 1–3 sprint (Jun 2026)** | **`data/research/PHASE_FINDINGS.md`**, `phase_findings.json` |
| **Gemini critique + Sprint 4 plan** | **`data/research/GEMINI_CRITIQUE_AND_SPRINT4.md`** (Round 1 + **Round 2** §6) |
| **Mean reversion reference (video summary)** | **`data/research/MEAN_REVERSION_REFERENCE.md`** — Sandeep Rao MR taxonomy + mapping to rsi_mr / Sprint 4 |
| **Sprint 4 (pending run)** | **`data/research/PHASE4_FINDINGS.md`**, `phase4_findings.json` — `python tools/research_phases.py --phase 4` |
| Loss decomposition | `data/research/loss_decomposition.md` |
| Filter ablation | `data/research/filter_backtests.md`, `filter_backtests_combined_pivot.md` |
| Strategy bake-offs | `data/research/strategy_bakeoff_verdict.md`, `rsi_div_*`, `zp_dmi_*`, `vst_ai_*`, `zp_dmi_sd_*` |
| Exit forensics | `data/research/atr_stop_postmortem.md`, `atr_sensitivity.md`, `rsi_threshold_sweep.md` |
| Code entry point | `intraday_agent/strategy.py`, `config.py`, `.env.example` |

---

## 12. Phase sprint results (executed Jun 2026)

Full report: **`PHASE_FINDINGS.md`** | Tool: `python tools/research_phases.py`

| Phase | Result |
|-------|--------|
| **1 Entry** | Test 9 confirmed (−₹133, 22 trades). RSI>84 → +₹10 but only 6 trades. ATR 1.25 **worse** on pivot stack. |
| **2 Exit** | **PASS** — keep stop **1.5**, raise target to **3.5** → net **+₹45**, Sharpe **0.108**, 21 trades |
| **3 Paper** | Sim gate met → trial pivot in paper (not live). Run `--once` 5–10 sessions before defaulting. |

**Research winner:** pivot + RSI>80 + hour<14 + denylist + `ATR_TARGET_MULT=3.5`. Paper trial in progress.

**Sprint 4 (not yet run):** Mean-exit ablation + slippage stress — see `GEMINI_CRITIQUE_AND_SPRINT4.md`. Run after market close: `python tools/research_phases.py --phase 4`.
