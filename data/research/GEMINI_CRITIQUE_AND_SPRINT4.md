# External Critique (Gemini) + Repo Analysis — Sprint 4 Plan

**Date:** Jun 2026  
**Context:** Phase 1–3 sprint promoted pivot + `ATR_TARGET_MULT=3.5` to paper trial (+₹45 sim, 21 trades). Paper session starting; Sprint 4 scheduled **after market close (post 15:30 IST)** — not run before paper.

**Tool:** `python tools/research_phases.py --phase 4`  
**Outputs (when run):** `data/research/PHASE4_FINDINGS.md`, `phase4_findings.json`

---

## 1. Gemini feedback (summary)

| # | Claim | Recommendation |
|---|--------|----------------|
| **1** | 3.5 ATR target on rsi_mr is mechanically wrong for mean reversion; +₹45 may be fat-tail outliers | Drop fixed ATR target; exit at mean (RSI 50, VWAP, EMA) |
| **2** | 21 trades / 180d is statistically meaningless; filters + denylist = curve fitting | Broaden universe (100+ liquid names); remove denylist for falsification test |
| **3** | 14:00 entry vs 15:15 square-off leaves too little time for wide targets; stop still exposed | Time stop (4–6 bars); shrink targets near EOD |
| **4** | ₹42/trade omits slippage; RSI>80 entries often into thin books | Add ~0.05% slippage per leg |
| **5** | Prior research showed RSI mid-line exit +₹2,230 | Re-run Test 9 stack with mean exits, not target mult sweep |

---

## 2. Repo analysis — what holds, what doesn’t

### 2.1 R:R / ATR target (partially agree)

**Gemini:** +₹45 driven by 3.5 ATR outlier collapses.

**Our data (`PHASE_FINDINGS.md` exit breakdown on final stack):**

| Exit | Trades | Net ₹ |
|------|--------|-------|
| ATR target | **1** | +112 |
| RSI mid-line | 7 | +723 |
| ATR stop | 4 | −702 |
| Trailing stop | 8 | −200 |
| EOD square-off | 1 | +112 |

The +₹45 was **not** carried by multiple 3.5 ATR target hits. It came from a **mix** of mid-line reversion, one target, trailing/EOD/stops.

**Still valid:** forcing a wide ATR target on MR entries is conceptually odd; Phase 2 optimized target mult on a **21-trade sample** without a dedicated **mean-exit ablation on Test 9**. That gap is real. See also `MEAN_REVERSION_REFERENCE.md` (video: exit via mean-linked trail, not fixed distant target).

**Baseline decomposition (`loss_decomposition.md`, unfiltered 142 trades):**

| Exit family | Trades | Net ₹ |
|-------------|--------|-------|
| RSI mid-line | 22 | **+2,230** |
| ATR target | 15 | **+2,975** |
| ATR stop | 49 | **−9,342** |

Mean-reversion exits already look strong on gross paths; **ATR stops** are the main leak. Sprint 4 tests whether **Test 9 entries + mean exits** beat **Test 9 + target 3.5**.

### 2.2 Statistical insignificance (agree)

21 trades over 180d × 30 symbols ≈ one trade every 8.5 symbol-days. Sharpe 0.108 on that sample is **not** promotion-grade.

**Denylist bias:** `EXCLUDED_SYMBOLS=ONGC,SBIN,BAJFINANCE` removes symbols that lost in-window — classic in-sample selection unless validated walk-forward. Sprint 4 includes a **no-denylist** variant on the same T2 universe.

**Universe breadth:** T2 (30 names) + heavy filters is prone to memorizing potholes. Full F&O cash list (100+) is Tier C follow-up; Sprint 4 documents the need but stays on T2 for parity with Phase 1–3 unless symbol list is expanded later.

### 2.3 EOD clock vs target (agree)

`ENTRY_CUTOFF_TIME=14:00`, square-off **15:15** → a 13:45 entry has ~**5** fifteen-minute bars left. A 3.5 ATR target is unlikely; 1.5 ATR stop remains fully exposed to noise.

**Sprint 4 note:** `TIME_STOP_BARS` exit is **not yet implemented** in the agent/sim. Documented as follow-up (Sprint 4e in IMPLEMENTATIONS). Mean-exit variants may partially mitigate by closing earlier at RSI 50 / VWAP.

### 2.4 Slippage (agree)

Sim uses flat **₹42/trade** (`costs.py`); no per-leg slippage. `USER_GUIDE.md` already warns bootstrap ignores slippage.

Sprint 4 applies **0.05% per leg** (0.1% round-trip on notional) as a **post-sim stress test** on trade records — no change to live agent until results justify it.

### 2.5 Paper trial stance

Proceed with Monday paper as **observational** (journal vs sim per trade, `paper_trial_log.md`). Treat Sprint 4 as **validation before any config promotion** beyond the current trial stack.

---

## 3. Sprint 4 design (implemented in `research_phases.py`)

**Base entry stack:** Test 9 — pivot proximity + RSI>80 + hour<14 + denylist (`PIVOT_STACK`).

| ID | Label | Exit / friction | Purpose |
|----|-------|-----------------|--------|
| **p4_control** | Phase 2 winner | ATR stop 1.5, target **3.5**, trailing on | Reproduce +₹45 reference |
| **p4_mean_rsi** | Mean exit (RSI 50) | ATR stop 1.5, target **disabled** (mult=50), trailing **off**, `RSI_EXIT=50` | Gemini fix #1 / #5 |
| **p4_mean_rsi_vwap** | Mean + VWAP exit | Above + `VWAP_EXIT_ENABLED=true` | Second mean proxy |
| **p4_mean_rsi_slip** | Mean RSI + slippage | Same as p4_mean_rsi + 0.05%/leg | Gemini fix #4 |
| **p4_control_slip** | Control + slippage | Phase 2 winner + 0.05%/leg | Stress current paper stack |
| **p4_no_denylist** | Mean RSI, no denylist | `EXCLUDED_SYMBOLS` empty | Selection-bias falsification |

**Gates (Sprint 4):**

1. **Primary:** `p4_mean_rsi` net ≥ `p4_control` net (beat Phase 2 winner on same window).
2. **Friction:** `p4_mean_rsi_slip` net > 0 (or beat slippage-adjusted control).
3. **Sample:** trades ≥ 15 (same minimum as Phase 1).
4. **Decision:** If mean exit wins under slippage → consider `.env` exit change **after** paper journal review; else keep target 3.5 for paper trial only.

**Not in Sprint 4 code (deferred):**

- Time stop after N bars (`TIME_STOP_BARS`) — needs `strategy.py` / sim hook.
- Top-100 volume universe — needs expanded symbol list + cache warming.

---

## 4. Commands

```bash
# After 15:30 IST — paper session done for the day
python tools/research_phases.py --phase 4

# Optional: custom window / source
python tools/research_phases.py --phase 4 --days 180 --source cache
```

Phase 1–3 unchanged:

```bash
python tools/research_phases.py              # runs phases 1,2,3 (default)
python tools/research_phases.py --phase 1,2,3
```

---

## 5. References

| Artifact | Path |
|----------|------|
| Phase 1–3 results | `PHASE_FINDINGS.md`, `phase_findings.json` |
| Loss decomposition | `loss_decomposition.md` |
| Implementations ledger | `IMPLEMENTATIONS_AND_NEXT_RESEARCH.md` |
| Paper trial log | `paper_trial_log.md` |
| Mean reversion reference (video) | `MEAN_REVERSION_REFERENCE.md` |

---

## 6. Gemini Round 2 (intraday MR + VWAP + India cash market)

**Date:** Jun 2026 (during paper trial Day 1 — 2026-06-22, cycle 1: 0 signals; CIPLA RSI 81.4 blocked by pivot/vol gate)

Second critique synthesizes web research on Indian intraday MR, VWAP institutional flow, and RSI-as-momentum (not pure MR). Mapped below against repo evidence and Sprint 4/5 plan.

### 6.1 Executive blind spots (Gemini Round 2)

| Blind spot | Gemini claim | Repo reality | Status |
|------------|--------------|--------------|--------|
| **Curve-fitting** | 21 trades + denylist = hindsight bias; need 150–200+ trades | Denylist removed in `p4_no_denylist`; T2 only (30 names) | Sprint 4 partial; **Sprint 5: Nifty 100** |
| **RSI ≠ MR** | RSI>80 in trends = strength; need regime / exhaustion filter | Unfiltered baseline −₹3k+; ADX/regime partially explored, not on Test 9 stack | **Sprint 5: regime + volume surge block** |
| **VWAP gravity** | Institutions anchor to VWAP; fade only when extended above VWAP; exit at VWAP touch | Paper stack has `VWAP_FILTER_ENABLED=false`; `vwap_allows_entry` SHORT requires `close < vwap` when filter on — **opposite of fade-from-above MR** | **Sprint 5: fix VWAP entry profile + extension gate** |
| **ATR target 3.5** | Hid the problem; mean exit is correct | Phase 2: target hit **1×**; RSI mid-line **7×** (+₹723) | Sprint 4 `p4_mean_rsi*` tests this |
| **Paper promotion premature** | Phase 3 deploy before unfalsified edge | Paper trial = **observational** only; Sprint 4 post EOD | Aligned |
| **Slippage** | Fade extremes = bad fills | 0.05%/leg in `p4_*_slip` variants | Sprint 4 |

### 6.2 What Round 2 adds beyond Round 1

1. **Dynamic regime over static pivots** — pivots are session-fixed; Gemini argues for VWAP distance / relative volume / VIX (we have `market_regime.py` VIX+Nifty EMA but not wired into Test 9 paper stack).
2. **VWAP as entry + exit anchor** — not just RSI 50 exit; require extension above VWAP to short, exit on VWAP touch (institutional mean).
3. **Volume surge filter** — block fade when intraday vol >200% of 10-day average (breakout vs MR).
4. **Stronger sample gate** — 150+ trades / 180d, not 15 (Sprint 4 keeps 15 for parity with Phase 1; Sprint 5 raises bar).

### 6.3 Repo counter-evidence (unchanged, worth repeating)

- **+₹45 is not an ATR-target story** — see §2.1 exit table (1 target vs 7 RSI mid-line).
- **Pivot + hour + RSI>80 did reduce bleed** — filter ablation Test 9: −₹133 vs baseline −₹3,122 (different run snapshot); filters are doing real work, but **n** is tiny.
- **REGIME_FILTER** exists (`VIX_MAX`, Nifty EMA) but bake-off ADX bands did not beat baseline — regime work is **unfinished**, not absent.

### 6.4 Sprint roadmap (4 vs 5)

**Sprint 4 (today post 15:30 — coded, not run):**

```bash
python tools/research_phases.py --phase 4
```

| Variant | Round 2 coverage |
|---------|------------------|
| `p4_mean_rsi` / `p4_mean_rsi_vwap` | Structural mean exit (Step 1) |
| `p4_no_denylist` | Remove hindsight bias (Step 2 partial) |
| `p4_*_slip` | Microstructure friction (Step 4) |
| `p4_control` | Phase 2 reference |

**Sprint 5 (planned — not coded yet):**

| Step | Work | Code touch |
|------|------|------------|
| **5a** | Nifty 100 (or F&O liquid) universe, no denylist | `universe.py` + cache warm |
| **5b** | VWAP MR entry: short only if `close > vwap` + min extension (Z-score or %) | Fix `vwap_allows_entry` MR profile in `strategy.py` |
| **5c** | VWAP touch exit (primary target), disable ATR target | `vwap_breakdown` / exit_reason review |
| **5d** | Volume surge block (>200% 10d avg intraday) | `SimEntryFilter` or strategy gate |
| **5e** | Regime stack on Test 9: VIX + Nifty EMA + optional ADX range | `market_regime.py` + sim overrides |
| **5f** | Gate: **≥150 trades** and net > 0 after slippage | `research_phases.py` phase 5 |

### 6.5 Paper trial Day 1 note (2026-06-22)

Zero entries on cycle 1 is **expected** for a heavily gated stack (~1 trade / 8.5 days in sim). Log in `paper_trial_log.md`; do not interpret one quiet cycle as failure. Compare **weekly** signal rate vs sim after 5–10 sessions.

### 6.6 External video (VWAP + structure)

[Intraday Trading Strategy using VWAP And Moving Averages](https://www.youtube.com/watch?v=DVQieGE_oVw) — practical VWAP + MA combinations for filtering intraday entries and avoiding fades in strong directional sessions (aligns with Round 2 regime-over-pivot argument).

See also `MEAN_REVERSION_REFERENCE.md` (Sandeep Rao MR taxonomy).
