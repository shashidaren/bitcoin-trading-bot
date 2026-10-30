# Execution Plan — Nasdaq-100 (`US100Cash`) M15 Bot

**Branch:** `arena/940811db-nasdaq-trading-bot` (fixed for this session)
**Reviewed:** 2026-10-30 (local UTC)
**Status:** FORWARD_TEST, 1 closed trade (1W/0L), equity $222.70, feed OK in `status.json`

Every prompt in this session should follow this plan. Work is ordered: **stabilize → evidence → soak → gates → live**. Do not skip a phase.

---

## Phase 1 — Stabilize & Verify (this session)

Goal: make the repo self-describing and the dashboard show a trustworthy readiness picture.

| # | Task | Command / Artifact | Acceptance |
|---|------|-------------------|------------|
| 1.1 | Refresh HANDOFF snapshot | `python3 tools/handoff_check.py --update` | `docs/HANDOFF.md` snapshot block matches live data (no `[ drift ]` / `[ STALE ]`) |
| 1.2 | Run full verification ladder | `tools/feed_doctor.py`, `tools/check_data.py`, `tools/smoke_test.py`, `tools/live_path_probe.py` | 0 failures; warnings only where explained (CME maintenance break gaps) |
| 1.3 | Add **Readiness** tab to dashboard | `dashboard.py` — new nav tab + panel | Tab renders feed verdict, data-gate pass/fail, trade stats, readiness verdict, non-data checklist |
| 1.4 | Commit + push | `git commit` / `git push origin arena/940811db-nasdaq-trading-bot` | Working tree clean, branch ahead of `main` by plan commits |

**Definition of done for Phase 1:** `python3 tools/check_data.py` exits 0, `tools/handoff_check.py` reports no problems, dashboard loads on `:6001` with a working Readiness tab.

---

## Phase 2 — Statistical Evidence (forward-test accumulation)

Goal: grow the post-gate evidence base so `tools/live_readiness.py` can pass its data gates.

| # | Task | Command / Artifact | Acceptance |
|---|------|-------------------|------------|
| 2.1 | Keep `mt5feed-nasdaq` + `nasdaq-engine` healthy | `docs/NASDAQ-OPS.md` §3 verification ladder | `feed_doctor.py` → OK; no `STALE_FEED` outside market-quiet windows |
| 2.2 | Accumulate ≥ 100 post-gate closed trades | `trades.csv` (entries >= `GATES_DEPLOY`, 2026-10-24) | `live_readiness.py` reports n ≥ 100 post-gate trades |
| 2.3 | Run statistical edge report | `python3 tools/live_readiness.py --spread 0.25` | Gate 1 (sample) + Gate 2 (edge P ≥ 90%) moving toward PASS |
| 2.4 | Run historical backtest for context | `python3 tools/backtest.py xm_data/candles_m15.csv --spread 0.25` | 6-month XM M15 backtest completes; used as prior, not as go/no-go |
| 2.5 | Review losers & pressure | `tools/analyze_losers.py`, `tools/pressure_report.py` | No systematic failure mode hidden in the 1% tail |

**Definition of done for Phase 2:** `live_readiness.py --spread 0.25` data gates trending to 6/6 PASS; no unexplained losing cluster.

---

## Phase 3 — Execution Soak (XM demo, real order path)

Goal: prove the LIVE order path end-to-end without risking real money.

| # | Task | Command / Artifact | Acceptance |
|---|------|-------------------|------------|
| 3.1 | Stage A: arm executor on demo | `docs/START-LEVER1.md` — `MT5_EXEC_ENABLED=1`, `MT5_EXEC_ALLOW_REAL=0`, `TRADING_MODE=LIVE`, XM demo | `tools/live_path_probe.py` 11/11 clean against demo |
| 3.2 | Stage B: 5–10 live demo round-trips | Same demo window | Demo fills match `trades.csv`/`status.json` signal flow; SL/TP reconciliation by `position_id` works |
| 3.3 | Stage C: parity review | Compare simulator vs demo fills (slippage, fill latency) | Parity within assumed spread ($0.25/trade) |
| 3.4 | Test kill switches | `touch /opt/nasdaq/HALT` → emergency flatten | Position flattens, new intents refused, `HALT` removal only after confirmed close |

**Definition of done for Phase 3:** Zero orphaned positions, zero duplicate orders, verified position-id reconciliation, tested HALT flatten.

---

## Phase 4 — Go-Live Gates (before `MT5_EXEC_ALLOW_REAL=1`)

All three must hold (from `docs/HANDOFF.md` §7):

| Gate | Source | Threshold |
|------|--------|-----------|
| Contract & Cost | `tools/xm_quote_report.py` | `calc_profit_usd_0.10lot_plus_100pts == 10.0`, `volume_min <= 0.10`, median spread ≤ 3.5 pts ($0.35 @ 0.10 lot), M15 parity OK |
| Statistical Edge | `tools/backtest.py` + `tools/live_readiness.py` | Day-block bootstrap P(net/trade > 0) ≥ 90%; break-even/assumed spread cover ≥ 2.0x |
| Execution Soak | `tools/live_path_probe.py` + XM Demo | Zero orphans, zero duplicates, SL/TP by position_id, HALT tested |

Plus the non-data checklist from `live_readiness.py` §8 (order path, spread profile, demo parity, kill switches, micro-live caps) — signed off by hand.

**Definition of done for Phase 4:** All 3 data gates PASS + non-data checklist signed → authorized to flip `MT5_EXEC_ALLOW_REAL=1` on a real-money XM account.

---

## Phase 5 — Micro-Live (real money, capped)

Goal: prove live economics at small size before scaling.

| # | Task | Cap |
|---|------|-----|
| 5.1 | Flip `MT5_EXEC_ALLOW_REAL=1` on real XM account | 0.10 lot only, weekday-only, max daily loss $15 / 3 SLs |
| 5.2 | Monitor daily | `dashboard.py` Readiness tab + `feed_doctor.py` each session |
| 5.3 | Review after N trades | Re-run `live_readiness.py` on live ledger; scale only if live P/L matches forward-test within spread |

---

## How to use this plan

- **Each session starts here.** Read Phase 1 status first, then pick the next incomplete task.
- **Do not edit live code on the server** — edit in this checkout, run `tools/smoke_test.py` + `tools/live_path_probe.py`, commit, push, let autosync deploy.
- **Refresh the HANDOFF snapshot** (`tools/handoff_check.py --update`) whenever ledger/config facts change, then commit.
- **Readiness tab** (`dashboard.py` → `/readiness`) is the single source of truth for "are we ready?" during any session.
