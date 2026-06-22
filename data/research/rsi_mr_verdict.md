# RSI MR Research Verdict

Symbols: 30 | Days: 180 | Data: cache | Engine: portfolio

## Q1 Rolling walk-forward
- Positive OOS folds: 1/1 (PASS)
- Full-period net: ₹-5,290 | Sharpe: -2.655

## Q3 Filter ablation (Sharpe primary)
- **base**: Sharpe -4.351 | net ₹-9,697 | trades 205
- **vix**: Sharpe -2.670 | net ₹-5,314 | trades 143
- **adx**: Sharpe -0.850 | net ₹-134 | trades 9
- **both**: Sharpe 0.669 | net ₹77 | trades 4
- Best ablation by Sharpe: **both**

## Q4 Sizing sweep (return-based Sharpe, formula costs)

## Decision

FAIL Q1 — stop entry research; revisit exits/guards or shelve MR.
