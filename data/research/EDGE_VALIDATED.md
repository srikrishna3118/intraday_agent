# Edge Found — Jul 10, 2026

**Status:** Sim edge **validated on T2** (30 liquid names). Paper P3 pending.

## Winner stack (applied to `.env`)

| Parameter | Value | Why |
|-----------|-------|-----|
| `SCAN_UNIVERSE` | **t2** | Full nifty50 net negative in sim (−₹228); edge is liquid-30 only |
| `CAPITAL_PER_TRADE` | **50000** | Costs <0.08% of notional |
| `ATR_STOP_MULT` | **1.25** | Tighter stop + RSI mean exit beats 1.5/2.0 on T2 |
| `ENTRY_CUTOFF_TIME` | **13:00** | No entries after 12:59 — morning session edge |
| `TRAILING_STOP_ENABLED` | false | Mean exit mode |
| `VOLUME_SURGE_BLOCK_MULT` | 2.0 | Sprint 5 (neutral on T2 but kept for safety) |
| `RSI_MOMENTUM_TRAP_RSI/VOLR` | 86 / 1.7 | CIPLA pattern guard |
| `LEARNING_ENABLED` | false | Until sim ↔ live aligned |
| `MAX_DAILY_LOSS/PROFIT` | 2000 / 3000 | Scaled for ₹50k |

## Performance (180d T2 cache, ₹50k)

| Metric | Base (ATR 1.5) | **Winner** |
|--------|----------------|------------|
| Net ₹ | 2,176 | **2,438** |
| Slippage net ₹ | 857 | **1,168** |
| Sharpe | 1.34 | **1.49** |
| Trades | 27 | 26 |
| ATR stops | 7 | 8 |
| RSI exits | 12 | 12 |
| edge_pass | ✓ | ✓ |

Gate: net > 0, trades ≥ 10, Sharpe > 0.5, slippage stress net > 0.

## What failed (do not deploy)

| Variant | Net ₹ | Note |
|---------|-------|------|
| Time stop 4–5 bars | −1,656 to −1,703 | Cuts winners before RSI 50 |
| Full Nifty 50 (winner stack) | −228 | Mid-cap noise dilutes |
| Clear denylist | −86 slip | ONGC/SBIN/BAJFINANCE exclusion helps |
| RSI_OB 82+ | ≤30 net | Over-filters |
| ATR 2.0 only | +1,446 | Worse than 1.25 |

## Phase status

| Phase | Status |
|-------|--------|
| P0 | ✅ Applied |
| P1 | ✅ Time stop rejected |
| P2 | ✅ Entry sweep — hour13 + ATR 1.25 win; surge/trap neutral on T2 |
| P3 | ⏳ Paper — run `python run_agent.py` on market days; need ≥15 sessions |
| P4 | ✅ Tested nifty50 — **deferred**; do not expand live scan beyond t2 |

## Commands

```bash
# Re-run full search
python tools/edge_search.py --tier t2 --rounds 2 --universe-test --capital 50000

# Paper agent (next market session)
python run_agent.py
python tools/status.py
```

Artifacts: [EDGE_SEARCH.md](EDGE_SEARCH.md), [edge_search.json](edge_search.json)
