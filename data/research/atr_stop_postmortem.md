# ATR Stop Post-Mortem (180d T2 portfolio)

## Success gates (new stack — paper milestone)

| Gate | Target | Result |
|------|--------|--------|
| Gross P&L | > ₹1,000 | ₹1,176 (PASS) |
| Cost ratio (costs/gross) | < 3 | 1.68 (PASS) |

## Portfolio summary

**New stack (RSI>80, hour<14, denylist):** 47 trades, gross ₹1,176, net ₹-798, 12 ATR stops (net ₹-2,065)

## Answers

- New stack — Q1 RSI concentration: dominant bucket **RSI 80-82** (7 stops). Focus buckets: RSI 80-82: 7 stops (net ₹-1,187), RSI 82-85: 3 stops (net ₹-559), RSI 90+: 1 stops (net ₹-164).
- New stack — Q2 time concentration: **0%** within 5 min, **0%** within 10 min, **8%** within 20 min. Largest bucket: **>20 min** (11 stops). Holds spread beyond 10 min — time exit alone may not replace ATR stop.
- New stack — Q3 symbol cluster (worst net): COALINDIA (3, ₹-476), INFY (2, ₹-401), INDUSINDBK (2, ₹-394), TECHM (1, ₹-179), NTPC (1, ₹-178).

## New stack — ATR stop trade log

| Symbol | Entry | RSI | Vol | ATR% | VWAP dist | Hold | Loss% | Net ₹ |
|--------|-------|-----|-----|------|-----------|------|-------|-------|
| INDUSINDBK | 2026-01-01 10:30 IST | 81.6 | 1.88 | 0.4717 | 1.0112 | 75.0m | -0.774% | -158.0 |
| NTPC | 2026-01-02 10:00 IST | 81.29 | 1.232 | 0.3788 | 0.4718 | 30.0m | -0.911% | -178.0 |
| COALINDIA | 2026-01-02 11:00 IST | 85.28 | 1.395 | 0.4151 | 0.9512 | 60.0m | -0.763% | -155.0 |
| COALINDIA | 2026-01-02 13:30 IST | 92.99 | 1.642 | 0.5448 | 1.768 | 105.0m | -0.822% | -164.0 |
| MARUTI | 2026-01-05 10:15 IST | 80.85 | 1.524 | 0.3128 | 0.6727 | 30.0m | -0.655% | -155.0 |
| INFY | 2026-01-16 09:45 IST | 82.53 | 1.382 | 0.6838 | 0.0517 | 135.0m | -1.202% | -203.0 |
| M&M | 2026-02-10 10:45 IST | 83.29 | 1.483 | 0.3181 | 0.6135 | 30.0m | -0.535% | -120.0 |
| TECHM | 2026-04-29 09:45 IST | 80.74 | 1.821 | 0.586 | 0.74 | 75.0m | -0.948% | -179.0 |
| ITC | 2026-04-29 11:00 IST | 80.61 | 1.379 | 0.4321 | 0.6628 | 105.0m | -0.813% | -162.0 |
| COALINDIA | 2026-05-26 10:30 IST | 81.82 | 1.536 | 0.4824 | 0.8467 | 15.0m | -0.788% | -157.0 |
| INFY | 2026-06-02 10:00 IST | 80.09 | 1.305 | 0.6666 | 0.8174 | 30.0m | -1.126% | -198.0 |
| INDUSINDBK | 2026-06-15 09:15 IST | 83.36 | 1.845 | 0.592 | 0.0054 | 90.0m | -1.305% | -236.0 |
