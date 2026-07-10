# Sprint 5 — Robustness (VWAP, volume, universe)

Generated: 2026-07-10 08:41 UTC | Tier: t250 (76 symbols) | Window: 180d | Source: cache

## Variants

| ID | Trades | Net ₹ | Sharpe |
|----|--------|-------|--------|
| p5_base | 51 | **319** | 0.343 |
| p5_vwap_fade | 48 | **744** | 0.845 |
| p5_vwap_exit | 58 | **-2,276** | -4.032 |
| p5_vol_surge | 51 | **427** | 0.462 |
| p5_no_denylist | 57 | **544** | 0.620 |
| p5_base_slip | 50 | **611** | 0.674 |
| p5_nifty250 | 56 | **728** | 0.849 |

## Gates

- Trades ≥ 15: **PASS**
- Sample ≥ 150 (or Nifty 250): **FAIL**
- Slippage net > 0: **FAIL**

## Decision

PARTIAL — continue tuning VWAP/volume gates; see variant table.
