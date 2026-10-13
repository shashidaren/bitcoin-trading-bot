# Speeding up the forward test — the fast path for the statistical gates

**Question this answers:** "Testing takes a very long time — is there a way to
speed it up?"

**Short answer:** the *compute* is not the bottleneck (the whole `tools/` suite
runs in ~13 s). The forward test is slow because it is **real time**: ~4 trades
per day, and confirming the edge needs ~700 post-gate trades (~30 weeks), plus
two critical-path items that were never started. You cannot compress wall-clock
data collection, but you **can** (1) parallelise the calendar and (2) cross-check
the statistical go-live gates on a long history in seconds.

---

## 1. Diagnosis (measured 2026-10-13)

| Step | Time |
|---|---|
| `smoke_test.py` (regression A–M) | ~2.1 s |
| `win_rate_report.py --spread 0.40` | ~4.0 s |
| `pathwalk_sims.py --census` | ~3.4 s |
| `check_data.py` / `live_readiness.py` / rest | <0.6 s each |

The binding go-live gates (`tools/live_readiness.py`) are **statistical**:
EDGE (day-block bootstrap P(net/trade>0) ≥ 0.90) and COST (break-even ÷ assumed
spread ≥ 2.0×). At ~4 trades/day those take months to resolve. Everything below
attacks that.

## 2. Lever 1 — start the two un-started critical-path items (free, biggest)

Per `docs/HANDOFF.md` §7, these two starts are what move the micro-live date, and
they run **in parallel** with ongoing collection instead of stacking after it:

- **Install the XM logger** (`tools/mt5_quotes.py` + `deploy/mt5quotes.service`,
  install as `mt5quotes-btc`). It is built and fake-terminal-tested; the real
  test is the checklist in `docs/XM-LOGGER.md` §3. The **≥14-day clock (incl. 2
  weekends) starts at the first real `OK` row**, so installing it today finishes
  14 days sooner. Read progress with `python3 tools/xm_quote_report.py`.
- **Begin Stage A** (order-path fixes + Wine executor). `live_path_probe.py` is
  still 1/9 clean; Stage A is the critical path for any micro-live.

Neither needs new code — they need to be *started*. This is the single highest-
leverage action and it costs nothing but calendar time.

## 3. Lever 2 — large-N historical cross-check (this session's new tools)

Replay the **frozen** gates over months of M5 history to get the EDGE/COST/
fragility numbers at N in the hundreds/thousands in **seconds**, reusing the same
`replay_lib` walk and `live_readiness` statistics. Two new tools:

- **`tools/history_to_log.py`** — raw M5 OHLC → engine-faithful
  `forward_test_log.csv` (reproduces the engine's EMA/RSI/ATR/floor exactly;
  `--selfcheck` proves it). Lets you point the existing replay/report tools at a
  long history.
- **`tools/backtest.py`** — long history → the binding-gate metrics
  (net/trade, t-stat, day-block bootstrap P, cost cover, per-side, fragility),
  for both the raw entry stream and the cascade "takeable book".

### How to run it

You need a long M5 OHLC history (fetch on the box that has the Twelve Data key or
MT5 — this sandbox cannot reach those hosts). Any `Timestamp,Open,High,Low,Close
[,Volume]` CSV works.

```bash
# prove the converter reproduces the engine on data you already trust
python3 tools/history_to_log.py forward_test_log.csv --selfcheck

# turn a long raw history into a log, then run the gate cross-check
python3 tools/backtest.py long_history.csv --spread 0.40 --save-log bt_log.csv

# or run the EXISTING tools on the prepared log (census + exit-rule grids)
python3 tools/pathwalk_sims.py --root . --census --spread 0.40   # after copying bt_log.csv -> forward_test_log.csv

# slices / hypotheses
python3 tools/backtest.py long_history.csv --side buy --min-date 2026-06-01
python3 tools/backtest.py long_history.csv --tp 5.0 --be 0.75        # candidate exits
```

### What it already tells us (36-day smoke run)

On the current 36-day log the reconstruction is 100% and the raw entry stream
sits at WR ≈ 34.6% — essentially the 33.3% RR-1:2 breakeven — and the takeable
book is ~break-even net of $0.40 (cost cover ≈ 1.0×). That **corroborates** the
handoff's "edge unproven / cost gate FAIL" conclusion. Run it on months of
history to see whether that holds at large N before spending 30 more weeks.

## 4. Lever 3 — lower the go-live bar (a risk call, not code)

The ~700-trade target is for *high* confidence. Stage D is explicitly "tiny size
+ kill switches" and is designed to start with less. If you accept micro-live
risk at ~150–200 forward trades, the date moves up months. That is a risk-
tolerance decision only you can make — the tools above just make the trade-off
visible sooner.

## 5. Honesty rules for anything quoted from Lever 2

- It is an **M5 reconstruction**, not the tick-resolved live engine (the same
  <100% agreement `pathwalk_sims` prints). Read rows **relatively**.
- It is **out-of-sample only for history the gates were not tuned on.** Do not
  read a pooled back-test point estimate as a live expectation.
- All trades use the **current geometry** (2×/4×), so no geometry-change pooling
  inside one run; use `--min-date` to align a slice.
- If the printed reconstruction quality is not ~100%, distrust every number below.

See `docs/HANDOFF.md` §9 (do not pool across the 2026-09-06 geometry change) and
§10 (keep the handoff honest).
