# Tier 4 — ATR Stop Multiplier Sensitivity

Stack: RSI>80.0, hour<14, denylist. EOD square-off IST fix applied.

| ATR_STOP_MULT | Trades | Gross ₹ | Net ₹ | ATR stops | Stop net ₹ |
|---------------|--------|---------|-------|-----------|------------|
| 1.0 | 47 | 1,155 | **-819** | 15 | -2,167 |
| 1.25 | 47 | 1,291 | **-683** | 12 | -1,951 |
| 1.5 | 47 | 1,176 | **-798** | 12 | -2,066 |

Best net at ATR_STOP_MULT=1.25 (₹-683). Validate in paper before changing .env.
