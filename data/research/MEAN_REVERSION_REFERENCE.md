# Mean Reversion — External Reference (Video Summary)

**Source:** AI summary of Sandeep Rao, *The Long & Short* — Mean Reversion Trading (Ep. 17, Indian market context)  
**Purpose:** Research context for `rsi_mr` design choices, Sprint 4, and why trend-entry ports (SBP, vst_ai, zp_dmi) stay shelved.  
**Not a trade recommendation** — framework only, per the host.

---

## 1. Core idea

**Mean reversion (MR)** bets that an overextended price will **snap back** toward its average (rubber-band metaphor). **Trend following** joins momentum; **MR** fades extension.

MR is **not** meant to run in isolation — it works best as a **portfolio leg** that fills the “potholes” of trend strategies (different phases, often inverse correlation across assets).

---

## 2. Four types of mean reversion (taxonomy)

| Type | Idea | Example tools | This repo |
|------|------|---------------|-----------|
| **1. Single-asset price reversion** | One symbol reverts to its own average | MA, RSI, Bollinger | **`rsi_mr`** (primary) |
| **2. Volatility reversion** | Vol cycles; squeeze → expansion | BB squeeze, NR7 | Not implemented |
| **3. Relative value** | Mispricing between related instruments | Basis, calendar spreads, put–call parity | Not implemented |
| **4. Pairs / stat arb** | Two correlated names diverge → convergence | HDFC vs ICICI pair | Not implemented (`rs_mr` is RSI(2) pullback, not pairs) |

**Agent scope today:** Type **1** only — Nifty 50 single-name MIS, 15m, short-biased rsi_mr + filters.

---

## 3. Strategy showcase from the video (daily Nifty + Gold)

**Universe:** Long-only MR on **Nifty** and **Gold**, daily timeframe.

**Entry:** Long when price **closes back inside** the lower Bollinger Band after an initial close **outside** it (confirmation of snap-back, not blind fade at the band).

**Exit / risk:** **Trailing stop tied to the lower Bollinger Band** — stop moves with the mean, not a fixed multiple-of-ATR profit target far from the mean.

**Backtest note:** Nifty and Gold had similar cumulative returns but **peaked in different phases** (inverse correlation) — supports multi-leg portfolios, not single-strategy heroics.

**Host disclaimer:** Shared logic is a **framework**; customize, control risk, fit your own book.

---

## 4. Mapping to Auto_trading research

### 4.1 What we already align with

| Video principle | Our implementation |
|-----------------|-------------------|
| Fade overextension | `RSI > RSI_OVERBOUGHT` (short) / volume filter |
| Revert toward a **mean** | `RSI_EXIT=50` (mid-line exit); session **VWAP** exit path exists |
| MR ≠ primary trend engine | Trend ports (`sbp_tm`, `vst_ai`, `zp_dmi`) **failed bake-off**; rsi_mr stays control |
| Portfolio context | Paper stack is one MR leg; no live multi-strategy book yet |
| Framework, not gospel | Phase sprints + bake-offs before `.env` promotion |

**Sprint 4 (`p4_mean_rsi`, `p4_mean_rsi_vwap`)** directly tests the video/Gemini thesis: **exit at the mean** (RSI 50 / VWAP) instead of optimizing **fixed ATR target mult** on filtered entries.

### 4.2 Where we diverge (intentionally or open research)

| Video / Gemini | Our stack | Research note |
|-------|-----------|---------------|
| **Entry:** re-entry *inside* band after outside close | Entry on RSI extreme + pivot proximity | BB re-entry untested on 15m MIS |
| **Entry:** short only when **extended above VWAP** | `VWAP_FILTER_ENABLED=false` in paper; when on, SHORT requires `close < vwap` | **Likely inverted for MR fade** — Sprint 5 |
| **Exit:** trailing stop on **lower BB** (dynamic mean) | Paper: ATR stop 1.5 + target 3.5 + trailing | Phase 2 target rarely fires; Sprint 4 tests RSI/VWAP mean exit |
| **Timeframe:** daily | 15m intraday MIS | EOD square-off 15:15 caps hold time — time stop still deferred |
| **Direction:** long-only example | Short-only paper (`ALLOW_SHORT`) | Same MR logic, inverted (fade overbought) |
| **Universe:** Nifty + Gold | Nifty 50 equities | No cross-asset MR diversification in sim yet |

### 4.3 Exit families vs video (baseline decomposition)

On **unfiltered** 180d rsi_mr (`loss_decomposition.md`):

| Exit path | Trades | Net ₹ | MR interpretation |
|-----------|--------|-------|-------------------|
| RSI mid-line exit | 22 | **+2,230** | Exit when stretch **normalizes** — closest to video philosophy |
| ATR target | 15 | +2,975 | Fixed reward; not mean-linked |
| ATR stop | 49 | **−9,342** | Stop-out before reversion completes |

Filtered stack (`PHASE_FINDINGS.md`): RSI mid-line **+723** (7 trades) vs ATR target **+112** (1 trade) — **mean exit already carries filtered-stack P&L**, not wide targets.

### 4.4 Types 2–4 (future, deprioritized)

- **Volatility MR** (NR7, BB squeeze): possible filter *on* rsi_mr entries, not a new primary strategy until Type 1 net is stable.
- **Relative value / pairs:** out of scope per `AGENTS.md` unless explicitly requested; different capital, execution, and data model.

---

## 5. Design rules implied by this reference

1. **Entries:** fade extension with confluence (RSI + pivot + time) — analogous to “outside then back inside” confirmation, but our trigger is RSI/volume not BB re-entry.
2. **Exits:** prefer **mean normalization** (RSI 50, VWAP, or band-linked trail) over **fixed distant targets** on MR setups.
3. **Stops:** protect against band **break** (continued trend), not arbitrary wide ATR targets that MR rarely reaches in 15m MIS.
4. **Portfolio:** keep MR as **filtered, low-frequency** leg; do not replace with trend indicators that over-trade on 15m.
5. **Validation:** Sprint 4 + slippage + (later) broader universe — same bar as video’s “customize and backtest before trading.”

---

## 6. Related artifacts

| Doc | Link |
|-----|------|
| Gemini critique + Sprint 4 plan | `GEMINI_CRITIQUE_AND_SPRINT4.md` |
| Phase 1–3 results | `PHASE_FINDINGS.md` |
| Sprint 4 command | `python tools/research_phases.py --phase 4` |
| Implementations ledger | `IMPLEMENTATIONS_AND_NEXT_RESEARCH.md` |
| Gemini Round 2 (VWAP / regime) | `GEMINI_CRITIQUE_AND_SPRINT4.md` §6 |
| Paper trial | `paper_trial_log.md` |

---

## 7. Optional follow-ups (not scheduled)

- **BB re-entry entry** on 15m (video-style) vs current RSI extreme — A/B on Test 9 stack.
- **BB lower-band trailing stop** as exit instead of ATR target mult — needs `strategy.py` hook.
- **Regime split:** run MR leg only when Nifty not in strong trend (ADX / EMA filter already partially explored).
