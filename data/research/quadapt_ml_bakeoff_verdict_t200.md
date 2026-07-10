# Strategy Bake-off Verdict

Window: 180d | Symbols: 200 | Data: cache | Engine: portfolio

Baseline (rsi_mr): net ₹-5,290 | Sharpe -2.655 | trades 146

Gates: net > baseline, Sharpe > baseline, trades ≥ 43 (30% of baseline), ≥50% rolling OOS folds positive

## Results

| Candidate | Trades | Net ₹ | Sharpe | OOS folds | Pass |
|-----------|--------|-------|--------|-----------|------|
| **rsi_mr_paper_stack** | 102 | ₹-1,183 | -0.649 | — | PASS |
| **quadapt_ml_consensus** | 105 | ₹-6,135 | -5.418 | — | FAIL |
| **quadapt_ml_short** | 39 | ₹-2,133 | -3.167 | — | FAIL |

## Decision

PASS — **rsi_mr_paper_stack** (rsi_mr) net ₹-1,183, Sharpe -0.649, 102 trades. Paper-test only; do not enable live without walk-forward on paper journal.
