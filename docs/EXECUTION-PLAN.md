# Execution Plan — Nasdaq-100 (`US100Cash`) M15 Bot

**Branch:** `arena/6cc2c0b1-nasdaq-trading-bot` (fixed for this session; use the active branch in future sessions)
**Reviewed:** 2026-10-30 (UTC)
**Status:** Phase 1 in progress; live-server feed verification and missing-candle investigation are outstanding. The autosync rollback data-loss hazard (leading hypothesis for the missing candles) is fixed and regression-tested on this branch, but **not yet deployed**: the currently deployed autosync still has the unsafe rollback, so merging to `main` must wait for the controlled deployment procedure (operator-approved; see the Phase 1 notes below and `docs/AUTOSYNC.md`).

The checked-in snapshot is **not live telemetry**: as of `status.json` at 2026-10-30 09:00 UTC it records FORWARD_TEST, one closed trade (1W/0L) and a gross engine ledger of $222.70. A historical `feed: OK` in that file does not prove the feed is currently healthy.

Every prompt in this session should follow this plan. Work is ordered: **stabilize → evidence → soak → gates → live**. Do not skip a phase.

---

## Phase 1 — Stabilize & Verify (this session)

Goal: make the repo self-describing and the dashboard show a trustworthy readiness picture.

| # | Task | Command / Artifact | Acceptance |
|---|------|-------------------|------------|
| 1.1 | Refresh HANDOFF snapshot | `python3 tools/handoff_check.py --update` | `docs/HANDOFF.md` snapshot block matches live data (no `[ drift ]` / `[ STALE ]`) |
| 1.2 | Run full verification ladder | `tools/feed_doctor.py`, `tools/check_data.py`, `tools/smoke_test.py`, `tools/live_path_probe.py` | 0 failures; all warnings investigated, including any CME maintenance-boundary gaps |
| 1.3 | Verify **Readiness** tab | `dashboard.py` — nav tab + `/readiness` panel | Tab renders the current feed verdict, the same six data gates as `live_readiness.py`, trade stats, readiness verdict and an unsigned non-data checklist |
| 1.4 | Commit + push | `git commit` / `git push origin arena/6cc2c0b1-nasdaq-trading-bot` | Working tree clean; work remains on the active development branch |

**Definition of done for Phase 1:** `python3 tools/check_data.py` exits 0 with its warnings investigated, `tools/handoff_check.py` reports no problems, the offline tests and execution probe pass, the dashboard loads on `:6001` with a working Readiness tab, and `tools/feed_doctor.py` is verified on the actual MT5 host.

### Phase 1 verification notes — checkout snapshot, 2026-10-30

- The HANDOFF snapshot has been refreshed. `check_data.py` exits 0 but reports **18 missing M15 slots**. Four are 21:00 UTC bars adjacent to the daily maintenance break; **14 occurred during open-market hours on October 30** (04:45–05:00, 06:00–07:00, 07:30–08:00 and 08:30–08:45 UTC). All missing slots are present in the checked-in XM candle backfill. Their absence from the engine's forward log is **not yet proven explained**; investigate the engine/feed/journals on the VPS. Do not edit or backfill the forward ledger to hide the gaps.
- **Autosync rollback race (leading hypothesis, not proven):** `tools/autosync.sh` committed live data, merged upstream, smoke-tested, and on failure ran `git reset --hard` to the pre-merge commit — erasing rows the still-running engine/XM logger wrote after the data commit. Data collection 4740 (04:45:01) contains candles only through 04:30; a failed deploy rolled back at 04:45:05 and another at 05:00, while the engine journal/EMAs show it processed candles now missing from the CSV. Timing fits, but precise write times are unverified and no trade loss has been established. **Fix status (2026-10-30, this branch):** rollback rewritten to preserve concurrent writes through merges/conflicts/aborts/smoke failures (data-only commits around every step, out-of-worktree backup + verification, no `reset --hard`, fail-safe no-push + non-zero exit if preservation is unverifiable), with deterministic temp-repo integration tests in `tests/test_autosync.py` (also run by smoke Scenario S). **Not deployed:** merging this to `main` would let the *currently deployed, unsafe* autosync perform the deploy (bash also reads its own script file incrementally, so a mid-run self-update is itself hazardous). Deploy only via the controlled procedure: operator pauses cron, updates `tools/autosync.sh` on the VPS by hand, verifies, resumes cron — awaiting operator approval.
- **`feed_doctor.py` XM witness time bug (fixed on this branch):** the witness treated `candles_m15.csv`'s `bar_close_utc` as an *open* time and added 15 minutes, so the reported bar age was one bar too fresh (a bar closed 21 min ago read as 6 min) and could wrongly prove MT5 alive. It now resolves the timestamp column from the header, reports open/close correctly, and fails closed on unknown schema. Regression: `tests/test_feed_doctor.py` + smoke Scenario R.
- `feed_doctor.py` returns `FILE_MISSING` in this isolated development checkout because there is no local MT5 feed/heartbeat. This does **not** establish the VPS feed's present state; rerun the doctor and verification ladder on `/opt/nasdaq`.
- The offline smoke suite and `live_path_probe.py` exercise temporary files and **fake MT5**, not a real XM demo or live account. Passing them does not complete the execution soak.
- The checked-in ledger has **1/100** post-gate trades. `live_readiness.py --spread 0.25` currently shows **0/6** data gates passing: the sample and the 90-minute open-market gap fail; four statistical gates remain unknown. The dashboard also checks current feed/heartbeat and snapshot freshness independently.

The Readiness page and CLI deliberately fail closed on missing/malformed evidence. Scheduled closures split gap runs, but missing open-market candles remain visible. `UNKNOWN` is not `PASS`; even 6/6 data gates passing does not replace the manual contract/cost, demo-soak and kill-switch sign-offs.

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
