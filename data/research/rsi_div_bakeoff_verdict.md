# Strategy Bake-off Verdict

Window: 180d | Symbols: 30 | Data: cache | Engine: portfolio

Baseline (rsi_mr): net ₹-5,290 | Sharpe -2.655 | trades 146

Gates: net > baseline, Sharpe > baseline, trades ≥ 43 (30% of baseline), ≥50% rolling OOS folds positive

## Results

| Candidate | Trades | Net ₹ | Sharpe | OOS folds | Pass |
|-----------|--------|-------|--------|-----------|------|
| **rsi_mr_baseline** | 110 | ₹-3,197 | -2.634 | — | control |
| **rsi_div** | 119 | ₹-5,029 | -4.407 | — | FAIL |
| **rsi_div_short** | 119 | ₹-5,029 | -4.407 | — | FAIL |

## Decision

FAIL — no candidate beats baseline on all gates. Baseline rsi_mr: net ₹-3,197, Sharpe -2.634, 110 trades. Keep current paper stack; shelve new entry strategies until exits/guards improve.
