# RSI MR Research Verdict

Symbols: 30 | Days: 180 | Data: cache | Engine: portfolio

## Q1 Rolling walk-forward
- Positive OOS folds: None/None (FAIL)
- Full-period net: ₹-4,912 | Sharpe: -2.515

## Q3 Filter ablation (Sharpe primary)
- **base**: Sharpe -4.083 | net ₹-8,768 | trades 202
- **vix**: Sharpe -2.515 | net ₹-4,912 | trades 142
- **adx**: Sharpe -0.850 | net ₹-134 | trades 9
- **both**: Sharpe 0.669 | net ₹77 | trades 4
- **adx_band_12_18**: Sharpe 1.815 | net ₹217 | trades 5
- **adx_band_10_15**: Sharpe 0.000 | net ₹0 | trades 0
- **adx_band_15_20**: Sharpe -0.850 | net ₹-134 | trades 9
- **both_band_12_18**: Sharpe 1.059 | net ₹29 | trades 2
- Best ablation by Sharpe: **adx_band_12_18**

## Q4 Sizing sweep (return-based Sharpe, formula costs)

## Decision

FAIL Q1 — stop entry research; revisit exits/guards or shelve MR.
