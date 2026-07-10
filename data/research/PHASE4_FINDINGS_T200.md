# Sprint 4 — Mean Exit Ablation + Friction

Generated: 2026-07-10 10:21 UTC | Tier: t200 (200 symbols) | Window: 180d | Source: cache

Rationale: `data/research/GEMINI_CRITIQUE_AND_SPRINT4.md`

## Variants

| ID | Trades | Net ₹ | Sharpe | Slippage net ₹ |
|----|--------|-------|--------|----------------|
| p4_control | 136 | **-4,003** | -2.555 | — |
| p4_mean_rsi | 120 | **-3,297** | -1.810 | — |
| p4_mean_rsi_vwap | 183 | **-7,671** | -5.805 | — |
| p4_mean_rsi_slip | 120 | **-3,167** | -1.763 | **-4,783** |
| p4_control_slip | 136 | **-3,760** | -2.439 | **-5,583** |
| p4_no_denylist | 119 | **-2,719** | -1.565 | — |

## Gates

- Beat Phase 2 control (₹-4,003): **PASS** (mean RSI net ₹-3,297)
- Trades ≥ 15: **PASS**
- Mean exit + slippage > 0: **FAIL** (₹-4,783)
- Overall: **FAIL**

## Exit breakdown (mean RSI variant)

| Exit | Trades | Net ₹ |
|------|--------|-------|
| RSI mid-line exit | 45 | 6,372 |
| ATR stop | 44 | -8,927 |
| EOD square-off | 30 | -760 |
| window end square-off | 1 | 17 |

## Deferred

- TIME_STOP_BARS exit (4–6 bars) — needs strategy/sim hook
- Top-100 volume universe — Sprint 5 (needs symbol list + cache)
- VWAP extension entry + volume surge block — Sprint 5 (strategy.py)
- ≥150 trades statistical gate — Sprint 5

## Decision

PARTIAL — mean RSI exit beats control on net, but slippage or sample size fails. Keep paper stack; do not promote mean exit yet.
