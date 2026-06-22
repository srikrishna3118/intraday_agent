# Strategy Bake-off Verdict

Window: 180d | Symbols: 30 | Data: cache | Engine: portfolio

Baseline (rsi_mr): net ₹-5,290 | Sharpe -2.655 | trades 146

Gates: net > baseline, Sharpe > baseline, trades ≥ 43 (30% of baseline), ≥50% rolling OOS folds positive

## Results

| Candidate | Trades | Net ₹ | Sharpe | OOS folds | Pass |
|-----------|--------|-------|--------|-----------|------|
| **rsi_mr_baseline** | 98 | ₹-3,122 | -2.634 | — | control |
| **vst_ai** | 268 | ₹-12,261 | -9.419 | — | FAIL |
| **vst_ai_short** | 258 | ₹-11,877 | -9.263 | — | FAIL |

## Decision

FAIL — no candidate beats baseline on all gates. Baseline rsi_mr: net ₹-3,122, Sharpe -2.634, 98 trades. Keep current paper stack; shelve new entry strategies until exits/guards improve.
