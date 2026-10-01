# XM quote + contract-spec logger (review §7 Stage B-i)

A **read-only** Wine sidecar that measures what the XM terminal actually charges and
offers for BTCUSD, without touching `engine.py`, `DATA_SOURCE` or the forward-test
sample. It exists to test the assumption most able to kill the edge: the paper P/L nets
a flat **$0.40** round trip, the measured **break-even is $0.87** (`docs/HANDOFF.md` §5),
and the $0.40 is **one Asian-session sample** (2026-09-15 04:06 UTC).

| | |
|---|---|
| Code | `tools/mt5_quotes.py` (sidecar) · `tools/xm_quote_report.py` (reader) |
| Unit | `deploy/mt5quotes.service` → installed as **`mt5quotes-btc`** |
| Data | `xm_data/` (committed by `tools/autosync.sh` like the other live data) |
| Tests | `tools/smoke_test.py` Scenario **K** (logger) and **L** (report) |
| Status | **Built and tested against a fake terminal. Not yet validated against the real XM terminal — §3 is that validation.** |

---

## 1. What it does

1. **Quotes** — every 30 s, one row: bid/ask/spread of the first quote after the boundary
   (the `:00`/`:05`… rows are what a bar-close signal would have filled at) plus the
   **min/max spread of the 5 s polls inside the window**, so a spike between two rows is
   not invisible. Outages are written as explicit `NOQUOTE`/`BADQUOTE`/`STALE` rows, never
   as silent holes.
2. **Shadow XM M5 candles** — one row per closed bar, **back-filled from the terminal's own
   history on first start** (default 12 000 bars ≈ 42 days; the forward-test log began
   2026-09-07) and gap-healed on every cycle. So feed parity against the Twelve Data era
   can be measured **from day one** instead of after 14 days, with no era split.
3. **Contract-spec snapshot** — execution mode, filling flags, stops/freeze level, volume
   min/step/max, contract size, swap, calc mode, demo-vs-real, terminal `maxbars`, plus an
   `order_calc_profit` probe (0.01 lot × $100 move must be **$1.00**). Re-read every 6 h;
   a **change** (XM widening the stops level, a swap change) appends a history line.

What it does **not** measure: **commission, slippage and realised swap** — `symbol_info()`
does not expose commission and slippage needs fills. Those come from Stage C demo deals.
Spread-only cost is a **lower bound** of the all-in round trip.

**Expected holes.** An XM FAQ (2022, via a partner mirror — verify on the first Saturday)
says crypto CFDs are suspended **Saturdays 10:05–10:35 server time** for maintenance, and
weekend quoting may differ from weekdays. The logger keeps writing rows through such a
window (`STALE`/`NOQUOTE`), so the report lists **runs of unusable rows** next to the gap
list; a ~30 min Saturday run is that window, not a logger fault.

## 2. What it writes (`/opt/bitcoin/xm_data/`)

`quotes-YYYY-MM-DD.csv` (UTC day files, ~200 KB/day):

| column | meaning |
|---|---|
| `ts_utc` | window start on the box clock, aligned to the 30 s grid |
| `bid`, `ask` | the **point sample** — first valid quote of the window (~1 s after the boundary) |
| `spread` | `ask − bid` of the point sample, **USD per BTC** (× 0.01 lot = $ per trade) |
| `spread_min`, `spread_max` | envelope over every poll in the window (default every 5 s) |
| `n_ok`, `n_bad` | valid / invalid polls in the window (a full window has 6) |
| `tick_age_s` | age of the point sample's tick — staleness, and a box-clock-skew detector |
| `srv_offset_s` | broker-server-time offset from UTC in force (seconds; see §5) |
| `flags` | `;`-joined: `STALE` (tick > 120 s old) · `NOQUOTE` (no tick) · `BADQUOTE` (zero/crossed) · `NOOFFSET` (offset not yet learned) · `LATE` (sample > 6.5 s after the boundary: start-up or a stall) |

`candles_m5.csv` (append-only, ascending in UTC):

| column | meaning |
|---|---|
| `bar_close_utc` | **same convention as `forward_test_log.csv`** (row T covers [T−5 m, T)) so a parity join is exact |
| `open`, `high`, `low`, `close`, `tick_volume` | the XM bar (MT5 bars are **bid**-based; the log's feed is not) |
| `spread_pts` | the terminal's per-bar spread in points — **semantics unverified**; the report cross-checks it against the live samples before trusting it |
| `time_srv`, `offset_s` | raw MT5 bar-open time (broker clock) and the offset used to convert it |

`symbol_spec.json` (latest) · `symbol_spec_history.jsonl` (one line per change). Allow-listed
fields only — see §5 *Privacy*.

## 3. Install and validate on the box (run this; the build sandbox had no Wine/MT5)

> **Before step 1 — two facts the repo cannot know** (they also tell you whether the
> existing feed sidecar is installed):
> `grep DATA_SOURCE /opt/bitcoin/.env` and `systemctl list-units | grep -i mt5`.

**Merge → autosync deploys the code.** This PR touches only `tools/`, `deploy/` and
`docs/`: autosync runs the smoke gate but **does not restart the engine** (only
`engine.py`/`trade_filter.py` changes do). Then on the box:

```bash
export WINEPREFIX=/root/.mt5
PY="xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/opt/bitcoin/tools/mt5_quotes.py"

# 1. Dry read of the contract spec. Writes nothing. Read the JSON.
$PY --spec
```
Expect: `"account_kind": "DEMO"` or `"REAL"`; `"filling_allowed_flags"`; `trade_stops_level`;
`volume_min 0.01`; `trade_contract_size 1.0`; `calc_profit_usd_0.01lot_plus_100usd 1.0`;
`terminal.maxbars`. **It must contain no login, name, server or balance** — if it does,
stop and tell the next session (that would be a bug in the allow-list).

```bash
# 2. One real cycle into a SCRATCH directory (does not touch xm_data/).
MT5_QUOTES_DIR=Z:/tmp/xm_probe $PY --once
```
Expect, in this order: `contract spec recorded` · the banner with `server offset +3h`
(summer; `+2h` after the broker's DST change) · `first run - back-filled N closed M5 bars` ·
a quote row · `candles written this run N` (Scenario K locks this order and the `--spec` /
`--backfill` behaviour). Then check the three things only the real terminal can answer:

| Check | Pass | If it fails |
|---|---|---|
| offset is a whole hour, `+2h`/`+3h` | learned from a fresh tick | `NOOFFSET` flags: market closed or box clock far off — `date -u`, `chronyc tracking` |
| back-filled N close to 12 000 | the terminal served the history | N ≈ `maxbars` (e.g. 5 000 = ~17 days): raise **Tools → Options → Charts → Max bars in chart** in the terminal, then `--backfill 12000` with the service stopped |
| `python3 tools/xm_quote_report.py --dir /tmp/xm_probe` (§4 PARITY) | says **`OK: no time shift`** and matches ≈ all log bars in range | a ±1 h shift = the server-time conversion is wrong on this broker; do **not** start the 14-day clock, open a session |

```bash
# 3. Install and start (note the -btc suffix; the gold bot owns the plain names)
sudo cp /opt/bitcoin/deploy/mt5quotes.service /etc/systemd/system/mt5quotes-btc.service
sudo systemctl daemon-reload && sudo systemctl enable --now mt5quotes-btc
journalctl -u mt5quotes-btc -f          # contract spec recorded / first run - back-filled N / hourly heartbeat

# 4. After ~1 hour
cd /opt/bitcoin && python3 tools/xm_quote_report.py | head -60
```
Optionally set `Environment=MT5_QUOTES_LABEL=XM Standard demo` in the unit (MT5 does not
expose the account tier; this free text is published in the spec — never a login).

**Within a day, confirm:** (a) `mt5quotes-btc` and `mt5feed-btc` run **side by side**
(several Python clients may attach to one terminal — assumed, not yet proven here);
(b) the autosync digest shows `📈 xm logger: OK …` and `xm_data/` appears on `main`;
(c) the engine was **not** restarted by the deploy (`systemctl status`). **The 14-day
clock starts when the first `OK` row is written — not at merge.**

## 4. Reading the report (`python3 tools/xm_quote_report.py`)

Five sections; every threshold shown is a **proposal** from `docs/REVIEW-2026-10-01.md` §7
and is decided by a human, not by this tool.

1. **LOGGER** — complete UTC days (≥ 80 % of rows) / 14 and complete weekends (Sat+Sun) / 2,
   the gap list **and** the runs of stale/absent quotes (maintenance windows), flag counts,
   blackout windows covered, tick-age (clock skew). The line `Stage B-i exit: MET` is the only
   thing that ends the wait.
2. **SPREAD** — $/BTC and $/trade by session × weekday/weekend, the engine's three blackout
   windows (read from `trade_filter.BLACKOUT_WINDOWS`, never re-declared), at the M5 bar
   close, the 5 s spike envelope, an hour-of-day profile, and the **share of samples above**
   the $0.40 assumption, the $60 hard-cap proposal, the break-even ($87/BTC) and 20/30/40 %
   of median 1R.
3. **COST** — the ledger's actual post-gate trades re-priced at the spread measured at their
   entry and exit: `(spread_in + spread_out) / 2 × 0.01`. Only trades after the logger
   started; **n < 30 is a plumbing check, not evidence.**
4. **PARITY** — XM candles vs `forward_test_log.csv`: match rate, |Δclose|/high/low, direction
   agreement, **wick ≥ 0.15 gate agreement** (the signal's key input), a ±3 h **time-shift
   scan** and per-day shift flags. The report also checks the terminal's per-bar `spread`
   against the live samples and, **only if it agrees**, prints a provisional spread history
   for the back-filled period (which can contain weekends the live clock hasn't seen yet).
5. **SPEC** — the contract facts Stage A must not guess, plus checks against the handoff's
   assumptions (contract 1.0, min lot 0.01, $1.00 per $100 at 0.01 lot).

**Reading guide (what each outcome would mean — a human decides; none of these is a gate).**
Thresholds below are only the ones `docs/REVIEW-2026-10-01.md` §7 already publishes: the
break-even round trip $0.87 (`HANDOFF` §5), the $60/BTC hard-cap *proposal*, spread as a share
of 1R, and Stage C's all-in limits ($0.60 median, $1.00 for any session/weekend bucket).

| Finding after the exit is MET | What it would mean |
|---|---|
| overall median ≈ the assumed $0.40 and no session/weekend median near $0.60 | the flat $0.40 is consistent with XM's real spread; the staged path continues unchanged |
| a session or weekend bucket median **above $1.00** (spread-only, before commission/slippage) | that bucket already breaks Stage C's per-bucket limit: replace the flat `--spread 0.40` with a **session table** and decide the weekend rule on this evidence (the ledger's weekend slice is 3W/13L on n = 16 — the logger tells you whether the *cost* explains it) |
| the post-gate gross edge ($0.87/trade) minus the **measured** COST ≤ 0 | the edge does not survive XM's real cost: the staged path stops, whatever the t-stat says |
| the share-above table at the bar close | sizes the hard cap and the share-of-1R guard from data instead of from the $60 guess: the cap should sit where it blocks the expensive tail, not the typical quote |
| wick-gate agreement clearly below 100 %, or \|Δclose\| p95 comparable to the spread | the two feeds will not take the same trades: **do not switch `DATA_SOURCE`** on candle parity alone; signal-level parity (Stage B-ii: run `engine.evaluate_candle` over the shadow candles, as `smoke_test.py` does with synthetic ones) is the next step |
| spec shows `execution` ≠ MARKET, neither `FOK` nor `IOC` flagged, or a stops level near the ATR stop distance | Stage A's order code must be designed around it before it is written (symbol *flag bits* FOK=1/IOC=2 are not the order enum FOK=0/IOC=1/RETURN=2 — the spec decodes the former) |

## 5. Design notes — the traps this tool is built around

- **MT5 `time` is broker server time, not UTC** (the Python docs say UTC; the integers are not —
  forum thread <https://www.mql5.com/en/forum/369602>). There is no API for the server zone, so
  the logger learns it from **fresh ticks**: `tick.time − now = offset − age`, rounded to the
  hour. XM runs EET/EEST (+2 winter, +3 summer), so it **changes twice a year**.
  - The offset is learned **only from a tick whose time advanced since the previous poll**.
    A tick that is *exactly N hours old* is indistinguishable from a fresh tick on a server N
    hours behind, so without this gate a weekend stale feed would silently flip the offset
    (`tools/smoke_test.py` K runs a frozen feed for >1 h to lock it; mutation-checked).
  - A **changed** offset needs 2 consecutive fresh agreeing ticks.
  - The candle resume point is kept in **UTC** and converted with the current offset, and each
    bar is converted with the current offset *or the previous one*, whichever puts it in the
    plausible window (after the last recorded bar, not in the future). That is what keeps the
    series continuous across the server's DST change — including the one bar that opens before
    the change and closes after it. Without it the straddling bar was dated an hour into the
    future and the next hour of candles was silently dropped (found by Scenario K).
  - **Limits:** bars back-filled across a DST change, or a sidecar outage that spans one, can
    be stamped one hour off. `offset_s` and the raw `time_srv` are on every row, and the report's
    per-day shift flags point at the date. The next possible changes are the broker's autumn
    switch to GMT+2 on **Sunday 25 October 2026** (XM's own trading-hours page: server time is
    GMT+2 winter / GMT+3 summer on the EU rule, last Sunday of March/October; the US switch is a
    week later, 1 Nov). Watch `server offset changed` in `journalctl -u mt5quotes-btc` that
    day. A 14-day run started in the first half of October ends before it.
- **Privacy — the repo is public.** `account_info()` carries login, name, balance and server;
  `terminal_info()` carries Windows user paths (`commondata_path` in MetaQuotes' own example
  output shows a username). Nothing is dumped: explicit allow-lists copy only non-identifying
  fields, nothing is printed with the login, and the unit/env never need credentials.
  Scenario K plants fake secrets in the fake terminal and fails if any reaches any file.
- **Read-only, by construction and by test.** The only MT5 calls are `symbol_select`,
  `symbol_info(_tick)`, `copy_rates_from_pos` (closed bars only), `account_info`,
  `terminal_info` and the pure calculators `order_calc_profit/margin`. Scenario K walks the
  source AST for 12 trading/position/history/login names and the fake terminal records any
  trading call; it also asserts the module never imports `engine`.
- **Wine writes CRLF in text mode.** Every file is opened with `newline=""` and `\n` terminators;
  K asserts no `\r` byte anywhere. A header that no longer matches moves the file **aside**
  (never append misaligned rows — how `trades.csv` once broke); a torn last line is isolated.
- **Self-healing.** No valid quote for 60 s → `shutdown()`/`initialize()` again; 15 min → exit 2
  so `Restart=always` gives a clean process. A *stale-but-valid* tick (market closed) never
  restarts it — that is data (`STALE` rows), not a fault.
- **Data volume** ≈ 200 KB/day of quotes in day files and ≈ 1 MB for the 12 000-bar candle
  back-fill (+ 23 KB/day after); git churn per autosync run is a few KB. `*.tmp` is already
  git-ignored.

## 6. Open items and what this does not prove

- **First run on the real terminal is the real test.** Every MT5 interaction was exercised only
  against a fake. Specific unknowns: whether XM serves ≥ 12 000 M5 bars (`maxbars`), what the
  per-bar `spread` field means (the report measures it rather than assuming), and whether two
  Python clients can attach to the terminal at once.
- **Demo vs real spreads.** If `account_kind` is `DEMO`, XM demo normally mirrors live pricing
  but that is not guaranteed; Stage C must confirm on the account that will trade.
- **Latent finding in the existing MT5 *feed* path (not fixed here — `engine.py` is out of
  scope and a merge touching it restarts the engine).** `tools/mt5_feed.py` publishes the raw
  **server-time** bar `ts`; `engine.run_mt5_test` seeds its dedup from the **UTC** stamp of the
  log's last row and then compares the two. With a +2/+3 h server, the freshest candle always
  looks newer than the log, so **each engine restart in `DATA_SOURCE=MT5` mode re-evaluates and
  re-logs the last bar once** (indicators advance twice for it). `HANDOFF` §3's "a restart never
  re-logs the boundary candle" is therefore only true at offset 0, and Scenario H uses toy
  timestamps so it cannot see it. It does not affect the default `TWELVEDATA` feed. **Fix when
  the data-source question is decided** (publish a UTC `ts` using this logger's offset
  estimate), in a PR that is allowed to restart the engine. Confirm the offset first:
  `jq .ts,.updated_at /opt/bitcoin/mt5_last_candle.json` then `date -u -d @<ts>` — a +2/+3 h
  difference proves it.
- **Not a trading rule.** Nothing here changes strategy, parameters or the cost used in any
  P/L. The `--spread` the other tools use stays `0.40` until a human changes it on the report's
  evidence.

## 7. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `MetaTrader5 package missing` | run with the Linux python, not the Wine one | use the `wine C:/Python312/python.exe …` form |
| `MT5 initialize failed` | terminal not running / not logged in, wrong `WINEPREFIX` | same prefix as `mt5feed-btc`; `systemctl status` it |
| `symbol_select(BTCUSD) failed` | symbol not in Market Watch / renamed | add it in the terminal; XM has `BTCUSD`, not `BTCUSDm` (verified 2026-09-15) |
| rows flagged `NOOFFSET` | no fresh tick yet (thin market / just started) or huge clock skew | wait a minute; check `date -u` |
| `server offset changed +3h -> +2h` | the broker's DST change | expected twice a year; check the report's shift flags that week |
| `schema drift in … moved to …old-…` | a file's header differs from the code | a code/schema change; the old file is kept, a fresh one started |
| autosync digest `xm logger: STALE` | the sidecar stopped writing | `systemctl status mt5quotes-btc`; `journalctl -u mt5quotes-btc -n 80` |
| `exiting for a clean restart` | 15 min without a valid quote | the unit restarts it; if it loops, the terminal is down |
