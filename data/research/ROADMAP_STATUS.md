# Adversarial Research Roadmap — Status & Pending Work

**Last updated:** 2026-07-10  
**Plan reference:** Adversarial Research Roadmap (Phases 0–6)  
**Paper host:** Desktop (Oracle cloud deferred)

> **Master findings & execution plan:** [FINDINGS_AND_NEXT_STEPS.md](FINDINGS_AND_NEXT_STEPS.md)  
> Narrative and config: [RESEARCH_HANDBOOK.md](RESEARCH_HANDBOOK.md). Implementation registry: [IMPLEMENTATIONS_AND_NEXT_RESEARCH.md](IMPLEMENTATIONS_AND_NEXT_RESEARCH.md). Paper sessions: [paper_trial_log.md](paper_trial_log.md).

---

## At a glance

| Area | Status |
|------|--------|
| Sim / code (Phases 0, 2, 3, 6) | **Done** |
| T200 / T250 full-universe research | **Done** — net negative |
| Edge search (T2, ₹50k) | **Done** — +₹2,438 net; see [EDGE_VALIDATED.md](EDGE_VALIDATED.md) |
| Paper validation (P3) | **Next** — run agent on market days; ≥15 sessions |
| Live trading | **Off** — user approval required |

---

## Phase completion matrix

| Phase | Goal | Done when | Status |
|-------|------|-----------|--------|
| **0** | Sprint 4 exits + commit + docs | `PHASE4_FINDINGS.md` + code committed | ✅ **Done** |
| **1** | Paper journal 5–10 market days | ≥5 weekdays in `paper_trial_log.md` | ⏳ **In progress** (1 day, old stack) |
| **2** | Quadapt bake-off | `quadapt_ml_bakeoff_verdict.md` PASS or FAIL | ✅ **Done** — FAIL, archived |
| **3** | Sprint 5 robustness + circuit guard | ≥150 trades, net > 0 after slippage | 🟡 **Partial** — T200: surge block helps; net still negative |
| **4** | Telegram + WebSocket + deploy | Infra ready after paper or 150+ sim trades | 🟡 **Stubs only** |
| **5** | 5m ablation (optional) | Only if Phase 3 stalls on n | ⏸️ **Deferred** |
| **6** | `RESEARCH_HANDBOOK.md` + ledger sync | Handbook + no stale contradictions | ✅ **Done** |

---

## Completed deliverables

### Phase 0 — Sprint 4

- **Winner:** Mean RSI exit (`RSI_EXIT=50`, `ATR_TARGET_MULT=50`, `TRAILING_STOP_ENABLED=false`)
- **Numbers:** +₹347 net / 17 trades / Sharpe 1.024; slippage stress +₹113
- **Rejected:** VWAP breakdown exit (−₹753)
- **Artifacts:** `PHASE4_FINDINGS.md`, `phase4_findings.json`
- **Config:** `.env.example` updated; committed (`7841311`)

### Phase 2 — Quadapt

- **Verdict:** FAIL — consensus −₹372 / 8 trades; short-only −₹126 / 2 trades
- **Action:** Do not use in paper; research archive only
- **Artifacts:** `quadapt_ml_bakeoff_verdict.md`, `quadapt_bakeoff.json`

### Phase 3 — Sprint 5 (code + sim)

| Variant | Trades | Net ₹ | Note |
|---------|--------|-------|------|
| p5_base | 17 | +347 | Same as Sprint 4 winner |
| p5_vwap_fade | 16 | +142 | Marginal vs base |
| p5_vwap_exit | 17 | −753 | Rejected |
| p5_vol_surge | 17 | +347 | No change on T2 window |
| p5_no_denylist | 22 | +8 | Denylist bias small |
| p5_nifty100 | 24 | +32 | **49/100 symbols cached** |

- **Implemented in code:** VWAP MR fade gate, volume surge block, circuit proximity guard, `SCAN_UNIVERSE=nifty100`, `research_phases.py --phase 5`
- **Artifacts:** `PHASE5_FINDINGS.md`, `phase5_findings.json`

### Phase 6 — Documentation

- `RESEARCH_HANDBOOK.md` (12 sections + appendices)
- `IMPLEMENTATIONS_AND_NEXT_RESEARCH.md` synced
- `README.md`, `USER_GUIDE.md` link handbook

### Phase 4 — Infra stubs (not production)

- `intraday_agent/alerts.py` — Telegram (env: `ALERTS_ENABLED`, `TELEGRAM_*`)
- `intraday_agent/broker.py` — `connect_stream()` / SmartStream init
- `agent.py` — connects stream on login when `STREAM_ENABLED=true`
- **Not done:** systemd unit, deploy doc, full WebSocket tick loop

---

## Pending work (priority order)

### P0 — Paper trial (Phase 1) — **you**

**Blocker for promotion.** Sim edge is not validated live.

| # | Task | Gate |
|---|------|------|
| 1.1 | Run `python run_agent.py` each market day (09:15–15:30 IST) | Desktop; `LIVE_TRADING=false` |
| 1.2 | Log session in `paper_trial_log.md` | ≥5 weekdays (0 entries OK) |
| 1.3 | Compare journal net vs sim | ~₹20/trade; rollback if &lt; ~₹16/trade |
| 1.4 | Do **not** switch to Quadapt or 5m | rsi_mr only |

**Resume:** Next weekday ~09:15 IST. Stack = Sprint 4 mean-exit (see handbook §5 or `.env.example`).

**Rollback if underperforms:**

```env
PIVOT_FILTER_ENABLED=false
ATR_TARGET_MULT=3.0
TRAILING_STOP_ENABLED=true
```

**Promotion checklist** (`paper_trial_log.md`):

- [ ] ≥5 weekdays logged
- [ ] Paper net not worse than sim by &gt;20% per trade
- [ ] No unexpected pivot/screener data gaps
- [ ] User confirms before any live discussion

---

### P1 — Research (revised — see [FINDINGS_AND_NEXT_STEPS.md](FINDINGS_AND_NEXT_STEPS.md))

| Task | Why | Status |
|------|-----|--------|
| **P0a** Verify trailing off in paper logs | Jun sessions used old stack | Pending next session |
| **P0b** Position sizing ≥₹50k notional | Cost drag (−₹301 on 9 trades) | Pending sim + `.env` |
| **P0c** Sim ↔ live alignment | Paper trades faster than sim | Pending |
| **P1** Time stop ablation (T2) | ATR stop −₹9k decomposition | **Done** — 4–5 bars hurts; keep `TIME_STOP_BARS=0` |
| **P2** RSI/VolR + surge block (T2) | CIPLA pattern | **Done** — ATR 1.25 + 13:00 cutoff wins |
| ~~Prefetch Nifty 100~~ | ~~≥150 trades via expansion~~ | **Deferred** — T200 negative; use T2 paper |
| ~~Re-run Sprint 5 Nifty 100~~ | ~~Statistical sample~~ | **Deferred** until T2 paper net-positive |

---

### P2 — Infrastructure (gated)

**Prerequisites:** Paper journal confirms sim expectancy **or** Sprint 5 ≥150 trades net-positive.

| Task | Status | Notes |
|------|--------|-------|
| Telegram alerts wired + tested | Stub done | Set `ALERTS_ENABLED`, bot token in `.env` |
| SmartStream full migration | Stub done | REST polling remains default |
| systemd auto-restart | Not started | Helps desktop power cuts |
| Oracle cloud deploy | **Deferred** | User chose desktop for now |
| **Live trading** | **Off** | Explicit user approval + circuit guard + alerts |

---

### P3 — Explicitly deferred / blocked

| Item | Rule |
|------|------|
| `quadapt_ml` in paper | Bake-off FAIL |
| `REGIME_ADAPTIVE=true` | ORB −₹42k on 180d T2 |
| `CANDLE_INTERVAL=FIVE_MINUTE` | Phase 5 optional; not started |
| New entry strategies | Until rsi_mr net-positive on T2 paper (≥15 sessions) |
| `RISK_PCT > 0` | **P0b** — test sizing; no longer blocked once sim validates notional |
| Meta-label expansion | Until rsi_mr net-positive |
| TradingView webhooks | Out of scope |

---

## Hard guardrails (unchanged)

1. `REGIME_ADAPTIVE=false`
2. `LIVE_TRADING=false` until circuit guard + alerts + user approval
3. No Quadapt in paper
4. No 5m on production stack without Phase 5 gate
5. No new entry strategies while ATR stop leak unresolved on rsi_mr — **P1 time-stop research scheduled**
6. `RISK_PCT` — enable in P0b after sim validates ₹50k+ notional

---

## Desktop operations notes

- **Power cuts:** Restart `python run_agent.py` when power returns; open paper positions are **in-memory** (not persisted across restarts).
- **Single host:** Do not run agent on desktop and cloud the same day.
- **Sparse signals:** ~1 trade / 10 days in sim is normal for the gated stack.

---

## Key artifacts (quick links)

| File | Purpose |
|------|---------|
| [RESEARCH_HANDBOOK.md](RESEARCH_HANDBOOK.md) | Master research doc |
| [paper_trial_log.md](paper_trial_log.md) | Live paper session log |
| [PHASE4_FINDINGS.md](PHASE4_FINDINGS.md) | Sprint 4 exit ablation |
| [PHASE5_FINDINGS.md](PHASE5_FINDINGS.md) | Sprint 5 robustness |
| [quadapt_ml_bakeoff_verdict.md](quadapt_ml_bakeoff_verdict.md) | Quadapt FAIL |
| [.env.example](../../.env.example) | Paper stack template |

---

## Changelog

| Date | Update |
|------|--------|
| 2026-07-05 | Roadmap Phases 0–3 sim, 2, 6 complete; Phase 1 paper pending; Oracle deferred; desktop chosen |
| 2026-06-22 | Paper day 1 — power cut, 0 entries (pre–Sprint 4 stack) |
