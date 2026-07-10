# Sprint 4 — Mean Exit Ablation + Friction

Generated: 2026-07-10 08:31 UTC | Tier: t250 (76 symbols) | Window: 180d | Source: cache

Rationale: `data/research/GEMINI_CRITIQUE_AND_SPRINT4.md`

## Variants

| ID | Trades | Net ₹ | Sharpe | Slippage net ₹ |
|----|--------|-------|--------|----------------|
| p4_control | 57 | **-896** | -0.933 | — |
| p4_mean_rsi | 54 | **49** | 0.053 | — |
| p4_mean_rsi_vwap | 62 | **-2,466** | -4.310 | — |
| p4_mean_rsi_slip | 55 | **-130** | -0.135 | **-858** |
| p4_control_slip | 57 | **-1,025** | -1.066 | **-1,782** |
| p4_no_denylist | 60 | **130** | 0.143 | — |

## Gates

- Beat Phase 2 control (₹-896): **PASS** (mean RSI net ₹49)
- Trades ≥ 15: **PASS**
- Mean exit + slippage > 0: **FAIL** (₹-858)
- Overall: **FAIL**

## Exit breakdown (mean RSI variant)

| Exit | Trades | Net ₹ |
|------|--------|-------|
| RSI mid-line exit | 21 | 2,809 |
| ATR stop | 17 | -3,095 |
| EOD square-off | 16 | 336 |

## Deferred

- TIME_STOP_BARS exit (4–6 bars) — needs strategy/sim hook
- Top-100 volume universe — Sprint 5 (needs symbol list + cache)
- VWAP extension entry + volume surge block — Sprint 5 (strategy.py)
- ≥150 trades statistical gate — Sprint 5

## Decision

PARTIAL — mean RSI exit beats control on net, but slippage or sample size fails. Keep paper stack; do not promote mean exit yet.
