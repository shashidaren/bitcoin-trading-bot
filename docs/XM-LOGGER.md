# XM-LOGGER — Read-Only `US100Cash` Quote, Spec & M15 Shadow Logger

`tools/mt5_quotes.py` is a strictly **read-only** Wine Python sidecar (`mt5quotes-nasdaq.service`) that records live XM **`US100Cash`** bid/ask spreads, contract specifications, and closed `M15` shadow candles into `/opt/nasdaq/xm_data/`.

## Guarantees

1. **Zero trading capability:** AST-verified in `tools/smoke_test.py` never to reference `order_send`, `order_check`, `positions_get`, or any trading API (`FORBIDDEN_API`).
2. **Zero account PII leaked to Git:** `symbol_spec.json` and `symbol_spec_history.jsonl` strip account numbers, server names, holder names, balances, and Windows paths before writing.
3. **Broker-time -> UTC alignment:** Estimates the XM server's UTC offset (`+2h` / `+3h`) strictly from fresh live ticks and converts every `M15` bar timestamp to exact UTC (`bar_close_utc`), healing across broker DST transitions.
4. **CME Market-Hours Aware:** Suppresses its 15-minute exit-2 watchdog during CME weekend closure (`Fri 16:55 ET -> Sun 18:10 ET`) and the daily `16:55–18:10 ET` maintenance break.
5. **12,000-Bar Startup Backfill:** Backfills up to `12,000` closed `M15` bars (~6 months of `US100Cash`) into `xm_data/candles_m15.csv` on startup so `tools/backtest.py` has a deep sample immediately.

## Files Written Under `/opt/nasdaq/xm_data/`

- `quotes-YYYY-MM-DD.csv` — 30-second live `bid`, `ask`, `spread` (`OK` / `STALE` / `NOQUOTE` / `BADQUOTE` / `NOOFFSET`)
- `candles_m15.csv` — continuous UTC `M15` OHLC + tick volume (`bar_close_utc`, `open`, `high`, `low`, `close`, `tick_volume`, `spread_pts`)
- `symbol_spec.json` & `symbol_spec_history.jsonl` — sanitized `US100Cash` contract spec (`contract_size`, `volume_min`, `filling_mode`, `calc_profit_usd_0.10lot_plus_100pts`, `calc_margin_usd_0.10lot`, swaps)

## Reporting & Parity Verification

```bash
# Full spread, session-blackout, contract-spec, and M15 parity report:
python3 tools/xm_quote_report.py

# Single-line liveness check used by tools/autosync.sh:
python3 tools/xm_quote_report.py --quiet

# Backtest the 12,000 backfilled XM M15 candles at $0.25/trade:
python3 tools/backtest.py xm_data/candles_m15.csv --spread 0.25
```

## Wine Python Setup: `tzdata` for `America/New_York`

The sidecars run under the **Wine** interpreter (`C:/Python312/python.exe`). Windows Python ships **no IANA timezone database**, so `ZoneInfo("America/New_York")` raises `ZoneInfoNotFoundError` until `tzdata` is installed *into that same interpreter* (the Linux `/opt/nasdaq/venv` is irrelevant — it never runs the Wine sidecars).

```bash
# One-time, under the same WINEPREFIX the MT5 terminal and systemd units use.
# The live VPS runs as root, so the prefix is /root/.mt5 (NOT /home/root/.mt5):
export WINEPREFIX=/root/.mt5
wine C:/Python312/python.exe -m pip install tzdata

# Verify the interpreter can now resolve US Eastern:
WINEPREFIX=/root/.mt5 wine C:/Python312/python.exe -c \
  "from zoneinfo import ZoneInfo; print(ZoneInfo('America/New_York'))"
```

**Fallback (never blocks the logger):** if `tzdata` is missing, `tools/mt5_quotes.py` and `trade_filter.py` catch `ZoneInfoNotFoundError` and fall back to a stdlib fixed-rule US Eastern `tzinfo` (`USEasternFallback`):

- DST starts 2nd Sunday of March `02:00 EST -> 03:00 EDT` (`07:00 UTC`)
- DST ends 1st Sunday of November `02:00 EDT -> 01:00 EST` (`06:00 UTC`)

That reproduces the post-2007 IANA rules exactly for EDT/EST (verified in `tools/smoke_test.py` across both 2026 transitions), so weekend closure, the `16:55–18:10 ET` CME break, and the `08:25–08:40 / 09:25–09:45 / 16:45–18:15 ET` blackouts stay aligned either way. Always install `tzdata` anyway: `zoneinfo` is the authority for historical/future rule changes.

### Quick Wine-side sanity checks

```bash
# Which prefix/interpreters are actually in play (root -> /root/.mt5):
systemctl show mt5quotes-nasdaq -p Environment | tr ' ' '\n' | grep WINEPREFIX
ls -d /root/.mt5 /root/.mt5/drive_c/Python312 2>/dev/null

# Confirm the logged-in terminal exposes US100Cash in Market Watch:
WINEPREFIX=/root/.mt5 wine C:/Python312/python.exe -c \
  "import MetaTrader5 as mt5; mt5.initialize(); print(mt5.symbol_select('US100Cash', True), mt5.symbol_info('US100Cash').spread)"
```
