# Strategy Bake-off Verdict

Window: 180d | Symbols: 76 | Data: cache | Engine: portfolio

Baseline (rsi_mr): net ₹-5,290 | Sharpe -2.655 | trades 146

Gates: net > baseline, Sharpe > baseline, trades ≥ 43 (30% of baseline), ≥50% rolling OOS folds positive

## Results

| Candidate | Trades | Net ₹ | Sharpe | OOS folds | Pass |
|-----------|--------|-------|--------|-----------|------|
| **rsi_mr_paper_stack** | 50 | ₹611 | 0.674 | — | PASS |
| **quadapt_ml_consensus** | 29 | ₹-1,811 | -2.984 | — | FAIL |
| **quadapt_ml_short** | 7 | ₹-984 | -1.925 | — | FAIL |

## Decision

PASS — **rsi_mr_paper_stack** (rsi_mr) net ₹611, Sharpe 0.674, 50 trades. Paper-test only; do not enable live without walk-forward on paper journal.
