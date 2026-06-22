# Filter Ablation Backtests — rsi_mr (180d T2 portfolio)

Baseline reference: 142 trades, net ₹-4,789 (from loss decomposition run).

| Test | Trades | Gross ₹ | Costs ₹ | Net ₹ | Sharpe | Δ net vs baseline |
|------|--------|---------|---------|-------|--------|-------------------|
| Baseline (no filter) | 98 | 994 | 4,116 | **-3,122** | -2.634 | +1,667 |
| Test 1: entry hour < 14 IST | 91 | 852 | 3,822 | **-2,970** | -2.528 | +1,819 |
| Test 2: RSI > 80 | 43 | 1,082 | 1,806 | **-724** | -0.895 | +4,065 |
| Test 6: pivot proximity (MR at S/R) | 64 | 1,091 | 2,688 | **-1,597** | -1.786 | +3,192 |
| Test 9: hour<14 AND RSI>80 AND pivot proximity | 22 | 791 | 924 | **-133** | -0.308 | +4,656 |

## Interpretation

Best single filter: **Test 9: hour<14 AND RSI>80 AND pivot proximity** — net ₹-133 (+2,989 vs baseline), 22 trades, Sharpe -0.308. All variants still net negative — filters may reduce damage but do not flip expectancy; ATR stop review remains next after confirming best filter stack in paper.
