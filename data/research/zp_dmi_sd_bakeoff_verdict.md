# Strategy Bake-off Verdict

Window: 180d | Symbols: 30 | Data: cache | Engine: portfolio

Baseline (rsi_mr): net ₹-5,290 | Sharpe -2.655 | trades 146

Gates: net > baseline, Sharpe > baseline, trades ≥ 43 (30% of baseline), ≥50% rolling OOS folds positive

## Results

| Candidate | Trades | Net ₹ | Sharpe | OOS folds | Pass |
|-----------|--------|-------|--------|-----------|------|
| **zp_dmi** | 141 | ₹-5,841 | -7.838 | — | FAIL |
| **zp_dmi_sd** | 124 | ₹-5,091 | -7.220 | — | FAIL |
| **zp_dmi_sd_short** | 124 | ₹-5,091 | -7.220 | — | FAIL |

## Decision

FAIL — no candidate beats baseline on all gates. Baseline rsi_mr: net ₹-5,290, Sharpe -2.655, 146 trades. Keep current paper stack; shelve new entry strategies until exits/guards improve.
