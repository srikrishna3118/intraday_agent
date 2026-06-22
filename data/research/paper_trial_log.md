# Paper Trial Log — Phase 3 (pivot + Test 9 stack)

**Stack:** rsi_mr short-only · RSI>80 · hour<14 · denylist · pivot proximity · ATR stop 1.5 / target 3.5  
**Sim reference (180d T2):** 21 trades · gross ₹927 · net **+₹45** · Sharpe 0.11  
**Expectancy hint:** ~₹2/trade net before paper drift  

**Session paused:** 2026-06-20 — resumed **2026-06-22 09:27 IST** (Tier 2 continuous loop).

Run each market day (09:15–15:30 IST):

```bash
python run_agent.py
python tools/status.py   # optional health check
```

Copy a row per session below. After **5–10 sessions**, compare total paper net vs sim expectancy.

| Date | Day | Cycles | Entries | Exits | Paper net ₹ | Notes |
|------|-----|--------|---------|-------|-------------|-------|
| 2026-06-22 | Mon | 1+ (running) | 0 | 0 | — | **Started 09:27 IST** — PAPER loop PID 1518342; Yahoo 49/49; cycle 1: 0 signals (best RSI CIPLA 81.4, below pivot/vol gate). *Update EOD.* |
| | Mon–Fri | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |

## Promotion gates (paper → default)

- [ ] ≥5 weekdays logged
- [ ] Paper net not worse than sim by >20% per trade
- [ ] No unexpected pivot/screener data gaps
- [ ] User confirms before any live discussion

## Rollback (if paper underperforms)

```env
PIVOT_FILTER_ENABLED=false
ATR_TARGET_MULT=3.0
```

See `data/research/PHASE_FINDINGS.md` for full research trail.
