# Mean Reversion — External Reference (Video Sync)

**Source:** [Mean Reversion Trading — Part 2 | The Long & The Short Ep.17](https://www.youtube.com/watch?v=NHFLQtinB48) (Sandeep Rao)  
**Synced:** 2026-08-04 against validated T2 paper stack  
**Purpose:** Map the video’s MR framework to this repo. **Not a trade recommendation.**  
**Paper stack unchanged by this sync** — see [EDGE_VALIDATED.md](EDGE_VALIDATED.md).

---

## 1. Segment map

| Time | Topic |
|------|--------|
| 0:51–2:03 | Theory: MR vs trend — overextended price “snaps back” to average |
| 2:16–3:04 | Type 1 — single-asset price reversion (avg as magnet) |
| 3:05–5:33 | Type 2 — volatility reversion (BB squeeze, NR7, options) |
| 5:34–8:03 | Type 3 — relative value (basis, calendars, synthetics) |
| 8:04–9:33 | Type 4 — pairs / stat arb |
| 9:34–11:11 | Showcase: long-only BB(20, 2σ) on daily Nifty + Gold |
| 12:00–13:14 | Results: similar cum returns; Gold better vs max DD; Nifty slightly higher WR |
| 13:15–14:00 | Takeaway: MR fills “potholes” in a book dominated by trend legs |

---

## 2. Core idea

**Mean reversion** fades extension toward a mean. **Trend following** joins momentum. The host’s portfolio point: MR is rarely the sole engine — it **smooths equity** when trend strategies struggle (often different seasons / assets).

Our agent is a **single Type-1 leg** (filtered short rsi_mr). We do **not** run a multi-strategy book yet; video portfolio advice is context, not a prompt to enable ORB/EMA.

---

## 3. Four types → this repo

| Type | Video idea | Tools (video) | This repo |
|------|------------|---------------|-----------|
| **1. Single-asset price MR** | Price snaps to its own average | MA, RSI, Bollinger | **`rsi_mr`** — paper primary ([EDGE_VALIDATED.md](EDGE_VALIDATED.md)) |
| **2. Volatility MR** | Vol extremes revert (squeeze → expansion, or crush) | BB squeeze, NR7, long/short straddle-strangle | BB/NR7 still deferred. **Paper** NIFTY options scaffold exists (`--mode fno`); live F&O out of scope ([OPTIONS_FNO_ANALYSIS.md](OPTIONS_FNO_ANALYSIS.md)) |
| **3. Relative value** | Mispricing across related instruments | Basis, calendar, synthetic futures | **Out of scope** |
| **4. Pairs / stat arb** | Correlated pair divergence → convergence | e.g. bank pairs | **Kill list** — `rs_mr` is RSI(2) pullback, **not** pairs |

**Agent scope today:** Type **1** only — `SCAN_UNIVERSE=t2`, 15m MIS, short-biased rsi_mr.

---

## 4. Volatility tools (Type 2 detail)

| Tool | Video use | Repo stance |
|------|-----------|-------------|
| **BB squeeze** | Low vol → bands tight → expect expansion (breakout / move) | Deferred as optional **filter** on rsi_mr only after P3; not a primary strategy ([COOKBOOK_REEVAL.md](COOKBOOK_REEVAL.md) — do not port BB for paper) |
| **NR7 / narrow range** | Restricted range primes a large move (Toby Crabel) | Same — deferred filter idea |
| **Options** | Expand → long straddle/strangle; crush → short strangle | **Paper scaffold** (`run_agent.py --mode fno` / `--mode both`); live NFO blocked ([OPTIONS_FNO_ANALYSIS.md](OPTIONS_FNO_ANALYSIS.md)) |

Note: squeeze/NR7 often **anticipate expansion** (trend/breakout follow-through), which is closer to our **rejected** ORB class than to RSI fade. Use with caution if ever gated onto rsi_mr.

---

## 5. Video showcase vs validated paper stack

| Dimension | Video BB showcase | Repo `rsi_mr` (paper) |
|-----------|-------------------|------------------------|
| Universe | Daily Nifty + Gold | T2 equities (30 liquid) |
| Direction | Long-only | Short-only (`ALLOW_LONG=false`) |
| Entry | Close back **inside** lower BB after outside close | RSI > 80 + volume + pivot; cutoff 13:00 |
| Mean exit | Trail / mean linked to BB | **RSI 50** (`ATR_TARGET_MULT=50`) |
| Stop | Lower-BB trail (video) | ATR 1.25× **underwater only**; trailing **off** |
| Sim ref | Host 10y Nifty/Gold (qualitative) | **+₹2,438** / Sharpe 1.49 / 26 trades / 180d T2 |
| Paper | — | P3 in progress; 2026-08-04 session: 0 trades (no RSI>80) |

---

## 6. Mapping to Auto_trading research

### 6.1 Aligned

| Video principle | Our implementation |
|-----------------|-------------------|
| Fade overextension | `RSI_OVERBOUGHT=80` + volume / pivot / surge / CIPLA trap |
| Exit toward the **mean** | `RSI_EXIT=50` (Sprint 4 winner; still paper default) |
| MR ≠ replace trend engine | ORB / VWAP / EMA / MACD / Quadapt / Pine ports **killed or shelved** |
| Customize + backtest | Edge search + paper gate before live |
| Different seasons | Sparse T2 signals (~1 trade / 10 days sim); log by session in [paper_trial_log.md](paper_trial_log.md) |

### 6.2 Intentional divergences

| Video | Our stack | Why |
|-------|-----------|-----|
| BB re-entry entry | RSI extreme + filters | Untested on 15m MIS; cookbook: no BB port for paper |
| BB-band trailing stop | ATR stop underwater; trailing off | Trailing cut winners in Jun paper; mean exit preferred |
| Daily TF | 15m + EOD square-off 15:15 | MIS product constraint |
| Long Nifty/Gold | Short T2 names | Equity MIS short MR; no commodity book |
| MR as portfolio sleeve | Single strategy agent | Multi-strat / REGIME_ADAPTIVE blocked (ORB −₹42k) |

### 6.3 Exit evidence (still supports “exit at mean”)

Unfiltered 180d decomposition: RSI mid-line exits net **positive**; ATR stops dominate losses. Sprint 4 / edge search kept RSI 50 + underwater ATR stop. Time-stop 4–5 bars **hurt** — keep `TIME_STOP_BARS=0`.

---

## 7. Research update verdict (2026-08-04)

| Question | Answer |
|----------|--------|
| Does the video require new strategies? | **No** |
| Does paper `.env` need changes? | **No** — keep EDGE_VALIDATED stack |
| Doc refresh needed? | **Yes** — this file (was stale: ATR 1.5/trailing/N50) |
| Type 2–4 promote? | **No** until Type 1 paper P3 passes; 3–4 remain out of scope |
| Next execution | Continue **P3 paper** (`python run_agent.py`) |

---

## 8. Deferred follow-ups (not scheduled)

Only after P3 (≥15 sessions, net ≥ 0):

1. BB re-entry entry A/B vs RSI extreme on T2 cache  
2. BB-band trail as stop alternative (not time stop)  
3. BB squeeze / NR7 as **entry filter** on rsi_mr (gate, not new primary)

---

## 9. Related artifacts

| Doc | Role |
|-----|------|
| [EDGE_VALIDATED.md](EDGE_VALIDATED.md) | Paper stack + numbers |
| [FINDINGS_AND_NEXT_STEPS.md](FINDINGS_AND_NEXT_STEPS.md) | Master plan + kill list |
| [COOKBOOK_REEVAL.md](COOKBOOK_REEVAL.md) | No BB/EMA/MACD for paper |
| [strategy_compare_orb_vwap_tier2.md](strategy_compare_orb_vwap_tier2.md) | Trend class −₹42k |
| [paper_trial_log.md](paper_trial_log.md) | Live paper sessions |
| [GEMINI_CRITIQUE_AND_SPRINT4.md](GEMINI_CRITIQUE_AND_SPRINT4.md) | Sprint 4 mean-exit thesis |
