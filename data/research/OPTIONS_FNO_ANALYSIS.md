# NIFTY Intraday Options — Analysis and Validation Plan

**Date:** 2026-09-27  
**Status:** Paper-only research track. Live NFO orders remain blocked.  
**Capital assumption:** under ₹2L, **1 lot**, every short leg hedged.  
**Data:** Angel SmartAPI only.

This note is the source of truth for the F&O paper scaffold. Equity `rsi_mr` remains the primary validated paper path. Options sit beside it, not instead of it.

---

## 1. Verdict

The repo already has a **paper NIFTY F&O path** (`--mode fno` / `--mode both`). It is a clock-based ATM short straddle that becomes an iron fly when wings are on. Live placement is refused.

Public **intraday** evidence supports selling same-session premium more than buying options on EMA signals. The 9:20 ATM straddle still shows a residual edge after costs, concentrated on **expiry-day sessions** and sessions **two days before expiry**. At 1 lot the ₹20/order stack eats most of that edge, so 2-leg defined-risk arms are the only structures that can survive this account size.

Nothing in this track goes live. A strategy is only allowed to continue to a replay study after **≥40 paper sessions** and the gates in §7.

---

## 2. What exists today

Default runtime is equity MIS (`AGENT_MODE=equity`). Options are a parallel paper stack.

| Layer | File | Behavior |
|-------|------|----------|
| Entry | `run_agent.py` | `--mode equity\|fno\|both` |
| Loop | `intraday_agent/agent_fno.py` | Multi-arm paper loop, slot grace, 15:10 exit, IV snapshots, capture hook |
| Strategies | `intraday_agent/strategy_fno.py` | Five pre-registered intraday arms |
| Instruments | `intraday_agent/instruments_fno.py` | NFO `OPTIDX` CE/PE, nearest expiry, `trading_dte` |
| Orders | `intraday_agent/orders_fno.py` | Multi-leg paper, side-group exits, persist/restore, live blocked |
| Costs | `intraday_agent/learning/costs.py` | F&O formula on `legs_json` rows |
| Journal | `intraday_agent/learning/journal.py` | `paper_fno` + `entry_features` + `legs_json` |

Equity `broker.place_order` still hardcodes **NSE + INTRADAY**. It cannot place NFO orders.

---

## 3. Intraday session rules (2026)

- NSE closing auction (CAS) started **3 Aug 2026**. F&O-list stocks stop continuous trading at 15:15; the NIFTY print is frozen until auction prices appear around 15:35. F&O contracts trade until **15:40**.
- Angel auto-squares-off **F&O MIS at 15:20** and **equity MIS at 15:10**.
- All F&O arms exit at **15:10**, before the index freeze and before Angel F&O auto square-off.
- Equity agent `SQUARE_OFF_TIME=15:15` is now **after** Angel's equity cutoff. Logged as an open item on [ROADMAP_STATUS.md](ROADMAP_STATUS.md); not changed here.
- Weekly NIFTY expiry is **Tuesday**. Lot size **65** since 31 Dec 2025 (read from scrip master).
- STT **0.15%** on sold premium since 1 Apr 2026. NSE option transaction charge **0.03553%** of premium since 1 Mar 2026.

**Intraday rule:** every strategy opens and closes the same session. No entries after **14:30**. Nothing is held overnight or to expiry. "Expiry-cycle day" only labels which weekday an **intraday** trade happens on:

| Cycle day | Weekday (Tuesday expiry) |
|-----------|--------------------------|
| 0 | Tuesday (expiry) |
| 1 | Monday |
| 2 | Friday |
| 3 | Thursday |
| 4 | Wednesday |

---

## 4. Intraday evidence ranking

### Strongest (intraday, net of costs or walk-forward OOS)

| Setup | Source | What it showed |
|-------|--------|----------------|
| 9:20 ATM straddle, 20% per-leg SL, same-day exit | [Zerodha, Seven Years of the 9:20 Straddle](https://inthemoneybyzerodha.substack.com/p/seven-years-of-the-920-straddle-past) (2019–2025) | Still positive in 2025, weaker. Profits on 0 DTE and 2 DTE sessions; 3–4 DTE sessions lost. Not viable at ≤5 lots after ₹20/order. |
| Premium-range short (₹200 option, 9:15–11:15 range, sell on close below range) | [Zerodha, ORB with NIFTY options](https://inthemoneybyzerodha.substack.com/p/how-to-trade-opening-range-breakout) (2022–Feb 2026, net) | Every year positive; ~6% max DD. Buying mirror ~45% DD. |
| Expiry-day remaining-vol model (11:00 → 14:30) | [nifty-0dte-vrp](https://github.com/aprameyap/nifty-0dte-vrp) | Walk-forward OOS R² 0.39 on 313 NIFTY expiry days (2019–2025). Forecasts overshoot realized move. Costs not modelled. |
| 9:20 ~₹30 strangle, 0–1 DTE only | [Walk-forward study](https://financewithsai.com/walk-forward-backtesting-vs-direct-optimization-a-complete-guide-with-nifty-9-20-straddle-strategy/) | All OOS quarters 2020–2023 profitable. Assumes **zero brokerage**. |

### Mechanism (to measure, not to assume)

ATM IV is highest at the open and typically falls through 09:20–10:00. Same-day decay is slow mid-week and steep on expiry-day afternoons. The agent snapshots ATM IV every 15 minutes to test this on Angel data.

### Base rates

- SEBI FY26: option sellers were the only retail group with positive median returns; ~97% of retail mainly buy options ([SEBI](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787236407005.pdf)).
- US 0DTE: short straddles/strangles net Sharpe ~0.39; iron flies/condors turn **negative after costs** ([Vilkov](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4641356)).

### Weak or negative (intraday)

| Idea | Why it is not a primary arm |
|------|-----------------------------|
| VWAP on straddle premium | ~4%/yr before slippage; negative after |
| EMA crossovers as a trade trigger | 31–41% win rate on NIFTY; this repo already killed ORB/VWAP trend flips on equity |
| Expiry-day option buying | ~10% of days pay for the rest; 2025 reports of no profit after SEBI changes |
| Opening-range breakout | Edge dies once realistic slippage is added |
| First-half-hour momentum (Gao et al. 2018) | US evidence; pays in the last half-hour, which is **after** the 15:10 exit |

### Dropped (multi-day, not intraday)

India VIX vs daily realized vol; Garg & Vipul daily premium study; VIX-percentile gate from weekly holds.

---

## 5. Cost hurdle at 1 lot

Per completed **intraday** round-trip (₹20/order, 0.15% STT on sells, 0.03553% exchange, SEBI ₹10/crore, 0.003% stamp on buys, 18% GST, 0.25% slippage):

| Structure | Legs | Approx. all-in ₹ |
|-----------|------|------------------|
| Iron fly | 4 | ~295 |
| 2-leg credit spread | 2 | ~150–235 |
| Single long option | 1 | ~145 |

A daily iron fly spends ~**37% of ₹2L per year** on costs before it earns anything. That is why the 2-leg arms exist.

The journal now costs every `legs_json` row with the F&O formula (`cost_model=fno_formula`), not the equity ₹42/leg flat.

---

## 6. Scaffold gaps found (and the fix)

| Gap | Fix |
|-----|-----|
| `FNO_WEEKLY_ONLY` skipped the monthly contract in the last week of the month | `nearest_expiry()` returns the nearest listed expiry (weekly or monthly) |
| One short-leg stop closed the whole iron fly | Side-group exits: only that side's short + wing close |
| Slot fired only on the exact minute | 2-minute grace window |
| No common entry cutoff | `FNO_ENTRY_CUTOFF=14:30` |
| Equity cost model on F&O rows | `fno_leg_cost()` |
| Heuristic margin only | Angel `getMarginApi` basket vs `FNO_CAPITAL` |
| No entry context | `entry_features` JSON (cycle day, VIX, EMA, ATM premium, ATM IV, basket margin) |
| Off-hours paper row at 22:29 | Report excludes entries outside 09:15–15:30 IST |
| Open paper legs lived only in memory | `data/fno_open_positions.json`; same-day restore; stale prior-day close as `restart_stale` |
| F&O could not share an Angel session with equity | `run_agent.py --mode both` + `intraday_agent/runner.py` |

---

## 7. Pre-registered paper arms

Shared: nearest NIFTY expiry, 1 lot, 200-pt wings on every short, product INTRADAY, entries 09:16–14:30, hard exit 15:10 unless noted. **No tuning during the trial.**

| Key | Recorded name | Rules |
|-----|---------------|-------|
| `time_based_straddle` | `time_based_iron_fly` when wings > 0 | 09:20 sell ATM CE+PE, buy ±200 wings. 20% short-leg rise closes **that side**. Other side to 15:10. |
| `ema920_credit_spread` | same | 09:20, completed 09:15 5-min bar. Bull stack (`close > EMA9 > EMA21`) → short ATM PE + long PE−200. Bear stack → short ATM CE + long CE+200. Neutral → skip. 20% short-leg rise closes the pair. |
| `ema920_option_buy` | same | Same signal. Buy the signal-side option with premium nearest ₹200. Exit on 20% drop or 15:10. |
| `premium_orb_short` | same | 09:16 pick CE and PE nearest ₹200. Range = 5-min high/low 09:15–11:15. After 11:15, 5-min close below range low → sell that option + buy 200 pts further OTM. One entry per side. 20% rise closes the pair. |
| `expiry_vol_strangle` | same | **Expiry day only.** 11:00 forecast remaining move to 14:30. Sell CE+PE at calibrated 10% tail (floor 0.4% of spot) + 200-pt wings. 50% short-leg rise closes that side. Exit 14:30. |

### Spot-study premises (must pass before trusting the matching arms)

1. **EMA premise** (arms 2 and 3): mean 09:20→15:10 return in the predicted direction > 0, bootstrap 95% lower bound > 0, and positive in both chronological halves. Artifact: [fno_signal_study.md](fno_signal_study.md).
2. **Expiry-vol premise** (arm 5): walk-forward OOS R² ≥ 0.2 and OOS breach rate at the 10% tail ≤ 12%. Thursday-expiry era (through 28 Aug 2025) and Tuesday era (from 2 Sep 2025) reported separately. Model: `data/models/fno_expiry_vol.json`.

**Spot-study result (Angel 5-min, 2023-09-28 → 2026-09-25, 743 sessions):** both premises **FAIL**. EMA n=519, mean +1.1 bps, bootstrap 95% LB −3 bps, first half negative. Expiry model n=149, walk-forward OOS R² **0.28** (gate pass) but 10% tail breach **18%** (gate fail). In-sample remaining-RV R² 0.37. Tuesday-era OOS R² 0.44 vs Thursday-era 0.15. Arms 2, 3 and 5 still run in paper so the 40-session journal can confirm; they are not eligible to CONTINUE on premise grounds. Details: [fno_signal_study.md](fno_signal_study.md).

### Paper gates at ≥40 sessions

**KILL** an arm if any of:

- net P&L after F&O costs ≤ 0
- net negative in either chronological half
- max drawdown > ₹20,000 (10% of ₹2L)

Arms 2 and 3 also need the EMA premise. Arm 5 also needs the expiry-vol premise (it trades ~8 times in 8 weeks, so the 3-year spot test carries most of the verdict).

Otherwise **CONTINUE** to a replay study on captured 1-min candles. **No arm goes live from this note.**

---

## 8. How to run

```bash
# Weekend spot study (3y Angel 5-min)
CANDLE_HISTORY_CHUNK_DAYS=90 python tools/fetch_history.py --index NIFTY,INDIAVIX --interval FIVE_MINUTE --days 1095 --source angel
python tools/fetch_history.py --index INDIAVIX --interval ONE_DAY --days 1500 --source angel
python tools/fno_signal_study.py

# Weekday paper (equity + five F&O arms, one Angel login)
python run_agent.py --mode both

# Report
python tools/report_journal.py --source paper_fno --since 2026-09-28
python tools/fno_smoke_test.py
```

Session log: [fno_paper_trial_log.md](fno_paper_trial_log.md).

`.env` should match the researched clock (`FNO_ENTRY_TIMES=09:20`, `FNO_COMBINED_STOP_LOSS_PCT=0`). `.env.example` already has those values; do not commit `.env`.

---

## 9. Out of scope

- Live NFO `place_order` / NRML product wiring
- Naked short options
- Non-Angel data vendors (Breeze, Dhan)
- Replay backtester on captured candles (next phase, after ≥40 captured sessions)
- Changing equity strategy defaults, including `SQUARE_OFF_TIME`
- Last-half-hour trades (after 15:10)
