# Strategy Bake-off Verdict

Window: 180d | Symbols: 30 | Data: cache | Engine: portfolio

Baseline (rsi_mr): net ₹-5,290 | Sharpe -2.655 | trades 146

Gates: net > baseline, Sharpe > baseline, trades ≥ 43 (30% of baseline), ≥50% rolling OOS folds positive

## Results

| Candidate | Trades | Net ₹ | Sharpe | OOS folds | Pass |
|-----------|--------|-------|--------|-----------|------|
| **rsi_mr_baseline** | 102 | ₹-3,387 | -2.770 | — | control |
| **zp_dmi** | 159 | ₹-6,788 | -8.473 | — | FAIL |
| **zp_dmi_short** | 149 | ₹-6,302 | -8.134 | — | FAIL |

## Decision

FAIL — no candidate beats baseline on all gates. Baseline rsi_mr: net ₹-3,387, Sharpe -2.770, 102 trades. Keep current paper stack; shelve new entry strategies until exits/guards improve.
