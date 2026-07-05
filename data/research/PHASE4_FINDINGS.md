# Sprint 4 — Mean Exit Ablation + Friction

Generated: 2026-07-05 14:06 UTC | Window: 180d T2 | Source: cache

Rationale: `data/research/GEMINI_CRITIQUE_AND_SPRINT4.md`

## Variants

| ID | Trades | Net ₹ | Sharpe | Slippage net ₹ |
|----|--------|-------|--------|----------------|
| p4_control | 17 | **63** | 0.200 | — |
| p4_mean_rsi | 17 | **347** | 1.024 | — |
| p4_mean_rsi_vwap | 17 | **-753** | -3.689 | — |
| p4_mean_rsi_slip | 17 | **347** | 1.024 | **113** |
| p4_control_slip | 17 | **63** | 0.200 | **-172** |
| p4_no_denylist | 22 | **8** | 0.017 | — |

## Gates

- Beat Phase 2 control (₹63): **PASS** (mean RSI net ₹347)
- Trades ≥ 15: **PASS**
- Mean exit + slippage > 0: **PASS** (₹113)
- Overall: **PASS**

## Exit breakdown (mean RSI variant)

| Exit | Trades | Net ₹ |
|------|--------|-------|
| RSI mid-line exit | 9 | 679 |
| EOD square-off | 6 | 50 |
| ATR stop | 2 | -382 |

## Deferred

- TIME_STOP_BARS exit (4–6 bars) — needs strategy/sim hook
- Top-100 volume universe — Sprint 5 (needs symbol list + cache)
- VWAP extension entry + volume surge block — Sprint 5 (strategy.py)
- ≥150 trades statistical gate — Sprint 5

## Decision

PASS — mean RSI exit beats Phase 2 control and survives slippage stress. Review paper journal before changing .env exits.
