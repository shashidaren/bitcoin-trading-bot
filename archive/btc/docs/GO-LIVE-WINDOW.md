# Go-live window — planning calendar (not a live switch)

Written 2026-10-09. Follow this with `docs/HANDOFF.md` §7. This does **not** approve `TRADING_MODE=LIVE`.

## Why this window

Post-gate book (strictly ≥2026-09-10, n=83): 35W/48L, **42.2%** win rate, **+$26.71 net** of the $0.40 round trip (+$0.32/trade). That is above the cost-adjusted breakeven (41.3%) but unproven: t = +0.96, day-block bootstrap 80% (gate wants 90%), best 5 trades are 114% of net, cost cover 1.8× (gate wants 2.0×). Bar timeframe stays **M5** through micro-live. M15/H1/H4 is an offline backtest, not a reason to delay Stage A.

Working micro-live window: **2026-12-08 → 2026-12-19**. 0.01 lot, weekdays, M5, hard stop −$30. Statistical confirmation (~703 post-gate trades) is a mid-2027 story and is not required before this probe.

## Calendar

| Window | Stage | Exit that must be true before the next window | Slip rule |
|---|---|---|---|
| week of 2026-10-12 | user go on Stage A + install `mt5quotes-btc` | logger writes a real `OK` row; Stage A branch opened | if either start slips past 2026-10-19, move the December window by the same number of days |
| 2026-10-13 → 2026-10-24 | **A** order-path PR + Wine executor + kill switches | `live_path_probe.py` exits 0; `TRADING_MODE` is an env var defaulting to `FORWARD_TEST` | do not open demo orders on a probe that is not clean |
| 2026-10-12 → ~2026-10-26 | **B-i** logger clock (≥14 UTC days, 2 weekends, incl. XM DST 10-24/25) | `xm_quote_report.py` prints `Stage B-i exit: MET` | a stale logger resets the 14-day clock; do not start Stage C on a partial clock |
| ~2026-10-16 | data checkpoint only | 100 strictly post-gate trades; re-run `live_readiness.py --spread 0.40` | a failed data gate does **not** block A/B; it blocks treating the edge as confirmed |
| 2026-10-27 → 2026-11-14 | **C** XM demo through the real order path | ≥30 closed demo trades, ≥2 weekends, parity ≥90%, 0 orphaned/missed exits, median all-in cost ≤ $0.60 | any orphaned position aborts C and returns to A |
| 2026-11-16 → 2026-12-05 | **D prep** weekday-only micro-live checklist | kill switches tested on demo; equity floor −$30; manual halt file; position-aware dead-man | do not fund the micro account until this checklist is checked in the handoff |
| **2026-12-08 → 2026-12-19** | **D** micro-live, 0.01 lot, weekdays, M5, hard stop −$30 | ≥50 micro trades before any lot change | miss this window → next review is January 2027, not a silent slip into Christmas illiquidity |
| after D | **E** no scale-up | ≥100 live trades and a positive lower-80% bound | — |

## Still needed from the operator

1. Approve starting Stage A (order-path PR: findings 1–7 and 9 in `docs/REVIEW-2026-10-01.md` §6, plus the Wine order executor).
2. Install the XM logger sidecar (`docs/XM-LOGGER.md` §3) in the week of 2026-10-12 so the 14-day clock covers the 10-24/25 server-DST weekend.

Keep `TRADING_MODE = FORWARD_TEST` until Stage A exits 0, Stage B-i is MET, and Stage C's demo exit is met.
