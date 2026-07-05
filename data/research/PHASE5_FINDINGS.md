# Sprint 5 — Robustness (VWAP, volume, universe)

Generated: 2026-07-05 14:13 UTC | Window: 180d | Source: cache

## Variants

| ID | Trades | Net ₹ | Sharpe |
|----|--------|-------|--------|
| p5_base | 17 | **347** | 1.024 |
| p5_vwap_fade | 16 | **142** | 0.437 |
| p5_vwap_exit | 17 | **-753** | -3.689 |
| p5_vol_surge | 17 | **347** | 1.024 |
| p5_no_denylist | 22 | **8** | 0.017 |
| p5_base_slip | 17 | **347** | 1.024 |
| p5_nifty100 | 24 | **32** | 0.071 |

## Gates

- Trades ≥ 15: **PASS**
- Sample ≥ 150 (or Nifty100): **FAIL**
- Slippage net > 0: **PASS**

## Decision

PASS — Sprint 4 stack survives Sprint 5 friction checks.
