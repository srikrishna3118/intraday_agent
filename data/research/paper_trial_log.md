# Paper Trial Log — Sprint 4 mean-exit stack

# Sprint 4 mean-exit stack: RSI>80, cutoff 14:00, denylist, pivot proximity, **mean exit (RSI 50, no trailing, ATR stop only when losing)**  
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

| Date | Day | Cycles | Entries | Exits | Paper gross ₹ | Notes |
|------|-----|--------|---------|-------|---------------|-------|
| 2026-06-22 | Mon | ~10 | 0 | 0 | ₹0 | Started 09:27; **power cut ~10:28** — old stack (ATR target 3.5). No entries. |
| 2026-06-19 | Thu | — | 3 | 3 | **+₹46** | SHORT NTPC +₹36 (2m trailing), BHARTIARTL +₹13 (2m trailing), ADANIENT −₹4 (2m trailing). DIVISLAB +₹31 manual exit. RSI 77–80, VolR 1.2–1.7. All AM entries. |
| 2026-06-23 | Mon | — | 3 | 3 | **−₹62** | SHORT DIVISLAB +₹4 (2m trailing), APOLLOHOSP +₹19 (87m trailing), CIPLA −₹84 (ATR stop, RSI 88.2, VolR 1.9 — trend continuation not reversal). |
| 2026-07-06 | Mon | ~full session | 2 | 2 | **+₹62** | Trailing stop exits at +0.25% — **old `.env`**. Fixed 2026-07-10: RSI-first, trailing off, ATR stop only underwater. |
| 2026-08-04 | Tue | ~29 scans | 0 | 0 | ₹0 | **Validated stack** (T2, ATR 1.25, cutoff 13:00, trailing off). 10:07–13:01; idle shutdown — no RSI>80 shorts. Peak RSI ~66 (JSWSTEEL); HDFCBANK oversold-only (longs disabled). |
| | | | | | | |
| | | | | | | |

## Running totals (paper sessions to date)

| Metric | Value |
|--------|-------|
| Sessions logged | 4 active (+ 1 aborted); **1 on validated stack (0 trades)** |
| Total trades | 9 |
| Win rate | 77.8% (7W / 2L) |
| Gross P&L | ₹+77 |
| Est. costs (₹42/trade) | ₹−378 |
| **Net P&L** | **₹−301** |
| Avg gross/trade | ₹+8.6 |
| Sim expectancy | ~₹20/trade net |
| Cost drag vs sim | Costs exceed gross — position sizes too small |

## Observations (as of 2026-07-10)

1. **Cost drag dominates**: avg ₹42/trade cost on notional ~₹5k–₹30k/trade. Net is negative even with 78% win rate.
2. **Reward:Risk is poor (0.54)**: avg win ₹23.5 vs avg loss ₹43.8 — high win rate required just to survive costs.
3. **Winners exited too early**: most trailing-stop exits at 2m with tiny gains. Two longest-held trades (137m, 157m) were the best performers.
4. **One outlier loss**: CIPLA (RSI 88.2, VolR 1.9) = −₹84, ATR stop hit — high RSI + very high volume was continuation, not exhaustion.
5. **All shorts**: short-only mode working as designed; no long signals triggered.

## Action items before promotion

- [ ] Increase position sizing so notional ≥ ₹50k/trade (reduce cost-as-% drag)
- [ ] Review trailing stop sensitivity — minimum hold time or wider initial stop to let winners run
- [ ] Consider filtering RSI > 86 entries (CIPLA pattern — extreme RSI with high volume = trend continuation risk)
- [ ] Log ≥2 more sessions to reach 5-session gate

## Promotion gates (paper → default)

- [ ] ≥5 weekdays logged *(3 active sessions so far)*
- [ ] Paper net not worse than sim by >20% per trade (~₹16/trade floor) — **currently failing** (net −₹301 due to small position sizes driving cost drag)
- [ ] Position sizing reviewed — notional ≥ ₹50k/trade before cost comparison is meaningful
- [ ] No unexpected pivot/screener data gaps
- [ ] User confirms before any live discussion

## Rollback (if paper underperforms)

```env
PIVOT_FILTER_ENABLED=false
ATR_TARGET_MULT=3.0
TRAILING_STOP_ENABLED=true
```

See `data/research/RESEARCH_HANDBOOK.md` and `PHASE4_FINDINGS.md` for full research trail. **Pending items:** [ROADMAP_STATUS.md](ROADMAP_STATUS.md).
