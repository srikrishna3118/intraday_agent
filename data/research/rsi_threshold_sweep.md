# Tier 2 — RSI Threshold Sweep (new stack, 180d T2)

Fixed: hour < 14 IST, exclude ONGC/SBIN/BAJFINANCE, EOD square-off IST fix.

| RSI > | Trades | Gross ₹ | Net ₹ | Sharpe | ATR stops | ATR stop net ₹ | Max hold |
|-------|--------|---------|-------|--------|-----------|----------------|----------|
| 80 | 47 | 1,310 | **-664** | -0.847 | 12 | -2,066 | 135.0m |
| 82 | 30 | 188 | **-1,072** | -1.756 | 8 | -1,455 | 135.0m |
| 84 | 13 | 247 | **-299** | -0.573 | 5 | -871 | 135.0m |
| 85 | 10 | -271 | **-691** | -1.381 | 5 | -871 | 135.0m |

Best net: **RSI > 84** (₹-299, 13 trades). Paper Tier 1 uses RSI>80 until Tier 2 confirms a higher floor.
