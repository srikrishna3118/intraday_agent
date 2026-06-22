# Filter Ablation Backtests — rsi_mr (180d T2 portfolio)

Baseline reference: 142 trades, net ₹-4,789 (from loss decomposition run).

| Test | Trades | Gross ₹ | Costs ₹ | Net ₹ | Sharpe | Δ net vs baseline |
|------|--------|---------|---------|-------|--------|-------------------|
| Baseline (no filter) | 98 | 994 | 4,116 | **-3,122** | -2.634 | +1,667 |
| Test 6: pivot proximity (MR at S/R) | 64 | 1,091 | 2,688 | **-1,597** | -1.786 | +3,192 |
| Test 7: pivot zone (long below PP, short above) | 98 | 994 | 4,116 | **-3,122** | -2.634 | +1,667 |
| Test 8: pivot zone + proximity | 64 | 1,091 | 2,688 | **-1,597** | -1.786 | +3,192 |

## Interpretation

Best single filter: **Test 6: pivot proximity (MR at S/R)** — net ₹-1,597 (+1,525 vs baseline), 64 trades, Sharpe -1.786. All variants still net negative — filters may reduce damage but do not flip expectancy; ATR stop review remains next after confirming best filter stack in paper.
