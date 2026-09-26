# NIFTY F&O paper trial log

**Started:** 2026-09-27  
**Mode:** paper only (`LIVE_TRADING=false`). Live NFO stays blocked.  
**Capital:** ₹2L, 1 lot, every short hedged.  
**Runner:** `python run_agent.py --mode both` (one Angel login; equity paper + five F&O arms).

Verdict source of truth: [OPTIONS_FNO_ANALYSIS.md](OPTIONS_FNO_ANALYSIS.md).  
Spot-study artifact: [fno_signal_study.md](fno_signal_study.md).

---

## Run steps

```bash
# 1. Spot history (Angel only)
CANDLE_HISTORY_CHUNK_DAYS=90 python tools/fetch_history.py --index NIFTY,INDIAVIX --interval FIVE_MINUTE --days 1095 --source angel
python tools/fetch_history.py --index INDIAVIX --interval ONE_DAY --days 1500 --source angel

# 2. EMA premise + expiry remaining-vol model
python tools/fno_signal_study.py

# 3. Scaffold / cost / restore checks (no login)
python tools/fno_smoke_test.py --offline

# 4. Live probe + two-contract capture (login, no orders)
python tools/fno_smoke_test.py --skip-candles

# 5. Daily after 15:10 (or backfill a live contract)
python tools/capture_fno_candles.py --session 2026-09-25

# 6. Combined paper loop on a session day
python run_agent.py --mode both

# 7. Report (excludes off-hours and restart_stale)
python tools/report_journal.py --source paper_fno --since 2026-09-28
```

Your `.env` should match `.env.example` on `FNO_ENTRY_TIMES=09:20` and `FNO_COMBINED_STOP_LOSS_PCT=0`. This file does not edit `.env`.

---

## Shared session rules

- Entries 09:16–14:30. Hard flat 15:10 (arm 5 at 14:30).
- Nearest listed NIFTY expiry (weekly or monthly). 200-pt wings on every short.
- Per-arm `TradeGuard` with `FNO_MAX_DAILY_LOSS=20000`, no symbol cooldown.
- Open paper legs persist in `data/fno_open_positions.json`. A prior-day leftover is closed as `restart_stale` and excluded from the verdict.

---

## Gates (read after ≥40 sessions, ~8 weeks)

Per arm, **KILL** if any of:

1. Net P&L after the F&O cost formula ≤ 0.
2. Net P&L negative in either chronological half of the paper sample.
3. Max net drawdown > ₹20,000.

Plus premises from the spot study:

| Arm | Extra gate |
|-----|------------|
| `ema920_credit_spread` | EMA 09:20→15:10 premise PASS |
| `ema920_option_buy` | EMA 09:20→15:10 premise PASS |
| `expiry_vol_strangle` | Expiry-model OOS R² ≥ 0.2 and 10% tail breach ≤ 12% (small n; lean on the 3-year test) |

No arm goes live from this trial. A CONTINUE arm is only eligible for a later replay on captured 1-min data.

---

## Session ledger

| Date | Runner | Arms that traded | Notes |
|------|--------|------------------|-------|
| 2026-09-27 (Sun) | implementation, `fno_smoke_test.py`, `fno_signal_study.py` | — | Market closed. Spot study: EMA FAIL (n=519, +1.1 bps, LB<0); expiry-vol FAIL (OOS R² 0.28, tail breach 18%). `--mode both --once` prints market closed. First combined paper session: Mon 2026-09-28. |
| 2026-09-25 (Fri) | `capture_fno_candles.py --session 2026-09-25` | — | 38 NFO 1-min series + NIFTY 1-min for range 23021–23163 ±400, expiry 2026-09-29. IV snapshot empty after hours. |

Add one row per weekday after the close: net by arm, capture file counts, and any `restart_stale` or off-hours rows (those do not count).
