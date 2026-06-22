# Loss Decomposition — rsi_mr baseline (180d T2 portfolio)

Strategy: `rsi_mr` | Trades: 142 | Gross: ₹1,175 | Costs: ₹5,964 | **Net: ₹-4,789** | Sharpe: -2.432

## Where the loss comes from

Gross edge is **positive** (+₹1,175) but **costs (₹5,964) exceed gross by ₹4,789** — the strategy is not losing on price action alone; friction dominates. Largest symbol drag: **ONGC** (10 trades, net ₹-1,014). Worst entry hour: **14:00 IST** (20 trades, net ₹-1,905). Largest exit leak: **ATR stop** (49 trades, net ₹-9,342). Best exit path: **ATR target** (15 trades, net +₹2,975). Best symbol pocket: **MARUTI** — 6 trades, net +₹443.

## P&L waterfall

| Layer | ₹ | Share of net loss |
|-------|---|-------------------|
| Gross P&L (price) | 1,175 | 24.5% |
| Estimated costs | -5,964 | 124.5% |
| Net P&L | -4,789 | 100.0% |

## Symbol attribution (all symbols)

| symbol | Trades | Win% | Gross ₹ | Costs ₹ | Net ₹ |
|-------|--------|------|---------|---------|-------|
| TCS † | 3 | 100.0 | 988 | 126 | **862** |
| MARUTI | 6 | 83.3 | 695 | 252 | **443** |
| RELIANCE † | 4 | 100.0 | 517 | 168 | **349** |
| M&M | 9 | 66.7 | 534 | 378 | **156** |
| ASIANPAINT † | 4 | 100.0 | 321 | 168 | **153** |
| JSWSTEEL † | 2 | 50.0 | 187 | 84 | **103** |
| TATACONSUM † | 3 | 66.7 | 182 | 126 | **56** |
| NTPC | 8 | 62.5 | 374 | 336 | **38** |
| SUNPHARMA † | 4 | 75.0 | 190 | 168 | **22** |
| WIPRO † | 3 | 100.0 | 123 | 126 | **-3** |
| KOTAKBANK † | 4 | 50.0 | 50 | 168 | **-118** |
| ULTRACEMCO | 5 | 80.0 | 53 | 210 | **-157** |
| INFY † | 3 | 33.3 | -102 | 126 | **-228** |
| HDFCBANK † | 2 | 50.0 | -294 | 84 | **-378** |
| LT | 6 | 33.3 | -151 | 252 | **-403** |
| COALINDIA | 12 | 50.0 | 87 | 504 | **-417** |
| TATASTEEL | 6 | 33.3 | -195 | 252 | **-447** |
| ITC | 5 | 60.0 | -292 | 210 | **-502** |
| POWERGRID | 5 | 40.0 | -308 | 210 | **-518** |
| TECHM | 10 | 40.0 | -153 | 420 | **-573** |
| INDUSINDBK | 8 | 37.5 | -324 | 336 | **-660** |
| SBIN | 14 | 50.0 | -109 | 588 | **-697** |
| BAJFINANCE | 6 | 50.0 | -603 | 252 | **-855** |
| ONGC | 10 | 30.0 | -594 | 420 | **-1,014** |

† fewer than min-segment trades — interpret with caution

## Hour-of-day attribution (entry IST)

| hour_label | Trades | Win% | Gross ₹ | Costs ₹ | Net ₹ |
|-------|--------|------|---------|---------|-------|
| 16:00 IST † | 1 | 100.0 | 34 | 42 | **-8** |
| 15:00 IST † | 3 | 66.7 | -69 | 126 | **-195** |
| 11:00 IST | 13 | 61.5 | 207 | 546 | **-339** |
| 12:00 IST | 14 | 64.3 | 237 | 588 | **-351** |
| 10:00 IST | 37 | 54.1 | 942 | 1,554 | **-612** |
| 09:00 IST | 42 | 61.9 | 1,093 | 1,764 | **-671** |
| 13:00 IST | 12 | 41.7 | -202 | 504 | **-706** |
| 14:00 IST | 20 | 40.0 | -1,065 | 840 | **-1,905** |

† fewer than min-segment trades — interpret with caution

## Exit reason attribution (grouped)

| exit_family | Trades | Win% | Gross ₹ | Costs ₹ | Net ₹ |
|-------|--------|------|---------|---------|-------|
| ATR target | 15 | 100.0 | 3,605 | 630 | **2,975** |
| RSI mid-line exit | 22 | 100.0 | 3,154 | 924 | **2,230** |
| trailing stop | 56 | 75.0 | 1,700 | 2,352 | **-652** |
| ATR stop | 49 | 0.0 | -7,284 | 2,058 | **-9,342** |

† fewer than min-segment trades — interpret with caution

## RSI bucket at entry

| rsi_bucket | Trades | Win% | Gross ₹ | Costs ₹ | Net ₹ |
|-------|--------|------|---------|---------|-------|
| short_rsi_>80 | 46 | 56.5 | 1,695 | 1,932 | **-237** |
| short_rsi_75-80 | 96 | 55.2 | -520 | 4,032 | **-4,552** |

† fewer than min-segment trades — interpret with caution

## Volume ratio at entry

| volume_bucket | Trades | Win% | Gross ₹ | Costs ₹ | Net ₹ |
|-------|--------|------|---------|---------|-------|
| vol_1.2-1.5x | 59 | 62.7 | 1,109 | 2,478 | **-1,369** |
| vol_1.5-2x | 83 | 50.6 | 66 | 3,486 | **-3,420** |

† fewer than min-segment trades — interpret with caution

## Edge pockets (net positive, ≥ min trades)

| Segment | Type | Trades | Net ₹ |
|---------|------|--------|-------|
| MARUTI | symbol | 6 | **443** |
| M&M | symbol | 9 | **156** |
| NTPC | symbol | 8 | **38** |

## Recommended focus

1. **Cut trade count** in worst hours/symbols before tuning RSI — costs scale linearly per trade.
2. **Review or exclude** chronic losers: ONGC, BAJFINANCE, SBIN.
3. **Time filter**: block or reduce size for entries at 14:00 IST, 13:00 IST.
4. **Exit review**: losses concentrate in ATR stop, trailing stop — tighten stops or skip weak entries.
5. **Keep winners working**: ATR target (+₹2,975 net) — don't cut this exit path while fixing stops.
6. **Entry filter test**: `short_rsi_75-80` (96 trades, ₹-4,552) — paper-block before any new strategy.
Do not add strategy #6 until gross/net per trade improves after symbol+time filters.
