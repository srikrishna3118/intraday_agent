# NIFTY F&O spot-signal study

**Generated:** 2026-09-27T00:45:48.007652
**NIFTY 5-min bars:** 55368  |  sessions: 743
**Coverage:** 2023-09-28 09:15:00 → 2026-09-25 15:25:00 (743 sessions)

## 1. 09:20 EMA direction premise (arms 2 and 3)

Signal uses the completed 09:15 5-min bar. Predicted-direction return is 09:15 close → last bar ≤ 15:10.

- n = 519
- mean signed return = 0.0001 (1.1 bps)
- bootstrap 95% lower bound = -0.0003
- first half mean = -0.0001
- second half mean = 0.0004
- win rate = 0.5087
- **PASS = False**  gates={'mean_gt_0': True, 'bootstrap_lb_gt_0': False, 'first_half_gt_0': False, 'second_half_gt_0': True}

## 2. Expiry-day remaining-volatility model (arm 5)

Walk-forward OLS: `log(remaining_rv_11:00_14:30) = a + b log(morning_rv) + c log(prior VIX)`.
10% tail distance never closer than 0.4% of the 11:00 spot. Breach = |14:30−11:00| > distance.

- expiry days = 149  |  OOS n = 100
- OOS R² (walk-forward log remaining RV) = 0.2793
- OOS 10% tail breach rate = 0.1800
- in-sample R² (on remaining RV) = 0.3720
- **PASS = False**  gates={'oos_r2_ge_0.2': True, 'tail_breach_le_0.12': False}
- model path = `data/models/fno_expiry_vol.json`

### By expiry era

- **thursday**: n_oos=48  R²=0.1499  breach=0.1875
- **tuesday**: n_oos=52  R²=0.4371  breach=0.1731
- **transition**: n_oos=0  R²=n/a  breach=n/a

## 3. Intraday profile

- share of day range done by 09:20 / 10:00 / 11:15: 0.4205 / 0.6000 / 0.7388
- |gap| / rest-of-day range = 0.4575

India VIX (prior close) vs 09:20–15:10 realized vol by expiry-cycle day:

- cycle 0: n=150  mean VIX=14.01  mean RV%=0.523  corr=0.4745
- cycle 1: n=146  mean VIX=14.27  mean RV%=0.516  corr=0.6496
- cycle 2: n=152  mean VIX=14.14  mean RV%=0.533  corr=0.4259
- cycle 3: n=142  mean VIX=13.89  mean RV%=0.513  corr=0.5080
- cycle 4: n=146  mean VIX=14.05  mean RV%=0.530  corr=0.4313

## 4. How this feeds the paper trial

- Arms 2 and 3 (`ema920_*`) also need the EMA premise to PASS.
- Arm 5 (`expiry_vol_strangle`) also needs the expiry-model premise to PASS.
- Paper KILL after ~40 sessions is separate: net ≤ 0 after F&O costs, negative in either half, or DD > ₹20k.

