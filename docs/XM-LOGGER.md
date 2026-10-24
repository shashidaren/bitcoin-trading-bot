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
