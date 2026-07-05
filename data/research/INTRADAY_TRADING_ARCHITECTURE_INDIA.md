# Advanced Intraday Trading Dynamics — Indian Cash Market
## Strategies, Market Microstructure, and Risk Architecture

**Date:** 2026-07-05  
**Scope:** NSE/BSE Intraday Equity Cash Segment  
**Regulatory Context:** Post-SEBI Peak Margin & T+1 Settlement Era (T+1 fully effective from 2023)

> **Source verification note:** This document was cross-checked against primary sources: Zerodha Z-Connect (Nithin Kamath, original), Zerodha Support Portal (current, reflects T+1 settlement), and Zerodha Charges page (live). Corrections from the original research synthesis are marked with **[CORRECTED]**.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Pre-Market Architecture & Stock Selection](#2-pre-market-architecture--stock-selection)
3. [Market Microstructure: Pivot Point Ecosystem](#3-market-microstructure-pivot-point-ecosystem)
4. [VWAP — The Institutional Benchmark](#4-vwap--the-institutional-benchmark)
5. [High-Probability Directional Strategies](#5-high-probability-directional-strategies)
6. [Risk Architecture & Position Sizing](#6-risk-architecture--position-sizing)
7. [Transaction Friction & Breakeven Reality](#7-transaction-friction--breakeven-reality)
8. [Systemic Perils: Upper Circuit & Short Delivery](#8-systemic-perils-upper-circuit--short-delivery)
9. [Implementation Checklist for This Agent](#9-implementation-checklist-for-this-agent)
10. [Key Formulas Reference](#10-key-formulas-reference)
11. [Key Takeaways](#11-key-takeaways)
12. [Source Verification Summary](#12-source-verification-summary)
13. [Bot Architecture Implementation Plan](#13-bot-architecture-implementation-plan)

---

## 1. Executive Summary

The Indian intraday equity cash market operates as a highly complex, volatile, and institutionally driven ecosystem. SEBI's peak margin requirements and the T+1 settlement cycle have systematically eliminated the era of high-leverage retail speculation, raising the operational bar to institutional-grade standards.

**Core thesis:** No single strategy dominates across all market regimes. A profitable trading architecture requires:
- Quantitative stock selection (liquidity, volatility, institutional footprint)
- Context-aware strategy deployment (ORB for trend days, mean-reversion for range days)
- Strict mathematical risk management (fixed-risk sizing, ATR-adjusted sizing)
- Full awareness of regulatory constraints and catastrophic tail risks (short delivery auctions)

---

## 2. Pre-Market Architecture & Stock Selection

### 2.1 Liquidity & Volume Depth (Non-Negotiable)

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| Average Daily Turnover | > ₹50 crore | Ensures institutional participation, narrow bid-ask spread |
| Universe | Nifty 50 / Nifty Next 50 | Depth, narrow spreads, institutional coverage |
| Exclusion | Small-cap, penny stocks | Wide spreads create immediate transactional deficit |

**Operational rule for this agent:** Already constrained to Nifty 50 (`universe.py`). This is correct.

### 2.2 Relative Volatility & Beta Configuration

| Metric | Target Range | Notes |
|--------|--------------|-------|
| Normalized daily move | 1.5% – 3% | Measured via ATR |
| Beta | > 1.0 | High Beta 50 Index constituents preferred |
| India VIX (high) | Elevated | Wider ranges → wider profit targets |
| India VIX (low/suppressed) | Suppressed | Tighten profit targets; avoid forced trades |

**Agent relevance:** `market_regime.py` already monitors India VIX. `VIX_MAX` config param gates entries. This aligns with the research.

### 2.3 Institutional Footprints — Relative Volume (RVOL)

- **RVOL filter:** Stock must print **1.5× – 2× its 20-period average volume** within the first 30–60 minutes
- Volume surges = footprints of FII/DII block positioning
- Price breakout without volume confirmation = low-probability retail churn

**Current agent gap:** `screener.py` uses a volume MA multiplier (`VOLUME_MA_MULTIPLIER`). Verify the lookback period aligns with 20-period convention.

### 2.4 Sectoral Momentum Confluence

- A breakout in a banking stock is **vastly more reliable** when Nifty Bank is simultaneously trending up on strong volume
- Avoid long setups when the sector index is in heavy sell-off

**Current agent gap:** Agent does not currently check sector index alignment. Could be added as a soft filter using Nifty Bank / Nifty IT index LTP trend.

### 2.5 Regulatory Exclusions (Hard Filters)

| Exclusion | Reason |
|-----------|--------|
| F&O ban-period stocks | Disrupted liquidity and price discovery |
| Trade-to-Trade (T2T) segment | No intraday square-off allowed — compulsory delivery |
| Upper circuit-prone stocks | Short delivery catastrophe risk (see Section 8) |

---

## 3. Market Microstructure: Pivot Point Ecosystem

### 3.1 Standard Pivot Methodologies Compared

| Method | Formula | Best Use Case |
|--------|---------|---------------|
| Standard (Classic) | PP = (H + L + C) / 3 | General daily bias mapping |
| Woodie's | PP = (H + L + 2C) / 4 | When close strongly reflects overnight sentiment |
| Fibonacci | PP ± Fib ratios (38.2%, 61.8%, 100%) | Trending or high-volatility markets |
| DeMark | Based on Open vs. Close relationship | Clean major breakout zones only |

### 3.2 Central Pivot Range (CPR) — The Core Framework

**Formulas:**
```
Pivot Point (P)         = (H + L + C) / 3
Bottom Central Pivot (BC) = (H + L) / 2
Top Central Pivot (TC)  = (P − BC) + P
```

#### CPR Width Interpretation

| CPR Width | Prior Session Behavior | Expected Session Type | Strategy |
|-----------|------------------------|----------------------|----------|
| **Narrow** | Low volatility, compressed range | High-volatility trend day (breakout) | ORB, Gap & Go |
| **Wide** | High volatility, no consensus | Range-bound / choppy | Mean-reversion, fade extremes |

#### CPR Directional Alignment

| CPR Alignment | Market Bias | Preferred Setup |
|---------------|-------------|-----------------|
| Ascending (today's range > yesterday's) | Bullish trend | Buy-on-dip setups |
| Descending (today's range < yesterday's) | Bearish trend | Sell-on-rally setups |

#### Virgin CPR (High-Priority Confluence Zone)

- Defined as: CPR lines **never touched** during an entire prior session
- Statistical observation: **40%–60% probability** of acting as major support/resistance in subsequent sessions
- Actionable setup: Sharp reactive bounce expected when price gravitates to Virgin CPR → excellent risk/reward for counter-trend scalpers

### 3.3 Camarilla Pivot Points — Scalping Precision

Developed by Nick Scott (1989). Uses Fibonacci-based multiplier against prior day's range and close.

> **Formula note:** The original research source presented the Camarilla formulas in ambiguous notation (e.g., `C + 2(H-L) × 1.1` for R4). The correct, unambiguous standard formulas are below, consistent with all major technical analysis references.

**Key Level Formulas (verified standard form):**
```
R4 = C + (H − L) × (1.1 / 2)     ← Breakout Resistance Threshold
R3 = C + (H − L) × (1.1 / 4)     ← Mean-Reversion Resistance
S3 = C − (H − L) × (1.1 / 4)     ← Mean-Reversion Support
S4 = C − (H − L) × (1.1 / 2)     ← Breakout Support Threshold
```

#### Camarilla Session Classification Matrix

| Opening Price Location | Session Type | Strategy | Entry | Stop | Target |
|------------------------|-------------|----------|-------|------|--------|
| Between S3 and R3 | Equilibrium / Range | Mean-reversion | Fade R3 (short) or S3 (long) | Above R4 / Below S4 | Pivot or opposite level |
| Between R3 and R4 | Bullish Strength | Buy R4 breakout | R4 break on volume | Below R3 | R5 / R6 |
| Between S3 and S4 | Bearish Weakness | Short S4 breakdown | 5-min close below S4 | Above S3 | S5 / S6 |
| Outside R4 or S4 | Gap-and-Go (Extreme) | Wait for pullback | Wait for R4/S4 retest | — | — |

---

## 4. VWAP — The Institutional Benchmark

### 4.1 Formula

```
VWAP = Σ(Typical Price × Volume) / Σ(Volume)

where: Typical Price = (H + L + C) / 3
```

VWAP resets daily at **09:15 AM IST**.

### 4.2 Why VWAP Matters (Institutional Mechanics)

- FIIs, prop desks, and mutual funds use VWAP to **measure execution quality**
  - Filled below VWAP → favorable execution
  - Filled above VWAP → overpaid relative to market average
- Billions in algorithmic capital interact with this level → genuine "magnet" behavior
- VWAP is a **self-fulfilling structural barrier**, not just a retail indicator

### 4.3 Sentiment Regimes

| Price vs. VWAP | Regime | Implication |
|----------------|--------|-------------|
| Consistently above ascending VWAP | Bullish | Institutional demand; average participant in profit |
| Consistently below descending VWAP | Bearish | Active distribution; seller dominance |

### 4.4 VWAP Pullback Strategy (High-Probability Entry)

**Setup conditions:**
1. Stock reclaims VWAP from below
2. Pulls back to VWAP
3. Tests VWAP again from **above** on **declining volume**
4. "Second test" = institutional algorithms actively defending the level

This is the highest-conviction VWAP long entry.

### 4.5 VWAP Standard Deviation Bands

- 1 SD and 2 SD bands act as dynamic, volume-adjusted overbought/oversold thresholds
- **Range-bound session:** Price at 2 SD upper band → mean-reversion short targeting central VWAP
- **⚠ Trend day warning:** During strong trends, price "walks" along 1–2 SD bands — counter-trend shorts are extremely dangerous

### 4.6 Anchored VWAP (AVWAP)

- AVWAP is anchored to a specific historical catalyst: earnings release, RBI policy, major swing high/low
- Represents **average cost basis of all participants since the catalyst**
- If price > AVWAP anchored to recent earnings gap → new buyers are profitable → strong trailing support

**Advanced: "Pinch Strategy"**
- Multiple AVWAPs converging (e.g., YTD open + recent swing low) = hyper-dense confluence zone
- Explosive breakout expected when price resolves from the "pinch"

---

## 5. High-Probability Directional Strategies

### 5.1 Opening Range Breakout (ORB)

**Timeframe:** First 15–30 minutes (09:15–09:45 AM)

#### Execution Protocol

| Step | Action | Detail |
|------|--------|--------|
| 1 | Define Opening Range | Mark absolute High and Low of chosen ORB window (15-min standard) |
| 2 | Validate Context | Narrow CPR required. Skip if ORB range > 2.5% of stock price |
| 3 | Entry Trigger | 5-min or 15-min **candle close** outside range (NOT wick penetration) |
| 4 | Volume Confirmation | Breakout candle volume ≥ 1.5× ORB average per-minute volume |
| 5 | Index Confluence | ORB long must occur above daily VWAP and 21-EMA |
| 6 | Stop-Loss | Conservative: opposite end of ORB. Aggressive: midpoint of ORB |
| 7 | Target | Minimum 1:1.5 to 1:2 R:R. Use VWAP as dynamic trailing stop |

**Critical disqualifier:** ORB fails frequently on wide-CPR days → shift to mean-reversion.

### 5.2 Gap and Go

**Optimal gap size:** +0.5% to +3%

| Gap Size | Behavior | Action |
|----------|----------|--------|
| 0.5% – 3% | Continuation momentum | Trade the setup |
| > 5% or > 2× ATR | High exhaustion risk | Avoid — prone to gap fill |

#### Execution Protocol

1. **Wait** for the 15-minute ORB to form (never buy at 09:15 open)
2. Entry: Stock consolidates within ORB then **breaks the 15-min high** on expanding volume
3. Stop: Low of the 15-minute opening candle (not yesterday's close)
4. **Early exit triggers:**
   - Nifty reverses sharply within first 30 minutes
   - Stock surrenders > 50% of post-breakout move on heavy volume

### 5.3 Trend Reversal & Mean Reversion

**Condition: Parabolic extension from VWAP + moving averages**

#### Exhaustion Identification

| Signal Type | Bullish Exhaustion (Short Setup) | Bearish Exhaustion (Long Setup) |
|-------------|----------------------------------|---------------------------------|
| Candlestick | Long upper wicks, shooting stars | Long lower wicks, hammers, dojis |
| RSI | > 75–80 (overbought) | < 20–25 (oversold) |
| Volume | Sharp drop after major run-up | Sharp drop after major sell-off |
| Pivot Level | At Camarilla R3 or above | At Camarilla S3 or below |

**High-probability short entry (example):**
- Price hits Camarilla R3
- Bearish reversal candle forms
- RSI > 80
- Volume declining after run-up
- → **Short** targeting VWAP or 20-EMA

### 5.4 High-Frequency Scalping & the 2652 Framework

> **Unverified claim:** The "2652 Theory" is cited in the original research source but could not be confirmed against a primary published source. It is presented here as an informal practitioner framework, not an established methodology.

- The NSE session (09:15–15:30, 375 minutes) maps to exactly **25 candles** on a 15-minute chart (not 26)
  - Note: 375 min ÷ 15 = 25 candles. The "26" figure in the source likely counts from 09:00 pre-market or includes a partial candle.
- Practical partition:
  - **High-velocity morning phase** (first 8–10 candles, 09:15–11:15) → prime scalping window
  - **Low-volume midday chop** (candles 10–18, 11:15–13:45) → avoid / reduce sizing
  - **Afternoon trend resolution** (candles 18–25, 13:45–15:30) → momentum or EOD square-off

---

## 6. Risk Architecture & Position Sizing

### 6.1 Psychological Discipline — Gambler's Fallacy

- Individual trade outcomes are **independent** — prior losses do not make a win "due"
- Revenge trading (increasing size after losses) = mathematically guaranteed capital destruction
- **Only antidote:** Mechanical, rules-based position sizing algorithm, fully decoupled from emotional state

### 6.2 Fixed-Risk Percentage Model (Gold Standard)

**Rule:** Risk maximum **1%–2%** of total trading equity per trade (novices: 0.5%)

**Formula:**
```
Position Size (shares) = (Total Capital × Risk %) / (Entry Price − Stop-Loss Price)
```

**Example:**
- Account: ₹5,00,000
- Risk rule: 1% → Max loss = ₹5,000
- Entry: ₹1,000, Stop: ₹970 → Risk per share = ₹30
- Position size: ₹5,000 / ₹30 = **166 shares**

**Key property:** Position size adapts to stop distance → portfolio risk remains constant regardless of setup.

### 6.3 Volatility-Adjusted (ATR) Sizing

- Sets stop distance = ATR × multiplier (not a fixed ₹ amount)
- High-beta / high-ATR stocks → smaller position size
- Low-volatility FMCG stocks → larger position size
- **Normalizes variance exposure across the entire portfolio**

**This agent:** `orders.py` already implements ATR-based stop sizing. This validates the approach.

### 6.4 SEBI Peak Margin Framework

| Regulation | Detail | Impact |
|------------|--------|--------|
| Upfront Margin | VaR + ELM ≈ minimum 20% of transaction value | Required before order execution |
| Maximum Intraday Leverage | **5× effective cap** | ₹1,00,000 capital → max ₹5,00,000 exposure |
| Peak Margin Snapshots | 4 randomized snapshots per session | Short-margin penalties if breached at any snapshot |
| T+1 Settlement | Sale proceeds may face redeployment restrictions same day | Maintain constant cash buffer |

**Operational requirement:** Maintain a cash buffer at all times to absorb sudden margin spikes during volatile sessions.

### 6.5 Daily Risk Budget

| Parameter | Conservative | Moderate | Aggressive |
|-----------|-------------|----------|------------|
| Per-trade risk | 0.5% of capital | 1.0% | 2.0% |
| Max daily loss limit | 2% of capital | 3% | 5% |
| Max concurrent positions | 1–2 | 2–3 | 3–5 |
| Stop trading after | 2 consecutive losses | 3 consecutive losses | Daily limit hit |

---

## 7. Transaction Friction & Breakeven Reality

### 7.1 Comprehensive Cost Breakdown (NSE Intraday Cash)

| Charge | Rate | Applied On |
|--------|------|-----------|
| Brokerage | ₹20 flat per order OR 0.03–0.05% (lower) | Per executed order |
| Securities Transaction Tax (STT) | **0.025%** | Sell-side only (intraday) |
| Exchange Transaction Charges | **0.00307%** [CORRECTED] | Both buy and sell turnover |
| SEBI Turnover Fee | **0.0001%** (₹10/crore) | Total turnover |
| State Stamp Duty | **0.003%** | Buy-side only |
| GST | **18%** | On (Brokerage + Exchange Charges + SEBI Fees) |

### 7.2 Total Friction on ₹10,00,000 Round-Trip

| Component | Approximate Cost |
|-----------|-----------------|
| STT (sell side, 0.025%) | ₹250 |
| Exchange charges (both sides, 0.00307%) | ₹61.40 [CORRECTED] |
| Stamp duty (buy side, 0.003%) | ₹30 |
| SEBI fee | ₹2 |
| Brokerage (₹20 × 2 orders) | ₹40 |
| GST (18% on brokerage + exchange + SEBI) | ~₹18.60 |
| **Total friction** | **~₹402 per ₹10L round-trip** [CORRECTED] |

### 7.3 The Scalper's Dilemma

- ~₹400 unavoidable friction on every ₹10L round-trip — **regardless of brokerage plan** [CORRECTED: exchange charge is 0.00307%, not 0.00297%]
- STT and Stamp Duty scale with turnover → high-frequency low-conviction scalping is a capital-destruction strategy
- **Minimum required R:R:** 1:1.5 to 1:2 on every setup

**Mathematical consequence:** A 60% win rate with 1:1 R:R is **unprofitable** after friction. Win rate must be significantly higher, or R:R must be asymmetric.

---

## 8. Systemic Perils: Upper Circuit & Short Delivery

### 8.1 The Upper Circuit Trap Mechanism

1. Trader initiates intraday short position
2. Stock aggressively rallies and hits **upper circuit limit**
3. Exchange halts trading → order book full of buyers, **zero sellers**
4. Trader **cannot execute buy order** to close short before 3:20 PM deadline
5. Position forcibly converted to overnight delivery obligation
6. Trader has no shares in demat → **Short Delivery on T-day**

### 8.2 Buy-in Auction Mechanics

> **T+1 Settlement Note (critical):** India fully transitioned to **T+1 rolling settlement** in 2023. All timelines below reflect the **current T+1 framework**. Legacy content (pre-2023) often cited T+2/T+3 — those references are now outdated.

| Stage | Detail |
|-------|--------|
| When | **T+1 afternoon**, approximately 2:00 PM – 2:45 PM |
| Who participates | Fresh sellers only; defaulting trader is **barred** from participating |
| Price band | ±20% of the T-day settlement price |
| Settlement | **T+2 day** (buyer receives shares or cash) |
| Typical auction price | Near +20% upper band when stock is bullish/circuit-locked |
| Source | Verified: Zerodha Support Portal (current T+1 framework) |

### 8.3 Financial Penalties

| Penalty Type | Amount |
|-------------|--------|
| Price deficit debit | Full difference: Auction price − Original short entry |
| Exchange shortage penalty | **0.05% of security value + 18% GST** (verified: Zerodha Support) |
| Internal shortage penalty (same broker) | **1% of security value + 18% GST** (Clearing Corp facilitation fee — verified: Zerodha Support) |
| Margin block by broker | **120% short delivery margin** blocked on T-day based on settlement price (verified: Zerodha Support) |

### 8.4 Close-Out Catastrophe (Worst Case)

If stock remains upper-circuit locked with zero auction sellers:
- Debit = **highest price between T-day and auction day** OR **20% above auction day's close**, whichever is higher
- No upper price cap → double-digit percentage losses possible on capital
- Under T+1, this settles by **T+2 day** at the latest (verified: Zerodha Support)

### 8.5 Mitigation Rules (Mandatory for This Agent)

The agent's short-only MIS strategy makes this the **highest-priority risk** to manage.

| Rule | Implementation |
|------|---------------|
| Never short circuit-prone stocks | Pre-filter by free float and historical ATR; avoid low-float mid/small cap |
| Never short on explosive pre-market news | Check for gaps > 2× ATR before allowing short entry |
| Auto-square-off buffer | Current default: 15:15 IST (well before 15:20 broker cutoff) ✓ |
| Monitor LTP vs. upper circuit distance | Add LTP circuit proximity check in `screener.py` |

---

## 9. Implementation Checklist for This Agent

| Area | Current State | Recommended Enhancement |
|------|--------------|------------------------|
| Universe | Nifty 50 only ✓ | Add Nifty Next 50 optionally for higher RVOL candidates |
| Volume filter | `VOLUME_MA_MULTIPLIER` exists ✓ | Verify lookback = 20 periods |
| India VIX gate | `VIX_MAX` in `market_regime.py` ✓ | Adjust profit targets dynamically with VIX level |
| Sector alignment | Not implemented | Add soft filter: check Nifty Bank / sector index trend |
| ATR-based stops | Implemented in `orders.py` ✓ | Add ATR-based position sizing (in addition to stops) |
| RSI thresholds | `RSI_*` config params ✓ | Cross-reference with literature: oversold < 25, overbought > 75 |
| EOD square-off | 15:15 default ✓ | Keep as-is; never remove per safety rules |
| Short delivery guard | Not explicit | Add upper circuit proximity check before short entry |
| T2T / F&O ban filter | Not implemented | Add pre-session filter using NSE exclusion list |
| Transaction cost awareness | Not modeled | Add `ESTIMATED_COST_PER_TRADE` to net P&L calculation ✓ (learning/costs.py) |
| CPR / Camarilla levels | Not implemented | Consider adding as optional confluence signals |
| VWAP | Not implemented | Strong candidate for addition as entry/exit reference |

---

## 10. Key Formulas Reference

```
# Pivot Points
Standard PP     = (H + L + C) / 3
Woodie's PP     = (H + L + 2C) / 4
CPR Top (TC)    = (PP − BC) + PP
CPR Bottom (BC) = (H + L) / 2

# Camarilla Levels
R4 = C + (H − L) × (1.1 / 2)
R3 = C + (H − L) × (1.1 / 4)
S3 = C − (H − L) × (1.1 / 4)
S4 = C − (H − L) × (1.1 / 2)

# VWAP
VWAP          = Σ(Typical Price × Volume) / Σ(Volume)
Typical Price = (H + L + C) / 3

# Position Sizing (Fixed-Risk)
Position Size = (Capital × Risk%) / (Entry − Stop)

# ATR-Based Stop
Stop Distance = ATR × Multiplier (e.g., 1.5×)

# Breakeven (approximate, intraday NSE)
Total friction ≈ 0.040% of round-trip turnover (corrected: uses 0.00307% NSE charge)
Required gross move to break even ≈ Entry Price × 0.0004
# Breakdown per ₹10L position: STT ₹250 + NSE ₹61.40 + Stamp ₹30 + SEBI ₹2 + Brokerage ₹40 + GST ₹18.60 = ~₹402
```

---

## 11. Key Takeaways

1. **Stock selection determines 70% of intraday outcomes** — a perfect setup on the wrong stock fails
2. **CPR width predicts the session type** — adapt strategy before the open, not reactively
3. **VWAP is non-optional for institutional-grade execution** — price relationship to VWAP determines regime
4. **ORB is the highest-probability setup on narrow-CPR trend days** — wait for candle close, never wick penetration
5. **Mean reversion requires oscillator + candle + level confluence** — RSI > 75, reversal candle, at Camarilla R3
6. **Fixed 1% risk rule is mathematically mandatory** — emotional sizing destroys all edge
7. **STT makes scalping with < 1:1.5 R:R mathematically losing** — friction is fixed, edge is not
8. **Short delivery is an existential threat for this agent's short-only strategy** — upper circuit + short = catastrophic loss
9. **SEBI 5× leverage cap is the ceiling** — design position sizing within this hard constraint
10. **India VIX should modulate targets, not just entry gates** — high VIX → wider targets; low VIX → tighten or skip

---

## 12. Source Verification Summary

| Claim | Status | Source |
|-------|--------|--------|
| NSE transaction charge 0.00307% | ✅ Verified (was 0.00297% in source) | Zerodha Charges page (live) |
| STT 0.025% sell-side intraday | ✅ Verified | Zerodha Charges page |
| Stamp duty 0.003% buy-side | ✅ Verified | Zerodha Charges page |
| SEBI fee ₹10/crore | ✅ Verified | Zerodha Charges page |
| Auction timing: T+1 afternoon (current) | ✅ Verified (T+2/T+3 refs are pre-2023 legacy) | Zerodha Support Portal |
| Exchange penalty 0.05% + GST | ✅ Verified | Zerodha Support Portal |
| Internal penalty 1% + GST | ✅ Verified | Zerodha Support Portal |
| Margin block 120% on T-day | ✅ Verified | Zerodha Support Portal |
| Close-out = max(highest price, +20% auction close) | ✅ Verified | Zerodha Z-Connect |
| CPR formulas (PP, BC, TC) | ✅ Verified | Standard finance literature |
| Camarilla R4/R3 formulas | ✅ Verified (source notation was ambiguous) | Standard TA references |
| "2652 Theory" (26 candles) | ⚠️ Unverified; candle count should be 25 | No primary source found |
| Virgin CPR 40–60% probability | ⚠️ Practitioner observation, not peer-reviewed | Original research source only |
| SEBI 5× leverage cap | ✅ Verified contextually | SEBI peak margin framework |
| Broker auto-square-off at 3:20 PM | ✅ Verified | Zerodha Z-Connect (multiple instances) |

*Report cross-checked against primary sources — NSE/BSE intraday cash market, 2025–2026 regulatory framework.*

---

## 13. Bot Architecture Implementation Plan

> **Motivation from research:** No single strategy survives all market regimes. Over 70% of long-term profitability comes from position sizing, automated stop-losses, and execution logic — not the indicator. The current bot is a single-strategy, flat-sizing system. This plan closes the gap.

---

### 13.1 Diagnosis: Current Architecture vs. Research Requirements

| Research Requirement | Current State | Gap |
|----------------------|--------------|-----|
| Regime-adaptive strategy selection | Fixed `STRATEGY` env var | No runtime switching |
| Risk-based position sizing: `(Equity × Risk%) / Stop Distance` | Flat `CAPITAL_PER_TRADE / price` | Stop distance ignored |
| ADX regime classifier on market index | EMA filter only | No trend-strength signal |
| Stop price passed through to sizer | ATR computed but not wired to sizer | Sizing ignores ATR stop |
| Regime type exposed to strategy router | Regime gates only (block/allow) | No regime type returned |

---

### 13.2 Changes: Five Files, Fully Backward Compatible

All changes are opt-in via new env vars defaulting to their current behaviour. `REGIME_ADAPTIVE=false` and `RISK_PCT=0` (disabled) by default.

---

#### 13.2.1 `intraday_agent/config.py`

**Add 5 new parameters:**

```python
# Risk-based position sizing
# RISK_PCT > 0 enables risk-based sizing; 0 = use legacy CAPITAL_PER_TRADE
RISK_PCT = float(os.getenv("RISK_PCT", "0"))
ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY", "500000"))

# Regime-adaptive strategy switching
REGIME_ADAPTIVE = os.getenv("REGIME_ADAPTIVE", "false").lower() in ("1", "true", "yes", "y")
REGIME_TREND_ADX_MIN = float(os.getenv("REGIME_TREND_ADX_MIN", "25"))
REGIME_RANGE_ADX_MAX = float(os.getenv("REGIME_RANGE_ADX_MAX", "20"))
```

**No removals. All existing params unchanged.**

---

#### 13.2.2 `intraday_agent/orders.py`

**Add `compute_quantity_risk_based(price, stop_price)`:**

```python
def compute_quantity_risk_based(self, price: float, stop_price: float) -> int:
    """
    Size = (ACCOUNT_EQUITY × RISK_PCT%) / |entry − stop|
    Falls back to compute_quantity(price) if stop distance is zero or RISK_PCT=0.
    """
    if Config.RISK_PCT <= 0 or price <= 0:
        return self.compute_quantity(price)
    stop_dist = abs(price - stop_price)
    if stop_dist < 0.01:
        return self.compute_quantity(price)
    risk_amount = Config.ACCOUNT_EQUITY * (Config.RISK_PCT / 100.0)
    qty = math.floor(risk_amount / stop_dist)
    return max(1, min(qty, Config.MAX_QUANTITY))
```

**Modify `open_position()` signature:** add optional `stop_price: float | None = None` parameter.  
Inside, call `compute_quantity_risk_based(ltp, stop_price)` when `stop_price` is provided and `RISK_PCT > 0`; otherwise fall back to existing `compute_quantity(ltp)`.  
Store `stop_price` on the `Position` dataclass for downstream exit logic.

**`Position` dataclass:** add `stop_price: float | None = None` field.

---

#### 13.2.3 `intraday_agent/market_regime.py`

**Extend `_prepare_nifty()`:** compute Nifty ADX (using existing `compute_adx()` from `strategy.py`) alongside the EMA already calculated. Store in an `adx` column.

```python
# inside _prepare_nifty, after EMA line:
from intraday_agent.strategy import compute_adx
out["adx"] = compute_adx(out, period=Config.ADX_PERIOD)
```

**Add `regime_type(dt) -> str` method:**

```python
def regime_type(self, dt: datetime) -> str:
    """
    Returns 'trending' | 'ranging' | 'neutral'.
    Uses Nifty ADX as the regime classifier.
    """
    adx = self._value_at(self._nifty, dt, "adx")
    if adx is None:
        return "neutral"
    if adx >= Config.REGIME_TREND_ADX_MIN:
        return "trending"
    if adx <= Config.REGIME_RANGE_ADX_MAX:
        return "ranging"
    return "neutral"
```

**Extend `snapshot()`:** include `nifty_adx` and `regime_type` keys.

---

#### 13.2.4 `intraday_agent/agent.py`

**Add `_REGIME_STRATEGY_MAP`** (module-level constant):

```python
_REGIME_STRATEGY_MAP: dict[str, str] = {
    "trending": "orb",
    "ranging":  "rsi_mr",
    "neutral":  "",          # empty = keep current
}
```

**Add `_maybe_switch_strategy(regime)`:**

```python
def _maybe_switch_strategy(self, regime: MarketRegime) -> None:
    if not Config.REGIME_ADAPTIVE or regime is None:
        return
    rtype = regime.regime_type(self.now_ist())
    target = _REGIME_STRATEGY_MAP.get(rtype, "")
    if not target or target == self.strategy.name:
        return
    logger.info("Regime '%s' (ADX-based) → switching strategy %s → %s",
                rtype, self.strategy.name, target)
    self.strategy = get_strategy(target)
    self.screener.strategy = self.strategy
```

*Note: requires `BaseStrategy` to expose a `.name` property (trivial one-liner in `strategy.py`).*

**Wire stop price into `try_entries()`:** before calling `open_position()`, compute `stop_price`:

```python
# compute stop price for risk-based sizing
atr = result.atr or 0.0
atr_stop_dist = atr * Config.ATR_STOP_MULT if atr else 0.0
if side == "SHORT":
    stop_price = result.close + atr_stop_dist
else:
    stop_price = result.close - atr_stop_dist
stop_price = stop_price if atr_stop_dist > 0 else None

res = self.orders.open_position(
    result.symbol, side, result.close,
    ...,
    stop_price=stop_price,        # ← new
)
```

**Call `_maybe_switch_strategy()`** inside `_refresh_regime()` after regime is fetched.

---

#### 13.2.5 `.env.example`

**Append new section:**

```bash
# ── Risk-based position sizing ──────────────────────────────────────────────
# RISK_PCT > 0 enables: Size = (ACCOUNT_EQUITY × RISK_PCT%) / |entry − stop|
# Set RISK_PCT=0 to keep legacy flat CAPITAL_PER_TRADE sizing.
RISK_PCT=0
ACCOUNT_EQUITY=500000

# ── Regime-adaptive strategy switching ──────────────────────────────────────
# When enabled, Nifty ADX determines active strategy at runtime:
#   ADX >= REGIME_TREND_ADX_MIN  →  orb  (trend-following)
#   ADX <= REGIME_RANGE_ADX_MAX  →  rsi_mr  (mean-reversion)
#   between                      →  no change (keep current STRATEGY)
# Disabled by default — set REGIME_ADAPTIVE=true to opt in.
REGIME_ADAPTIVE=false
REGIME_TREND_ADX_MIN=25
REGIME_RANGE_ADX_MAX=20
```

---

### 13.3 Data Flow After Changes

```
MarketRegime.from_broker/feed()
    └─ _prepare_nifty()
           ├─ EMA(20)      [existing]
           └─ ADX(14)      [new]
                └─ regime_type() → "trending" | "ranging" | "neutral"
                        └─ _maybe_switch_strategy()
                                └─ self.strategy = get_strategy("orb" | "rsi_mr")

screener.scan()
    └─ result.atr (existing)
            └─ stop_price = close ± ATR × ATR_STOP_MULT   [new: computed in agent]
                    └─ orders.open_position(..., stop_price=stop_price)
                            └─ compute_quantity_risk_based(price, stop_price)
                                    └─ qty = (ACCOUNT_EQUITY × RISK_PCT%) / stop_dist
```

---

### 13.4 Invariants Preserved (Safety Rules)

| Rule | Preserved |
|------|-----------|
| EOD square-off at `SQUARE_OFF_TIME` | ✅ Untouched |
| ATR / % stop-loss exits in `manage_positions()` | ✅ Untouched |
| `MAX_POSITIONS` cap | ✅ Untouched |
| `TradeGuard` daily loss/trade limits | ✅ Untouched |
| `LIVE_TRADING=false` default | ✅ Untouched |
| `ALLOW_SHORT` / `ALLOW_LONG` gates | ✅ Untouched |
| Regime block (VIX, Nifty EMA) | ✅ Untouched |
| `MAX_QUANTITY` hard cap on any sized quantity | ✅ Enforced inside `compute_quantity_risk_based` |

---

### 13.5 Acceptance Criteria

| Test | Pass Condition |
|------|---------------|
| `RISK_PCT=0` | Behaviour identical to current (flat sizing) |
| `RISK_PCT=1.0`, ATR stop = ₹15, equity = ₹5L | qty = floor(5000 / 15) = 333, capped at `MAX_QUANTITY` |
| `RISK_PCT=1.0`, stop_price=None | Falls back to `compute_quantity(price)` |
| `REGIME_ADAPTIVE=false` | No strategy switching regardless of ADX |
| `REGIME_ADAPTIVE=true`, ADX=30 | strategy switches to `orb` |
| `REGIME_ADAPTIVE=true`, ADX=15 | strategy switches to `rsi_mr` |
| `REGIME_ADAPTIVE=true`, ADX=22 | no switch — keeps current strategy |
| Syntax check all 5 files | `python3 -m py_compile` passes |
| `python tools/status.py` | Health check passes |
