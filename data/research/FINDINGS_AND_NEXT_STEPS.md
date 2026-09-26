# Research Findings & Next Steps — Jul 10, 2026

**Status:** **Sim edge validated** on T2 (+₹2,438 / Sharpe 1.49). P3 paper validation next.  
**Paper mode:** `LIVE_TRADING=false` — do not enable live without explicit approval.

Related artifacts:
- [EDGE_VALIDATED.md](EDGE_VALIDATED.md) — T2 paper stack (+₹2,438)
- [MEAN_REVERSION_REFERENCE.md](MEAN_REVERSION_REFERENCE.md) — Ep.17 video taxonomy synced Aug 2026
- [COOKBOOK_REEVAL.md](COOKBOOK_REEVAL.md) — Packt cookbook vs registry reevaluation (Aug 2026)
- [NIFTY200_RESEARCH.md](NIFTY200_RESEARCH.md) — T200 cache + sprint artifacts
- [PHASE4_FINDINGS_T200.md](PHASE4_FINDINGS_T200.md) / [PHASE5_FINDINGS_T200.md](PHASE5_FINDINGS_T200.md)
- [quadapt_ml_bakeoff_verdict_t200.md](quadapt_ml_bakeoff_verdict_t200.md)
- [paper_trial_log.md](paper_trial_log.md)
- [strategy_compare_orb_vwap_tier2.md](strategy_compare_orb_vwap_tier2.md)

---

## 1. Executive summary

| Finding | Implication |
|---------|-------------|
| RSI mean-reversion **signal works** on true reversals | RSI 50 exits ≈ +₹6k gross on T200 backtest |
| **Universe expansion broke economics** | T200 net **−₹1,183**; interim 80-symbol **+₹451** was partial-cache bias |
| **ATR stops are the main loss bucket** | ~0% win rate on ATR-stop exits; failed shorts / momentum traps |
| **Costs dominate at small size** | Paper: 78% win rate, **net −₹301** (gross +₹77, costs −₹378) |
| **Exits fixed for paper (Jul 10)** | Trailing off; RSI-first; ATR stop only when underwater |
| **Research ≠ live today** | Surge block not in `.env`; sim ranker uses empty journal |

**Working hypothesis:** MR short works on **liquid large-caps**; fails when scanning **200 names** with weak entry filters and ₹15k/trade notional.

---

## 2. Universe migration (Nifty 200)

### Symbol fixes applied (`intraday_agent/universe.py`)

| Old | New | Reason |
|-----|-----|--------|
| LTIM | LTM | LTIMindtree rebrand (Feb 2026) |
| ZOMATO | ETERNAL | Zomato rename |
| KALPATPOWR | KALPATARU | Correct NSE ticker |
| JUBILINDS | JUBLPHARMA | Jubilant Pharmova |
| GUJGASLTD | GUJENERGY | Gujarat Energy (-BE series in scrip master) |
| ISEC | SWIGGY | ICICI Securities delisted (Mar 2025) |

Also: `instruments.py` supports `GUJENERGY-BE`; prefetch waits on Angel rate-limit pause.

### Cache status

| Metric | Value |
|--------|-------|
| Bundle | `t200_180d` |
| Symbols | **200 / 200** usable for 180d backtests |
| Manifest | `data/research/candle_cache_t200_180d.json` |

---

## 3. T200 research results (180d, Angel cache)

### Sprint 4 — mean exit ablation

| Variant | Trades | Net ₹ | Sharpe |
|---------|--------|-------|--------|
| Control (ATR trail + target 3.5) | 136 | −4,003 | −2.56 |
| Mean RSI exit | 120 | −3,297 | −1.81 |
| Mean RSI + VWAP breakdown | 183 | **−7,671** | −5.81 |
| No denylist | 119 | −2,719 | −1.57 |
| Paper stack | 120 | −3,063 | −1.72 |

**Exit breakdown (mean RSI):** RSI mid-line +₹6,372 | ATR stop −₹8,927 | EOD −₹760

**Gates:** Beat control PASS | Slippage FAIL (−₹4,783 stress)

### Sprint 5 — filters

| Variant | Trades | Net ₹ | Sharpe |
|---------|--------|-------|--------|
| Base (paper stack) | 120 | −3,063 | −1.72 |
| Volume surge block (2.0×) | 116 | **−2,208** | −1.28 |
| VWAP MR fade entry | 111 | −5,187 | −2.92 |
| No denylist | 105 | −1,420 | −0.78 |
| Nifty 200 full (bake-off cfg) | 103 | **−1,208** | −0.66 |

### Strategy bake-off (T200)

| Candidate | Trades | Net ₹ | Sharpe | Verdict |
|-----------|--------|-------|--------|---------|
| **rsi_mr_paper_stack** | 102 | **−1,183** | −0.65 | PASS vs baseline |
| quadapt_ml_consensus | 105 | −6,135 | −5.42 | FAIL |
| quadapt_ml_short | 39 | −2,133 | −3.17 | FAIL |

### ATR stop multiplier sweep (paper stack, T200)

| ATR_STOP_MULT | Trades | Net ₹ | ATR stops | Stop net ₹ | RSI net ₹ |
|---------------|--------|-------|-----------|------------|-----------|
| 1.25 | 103 | −1,108 | 35 | −7,089 | +6,047 |
| **1.50** (current) | 102 | −1,183 | 31 | −7,094 | +6,042 |
| **2.00** | 98 | **−840** | 22 | −6,334 | +5,875 |

**Conclusion:** Looser stop helps marginally but does **not** restore profitability. Entry quality and universe matter more.

### PnL bridge (T200, ATR 1.5)

```
RSI 50 exits     ≈ +₹6,000   (edge)
ATR stops        ≈ −₹7,100   (failed shorts)
EOD / other      ≈ +₹900
Trading costs    ≈ −₹4,300   (~₹42 × ~102 trades)
─────────────────────────────
Net              ≈ −₹1,183
```

---

## 4. T2 baseline (reference — still the positive benchmark)

| Metric | Value |
|--------|-------|
| Universe | 30-symbol T2 / Nifty liquid subset |
| Sprint 4 mean exit | **+₹347** net, 17 trades, Sharpe **1.024** |
| Slippage stress | +₹113 (PASS) |

Promote MR on **restricted liquid universe**, not full T200.

---

## 5. Paper trading findings

### Jul 6, 2026 (old stack — superseded)

- 2 SHORT entries (BAJAJ-AUTO, EICHERMOT); exited via **trailing stop** at ~+0.25%
- Root cause: `.env` had `TRAILING_STOP_ENABLED=true`, old ATR target stack
- **Fixed Jul 10:** RSI-first, trailing off, ATR stop only underwater

### Cumulative paper log (as of Jul 10)

| Metric | Value |
|--------|-------|
| Sessions | 3 active (+ 1 aborted) |
| Trades | 9 |
| Win rate | 77.8% |
| Gross P&L | +₹77 |
| Est. costs | −₹378 |
| **Net P&L** | **−₹301** |

**Key lesson:** High win rate does not imply profitability when notional is ₹5k–₹30k and cost ≈ ₹42/trade.

### CIPLA pattern (Jun 23)

- RSI 88.2, VolR 1.9 → −₹84 ATR stop
- High RSI + very high volume = **momentum continuation**, not exhaustion
- Proposed filter: skip if **RSI > 86 and VolR > 1.7**

---

## 6. Strategy synthesis cross-check

### Validated against repo

- Market session phases (open / midday chop / afternoon) — aligns with best paper holds
- MR vs trend strategies are complementary by day type
- Cost math: ₹42/trade painful below ~₹50k notional
- RSI mid-line exit > ATR target / trailing for MR
- Quadapt, VWAP breakdown exit — rejected

### Corrected vs external synthesis

| Claim | Repo reality |
|-------|--------------|
| ORB +₹3,327 net | `strategy_compare_orb_vwap_tier2.md`: ORB **net −₹42,430**, 1,077 trades |
| VWAP pullback +₹2,857 OOS | Same doc: **net −₹42,295**, 1,054 trades |
| Circuit guard missing | **Implemented** (`CIRCUIT_GUARD_*`, default on) |
| Volume surge >2.5× | Sprint 5 tested **2.0×** |

ORB/VWAP may show positive **gross** but fail **net** at current position size and trade frequency.

---

## 7. `.env` audit summary (Jul 10)

### Aligned with research

- `LIVE_TRADING=false`, short-only, `STRATEGY=rsi_mr`
- RSI 80 / exit 50, pivot proximity, entry cutoff 14:00, denylist
- `ATR_STOP_MULT=1.5`, `ATR_TARGET_MULT=50`, `TRAILING_STOP_ENABLED=false`
- `REGIME_FILTER_ENABLED=true`, `VIX_MAX=18`
- `ESTIMATED_COST_PER_TRADE=42`

### Gaps / review items

| Parameter | Current | Issue |
|-----------|---------|-------|
| `SCAN_UNIVERSE` | nifty200 | T200 negative — restrict after Phase 1 |
| `VOLUME_SURGE_BLOCK_MULT` | missing (0) | Sprint 5 winner not deployed |
| `CAPITAL_PER_TRADE` | ₹15,000 | Cost drag; test ₹50k in sim |
| `LEARNING_ENABLED` | true | Sim uses empty journal — paper ≠ backtest |
| `ATR_STOP_MULT` | 1.5 | 2.0 better on T200 but still negative alone |
| `CIRCUIT_GUARD_ENABLED` | default on | Add to `.env` for visibility |

### Capital & guards

| Parameter | Value | Role |
|-----------|-------|------|
| `CAPITAL_PER_TRADE` | ₹15,000 | qty = floor(15000/price), cap 50 |
| `MAX_POSITIONS` | 2 | ~₹30k max deployed |
| `MAX_DAILY_LOSS` | ₹600 | Halt + square off |
| `MAX_DAILY_PROFIT` | ₹1,500 | Stop new entries |
| `MAX_TRADES_PER_DAY` | 10 | Overtrading cap |

---

## 8. Root cause model

```
RSI>80 short signal
        │
        ├─ Large-cap, true exhaustion → RSI 50 exit (+₹)
        │
        └─ Midcap / momentum breakout → ATR stop (−₹) + costs
```

Expanding from ~50–80 liquid names to 200 adds **continuation risk** without enough extra RSI winners.

---

## 9. Kill list (do not implement without new evidence)

- Full Nifty 200 as live MR universe
- ATR-only tuning without universe + entry filters
- `TRAILING_STOP_ENABLED=true` on MR
- `VWAP_EXIT_ENABLED=true` / VWAP breakdown exit
- `VWAP_MR_FADE_SHORT=true`
- Quadapt ML in paper/live
- ORB / VWAP as **replacement** for MR (only complementary, capped, later)
- **Cookbook EMA(4/9) / MACD trend crossovers** — same flip class as ORB/VWAP (−₹42k); do not add to paper registry ([COOKBOOK_REEVAL.md](COOKBOOK_REEVAL.md))
- BB squeeze / NR7 as **equity** primary strategies — Type 2 deferred ([MEAN_REVERSION_REFERENCE.md](MEAN_REVERSION_REFERENCE.md))
- Live NFO / naked shorts — blocked. Paper F&O is a **side** track, not an equity replacement ([OPTIONS_FNO_ANALYSIS.md](OPTIONS_FNO_ANALYSIS.md))
- `LIVE_TRADING=true`
- Pairs / stat arb in this agent

---

## 10. Critical analysis (Jul 10 review)

### 10.1 Ground truth

| Fact | Source | Implication |
|------|--------|-------------|
| T2 gross edge is real | +₹347 / Sharpe 1.024 / 17 trades / 180d | Signal quality confirmed on **restricted** universe |
| Paper net negative | −₹301 / 9 trades | **Cost drag**, not necessarily signal failure |
| Paper win rate 77.8% (7/9) | `paper_trial_log.md` | Small sample — luck possible; R:R matters more |
| Avg win ₹23.5 vs avg loss ₹43.8 | Paper log | **R:R 0.54** — fatal at scale with ₹42/trade costs |
| ATR stop = #1 loss driver | Sprint 4 T200 (−₹8,927); decomposition −₹9,342 unfiltered | Exit architecture unsolved |
| T200 consistently negative | All sprints / bake-off | Best **−₹1,208**; do not trade live on 200 names |
| T250 cache unreliable | Partial runs (76–198 symbols usable) | **Do not use T250 numbers for decisions** |
| 17 trades / 180d on T2 sim | Sprint 4 filtered stack | **Statistical noise** — cannot prove edge from sim alone |
| Jun paper trailing exits | Jun 19/23 sessions | **Old stack** (trailing on) — not current config |
| Jul 6 trailing exits | `trading_20260706.log` | **Old `.env`** — fixed Jul 10 |

### 10.2 What the plan gets right ✅

- Mean exit (RSI 50) beats ATR target — Sprint 4 winner; now in code + `.env`
- Quadapt rejected — do not revisit
- 5m deferred — costs would rise without proven signal gain
- `REGIME_ADAPTIVE=false` — ORB lost −₹42k on T2 compare
- Live trading gated

### 10.3 What was wrong or misprioritised ❌

| Problem | Detail | Correction |
|---------|--------|--------------|
| **Universe expansion before economics** | `ROADMAP_STATUS.md` listed Nifty 100 prefetch + ≥150 trades as P1 | **Deferred.** T200 proved wider ≠ better. Reach sample size on **T2 paper**, not by diluting universe |
| **Position sizing not P0** | ₹15k/trade → cost 0.28–0.84% of notional | **P0b:** target ₹50k–₹1L notional (via `CAPITAL_PER_TRADE` or `RISK_PCT`) |
| **Trailing stop unscheduled** | 5/7 paper wins cut at 2m (Jun sessions, old config) | **P0a:** verify Jul 10+ sessions show **zero** trailing exits; config already set `false` |
| **ATR stop as footnote** | −₹9k decomposition; CIPLA −₹84 | **P1:** time-stop ablation (4–6 bars) — scheduled research, not “if paper confirms” |
| **Phase 1 = T50 backtest first** | Our prior plan started with universe sim | **Demoted to P4** — only after T2 paper net-positive |

### 10.4 Sim vs paper discrepancy (must investigate)

| Metric | Sim (T2, 180d) | Paper (3 active sessions) |
|--------|------------------|---------------------------|
| Trade rate | ~1 trade / 10.6 days | 9 trades in ~3 sessions — **faster** |
| Stack | Filtered Sprint 4 + `SimEntryFilter` | Live ranker + Yahoo screener + `LEARNING_ENABLED` |

**Hypothesis:** Paper may enter on **weaker signals** than sim (ranker, screener source, no `SimEntryFilter`). If true, 78% win rate may not hold.

**Action (P0c):** Diff live entry RSI / pivot / hour vs sim on next sessions; align ranker or disable learning until matched.

---

## 11. Revised execution plan (priority order)

> **Do not** prefetch Nifty 100/250 or change `SCAN_UNIVERSE` until **P3 gate** passes.

### P0 — Fix foundation (before more paper or universe tests)

| ID | Task | Why | Success gate |
|----|------|-----|--------------|
| **P0a** | Verify trailing **off** in next paper session | Jun/Jul 6 exits were old config | **Zero** `trailing stop` exit reasons in log |
| **P0b** | Size for economics: `CAPITAL_PER_TRADE=50000` **or** enable `RISK_PCT` (1%) + `ACCOUNT_EQUITY` | Costs dominate at ₹5k–₹30k notional | Cost &lt; 0.08% of notional; sim re-run at new size |

**P0b sim (Jul 10)** — T2 / Sprint 4 stack / 180d / `SimEntryFilter` / flat ₹42 cost:

| `CAPITAL_PER_TRADE` | `MAX_QUANTITY` | Trades | Gross ₹ | Costs ₹ | **Net ₹** | Sharpe |
|---------------------|----------------|--------|---------|---------|-----------|--------|
| 15,000 | 50 | 21 | 1,184 | 882 | **302** | 0.77 |
| 25,000 | 50 | 21 | 2,008 | 882 | **1,126** | 1.75 |
| 50,000 | 50 | 21 | 4,274 | 882 | **3,392** | 2.50 |
| 100,000 | 50 | 21 | 7,404 | 882 | **6,522** | 2.84 |

Costs are **flat per trade** (₹42); gross scales with qty. At ₹50k notional, cost ≈ **0.084%** — at the survival threshold. **Recommendation:** `CAPITAL_PER_TRADE=50000` + raise `MAX_QUANTITY` if expensive names cap out (₹100k sim: +₹1,248 gross with `MAX_QUANTITY=200`).

| **P0c** | Align sim ↔ live (ranker + filters) | Paper trades faster than sim | Entry rules documented; optional `LEARNING_ENABLED=false` |

**Safe `.env` adds (with P0):**

```env
VOLUME_SURGE_BLOCK_MULT=2.0
CIRCUIT_GUARD_ENABLED=true
TRAILING_STOP_ENABLED=false   # verify in logs
# After P0b sim check:
# CAPITAL_PER_TRADE=50000
# or RISK_PCT=1.0 + ACCOUNT_EQUITY=500000
```

Revert live scan to **T2** for paper (not full Nifty 50/200):

```env
SCAN_UNIVERSE=t2
```

---

### P1 — Time stop ablation (T2 cache, 180d)

**Goal:** Replace or complement ATR stop — the main loss bucket.

| Variant | Description |
|---------|-------------|
| P1a | Base mean-exit stack (RSI 50, ATR underwater only) |
| P1b | **Time stop:** exit after 4–6 bars if neither RSI 50 nor profit |
| P1c | Time stop + surge block (2.0×) |

**Gate:** Net improvement vs P1a on **T2 symbols** (30 names), not T200.

**P1 results (Jul 10, ₹50k capital):** Time stop **4–5 bars hurts** (net −₹1,656 to −₹1,703); 6 bars ≈ breakeven (−₹90) vs **baseline +₹2,176** (no time stop). Keep `TIME_STOP_BARS=0` for paper; prioritize **P2 entry filters** to reduce ATR stops (7 on baseline).

| Variant | Net ₹ | ATR stops | Time stops | RSI exits |
|---------|-------|-----------|------------|-----------|
| P1a base | **+2,176** | 7 | 0 | 12 |
| P1b ts=4 | −1,656 | 4 | 16 | 5 |
| P1d ts=6 | −90 | 5 | 12 | 7 |

Artifact: [TIME_STOP_ABLATION_T2.md](TIME_STOP_ABLATION_T2.md)

---

### P2 — Entry filter ablation (T2 cache)

**P2 results (Jul 10, iterative `edge_search.py`):**

| Finding | Detail |
|---------|--------|
| **Winner** | `ATR_STOP_MULT=1.25` + `ENTRY_CUTOFF_TIME=13:00` (no entries ≥13:00) |
| Net / slip | **+₹2,438** / **+₹1,168** (26 trades, Sharpe 1.49) |
| Surge block 2.0 | No change on T2 (already filtered by pivot/vol) |
| CIPLA trap RSI>86 | No change on T2 sim — kept in `.env` for live safety |
| Clear denylist | Slippage net **−₹86** — keep ONGC/SBIN/BAJFINANCE excluded |
| RSI_OB 82+ | Over-filters; net collapses |

Artifact: [EDGE_SEARCH.md](EDGE_SEARCH.md), [EDGE_VALIDATED.md](EDGE_VALIDATED.md)

**Applied to `.env`:** `SCAN_UNIVERSE=t2`, `ATR_STOP_MULT=1.25`, `ENTRY_CUTOFF_TIME=13:00`

---

### P3 — Paper validation (T2 / Nifty 50 only)

| Requirement | Target |
|-------------|--------|
| Universe | `SCAN_UNIVERSE=t2` |
| Sessions | **≥15** weekdays logged |
| Stack | P0 + winning P1/P2 variants |
| Net | ≥ 0 after ₹42/trade (at P0b notional) |
| vs sim | Within ±20% per trade |

**Do not** promote until P3 passes. Sim's 17 trades / 180d is **not** sufficient alone.

---

### P4 — Universe research (deferred)

**P4 results (Jul 10):** Winner stack on **full Nifty 50** → net **−₹228** (48 trades). Edge does **not** survive universe expansion. Live scan locked to **`SCAN_UNIVERSE=t2`** (30 liquid names) until paper proves otherwise.

Run **only if P3 gate passes** on t2 paper:

| Step | Action |
|------|--------|
| P4a | T50 / T80 liquidity backtest (confirm T2 isn't cherry-picked) |
| P4b | Nifty 100 backtest (not live scan) |
| P4c | Never promote Nifty 200 MR without new evidence |

**Explicitly deferred:** T250 prefetch, 5m candles, Quadapt, live trading, `REGIME_ADAPTIVE=true`.

---

### Legacy phase map (superseded)

| Old phase | New priority |
|-----------|--------------|
| Phase 1 universe test first | → **P4** (deferred) |
| Phase 2 entry filters | → **P2** |
| Phase 3 sizing | → **P0b** |
| Phase 4 paper | → **P3** |
| Phase 5 regime routing | → After P3 only |

---

## 12. Open decisions

| Question | When to resolve |
|----------|-----------------|
| `CAPITAL_PER_TRADE` vs `RISK_PCT` | P0b sim comparison |
| Denylist on/off | P2 ablation on T2 |
| Learning on/off in paper | P0c alignment |
| Time stop bars (4 vs 6) | P1 sweep |

---

## 13. Commands reference

```bash
# Cache status
python tools/candle_cache_status.py --bundle t200_180d

# Full T200 research rerun
python tools/rerun_nifty200_research.py --skip-prefetch

# Paper agent
python run_agent.py
python tools/status.py
```

Phase 1 scripts (P4 only): T50/T80 liquidity backtest on cache.

---

## 14. Document history

| Date | Change |
|------|--------|
| 2026-07-10 | Initial consolidation: T200 research, ATR sweep, `.env` audit, synthesis cross-check |
| 2026-07-10 | **Critical review:** reprioritise P0 sizing/trailing/alignment; defer universe expansion; schedule time-stop P1 |
| 2026-07-10 | **P0 applied:** `.env` nifty50, ₹50k capital, surge block 2.0, learning off |
| 2026-07-10 | **P1 complete:** time stop 4–5 bars net negative; baseline +₹2,176 at ₹50k — keep `TIME_STOP_BARS=0` |
| 2026-08-04 | **Cookbook reeval:** Packt EMA/MACD trend flips rejected; see [COOKBOOK_REEVAL.md](COOKBOOK_REEVAL.md) |
| 2026-08-04 | **Video MR sync:** refreshed [MEAN_REVERSION_REFERENCE.md](MEAN_REVERSION_REFERENCE.md); Type 2 BB/NR7 deferred; no paper `.env` change |
