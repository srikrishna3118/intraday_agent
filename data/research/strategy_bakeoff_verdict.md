# Strategy Bake-off Verdict

Window: 180d | Symbols: 30 | Data: cache | Engine: portfolio

Baseline (rsi_mr): net ₹-5,290 | Sharpe -2.655 | trades 146

Gates: net > baseline, Sharpe > baseline, trades ≥ 43 (30% of baseline), ≥50% rolling OOS folds positive

## Results

| Candidate | Trades | Net ₹ | Sharpe | OOS folds | Pass |
|-----------|--------|-------|--------|-----------|------|
| **rsi_mr_baseline** | 23 | ₹41 | 0.099 | — | control |
| **rsi_mr_paper_stack** | 23 | ₹41 | 0.099 | — | FAIL |
| **sbp_tm_short** | 484 | ₹-21,363 | -8.432 | — | FAIL |

## Decision

FAIL — no candidate beats baseline on all gates. Baseline rsi_mr: net ₹41, Sharpe 0.099, 23 trades. Keep current paper stack; shelve new entry strategies until exits/guards improve.
