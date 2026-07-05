# Paper Trial Log — Sprint 4 mean-exit stack

**Stack:** rsi_mr short-only · RSI>80 · hour<14 · denylist · pivot proximity · ATR stop 1.5 · **mean exit (RSI 50, no ATR target, trailing off)**  
**Sim reference (180d T2, Sprint 4):** 17 trades · gross ₹1,061 · net **+₹347** · Sharpe **1.024** · slippage stress **+₹113**  
**Expectancy hint:** ~₹20/trade net before paper drift (~1 trade / 10.5 days on T2)

**Sprint 4 decision (2026-07-05):** Mean RSI exit beats ATR target 3.5 control (+₹63). VWAP exit rejected (−₹753). `.env.example` updated.

**Session paused:** 2026-06-22 EOD — resume next market open ~09:15 IST.

Run each market day (09:15–15:30 IST):

```bash
python run_agent.py
python tools/status.py   # optional health check
```

Copy a row per session below. After **5–10 sessions**, compare total paper net vs sim expectancy (~₹20/trade).

| Date | Day | Cycles | Entries | Exits | Paper net ₹ | Notes |
|------|-----|--------|---------|-------|-------------|-------|
| 2026-06-22 | Mon | ~10 | 0 | 0 | ₹0 | Started 09:27; **power cut ~10:28** — old stack (ATR target 3.5). No entries. |
| | Mon–Fri | | | | | *Resume with Sprint 4 mean-exit stack* |
| | | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |

## Promotion gates (paper → default)

- [ ] ≥5 weekdays logged
- [ ] Paper net not worse than sim by >20% per trade (~₹16/trade floor)
- [ ] No unexpected pivot/screener data gaps
- [ ] User confirms before any live discussion

## Rollback (if paper underperforms)

```env
PIVOT_FILTER_ENABLED=false
ATR_TARGET_MULT=3.0
TRAILING_STOP_ENABLED=true
```

See `data/research/RESEARCH_HANDBOOK.md` and `PHASE4_FINDINGS.md` for full research trail.
