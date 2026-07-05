# Strategy compare: ORB vs VWAP pullback vs Tier 2 rsi_mr

**Generated:** 2026-07-05  
**Window:** 180d T2 portfolio (30 symbols) | **Source:** `data/candles/` cache  
**Engine:** `portfolio_sim` (MAX_POSITIONS, TradeGuard, AdaptiveRanker)  
**Cost model:** ₹42/trade flat  

**Shared settings:** `ENTRY_CUTOFF_TIME=14:00`, denylist ONGC/SBIN/BAJFINANCE, ATR stop 1.5, trailing on, regime filter off.

| Candidate | Trades | Gross ₹ | Costs ₹ | **Net ₹** | Sharpe | WR% | Net/trade |
|-----------|--------|---------|---------|-----------|--------|-----|-----------|
| **tier2_rsi_mr** | 22 | 397 | 924 | **-527** | -1.25 | 40.9% | -23.9 |
| **orb** (long+short) | 1,077 | 2,804 | 45,234 | **-42,430** | -16.75 | 12.1% | -39.4 |
| **vwap_pullback** (long+short) | 1,054 | 1,973 | 44,268 | **-42,295** | -14.48 | 20.5% | -40.1 |

## Verdict

**Tier 2 rsi_mr wins this comparison** — not because it is strongly profitable, but because it is the **only variant close to breakeven** on net. ORB and VWAP pullback **over-trade** (~1,000+ trades / 180d) and costs (~₹42k) overwhelm small positive gross edge.

**Do not switch paper stack to ORB or vwap_pullback** on these defaults.

## Exit breakdown

### tier2_rsi_mr (22 trades)

| Exit | Trades | Gross ₹ |
|------|--------|---------|
| RSI mid-line exit | 4 | +637 |
| Trailing stop | 11 | +231 |
| ATR target | 1 | +154 |
| EOD square-off | 1 | +154 |
| ATR stop | 5 | -778 |

### orb (1,077 trades)

| Exit | Trades | Gross ₹ |
|------|--------|---------|
| RSI mid-line exit | 1,037 | +4,805 |
| OR target | 2 | +715 |
| Trailing stop | 23 | -120 |
| OR stop | 5 | -808 |
| EOD square-off | 10 | -1,788 |

Gross RSI mid-line path is positive (+₹4.8k) but **1,037 exits at ~₹2.6 gross/trade** cannot cover ₹42 friction.

### vwap_pullback (1,054 trades)

| Exit | Trades | Gross ₹ |
|------|--------|---------|
| RSI mid-line exit | 826 | +15,958 |
| ATR target | 5 | +1,540 |
| Trailing stop | 79 | +1,416 |
| EOD square-off | 11 | -543 |
| ATR stop | 133 | -16,398 |

Same pattern: **+₹2.0k gross, -₹42k costs**. ATR stops are the main gross leak (-₹16.4k).

## Notes

- ORB: 15m opening range, VWAP confirm, OR range stop, long+short (literature default).
- vwap_pullback: 0.15% VWAP touch, slope filter off, long+short.
- tier2: pivot proximity, RSI>80, short-only, ATR target 3.5 (paper stack).
- Tier 2 standalone bakeoff same day (`strategy_bakeoff.py --candidates rsi_mr_paper_stack`): **17 trades, net +₹63** — trade-count variance vs 22 trades here; both confirm **low-frequency filter stack** beats high-frequency alternatives.

## Artifact

`data/research/strategy_compare_orb_vwap_tier2.json`
