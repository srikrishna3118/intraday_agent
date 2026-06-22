# Research Phase Findings

Generated: 2026-06-20 14:08 UTC | Window: 180d T2 | Source: cache

## Phase 1 — Entry stack

Goal: beat Test 9 reference (net −₹133, ≥15 trades).

| Variant | Trades | Gross ₹ | Net ₹ | Sharpe |
|---------|--------|---------|-------|--------|
| Test 9 ref (pivot + RSI>80 + hour<14 + denylist) | 22 | 791 | **-133** | -0.308 |
| Test 9 + ATR_STOP_MULT=1.25 | 22 | 586 | **-338** | -0.869 |
| Test 9 + ATR_STOP_MULT=1.0 | 22 | 604 | **-320** | -0.832 |
| Pivot stack + RSI>82 | 12 | 415 | **-89** | -0.231 |
| Pivot stack + RSI>84 | 6 | 262 | **10** | 0.033 |
| Pivot stack + RSI>85 | 4 | -41 | **-209** | -0.732 |

**Winner:** Test 9 ref (pivot + RSI>80 + hour<14 + denylist) — net ₹-133, 22 trades, Sharpe -0.308.
**Gate:** FAIL (beat −₹133 with ≥15 trades).

## Phase 2 — Exit tuning

Base: Phase 1 winner config.

### ATR stop mult

| ATR_STOP_MULT | Trades | Net ₹ | ATR stops | Stop net ₹ |
|---------------|--------|-------|-----------|------------|
| 1.0 | 22 | **-320** | 6 | -940 |
| 1.25 | 22 | **-338** | 6 | -958 |
| 1.5 | 22 | **-133** | 5 | -859 |
| 1.75 | 21 | **-186** | 4 | -911 |

### ATR target mult (best stop)

| ATR_TARGET_MULT | Trades | Net ₹ | Sharpe |
|-----------------|--------|-------|--------|
| 2.5 | 21 | **-49** | -0.120 |
| 3.0 | 21 | **24** | 0.058 |
| 3.5 | 21 | **45** | 0.108 |

**Final stack net:** ₹45 | Sharpe 0.108 | 21 trades | gross ₹927.
**Gate:** PASS (net ≥ 0 or Sharpe > 0).

### Exit family breakdown (final stack)

| Exit | Trades | Net ₹ |
|------|--------|-------|
| trailing stop | 8 | -200 |
| RSI mid-line exit | 7 | 723 |
| ATR stop | 4 | -702 |
| ATR target | 1 | 112 |
| EOD square-off | 1 | 112 |

## Phase 3 — Paper promotion

**Promote pivot to paper .env:** Yes.

### Checklist

- PASS: sim gate met — safe to trial pivot stack in paper .env
- Sim net ≥ ₹0 or Sharpe > 0 before enabling pivot in paper .env
- Run 5–10 market days: python run_agent.py --once (paper)
- Compare journal net vs sim expectancy per trade
- Do not set LIVE_TRADING=true without explicit approval

### Recommended paper `.env` (research winner)

```env
STRATEGY=rsi_mr
ALLOW_SHORT=true
ALLOW_LONG=false
LIVE_TRADING=false
RSI_OVERBOUGHT=80.0
ENTRY_CUTOFF_TIME=14:00
EXCLUDED_SYMBOLS=ONGC,SBIN,BAJFINANCE
PIVOT_FILTER_ENABLED=true
PIVOT_FILTER_MODE=proximity
PIVOT_TOUCH_PCT=0.35
ATR_STOP_MULT=1.5
ATR_TARGET_MULT=3.5
USE_ATR_EXITS=true
VWAP_FILTER_ENABLED=false
```

## Decision

Proceed to paper trial with pivot stack (stop=1.5, target=3.5, RSI>80.0). Sim net ₹45.
