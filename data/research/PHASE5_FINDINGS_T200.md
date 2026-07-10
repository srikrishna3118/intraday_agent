# Sprint 5 — Robustness (VWAP, volume, universe)

Generated: 2026-07-10 10:51 UTC | Tier: t200 (200 symbols) | Window: 180d | Source: cache

## Variants

| ID | Trades | Net ₹ | Sharpe |
|----|--------|-------|--------|
| p5_base | 120 | **-3,063** | -1.720 |
| p5_vwap_fade | 111 | **-5,187** | -2.921 |
| p5_vwap_exit | 181 | **-7,612** | -5.754 |
| p5_vol_surge | 116 | **-2,208** | -1.276 |
| p5_no_denylist | 105 | **-1,420** | -0.779 |
| p5_base_slip | 104 | **-1,518** | -0.830 |
| p5_nifty200 | 103 | **-1,208** | -0.664 |

## Gates

- Trades ≥ 15: **PASS**
- Sample ≥ 150 (or Nifty 200): **FAIL**
- Slippage net > 0: **FAIL**

## Decision

PARTIAL — continue tuning VWAP/volume gates; see variant table.
