# Nasdaq-100 (`US100Cash` M15) Restructure & VPS Cutover — 2026-10-24

## Summary of Changes

1. **Instrument & Timeframe Restructure:**
   - Replaced Bitcoin (`BTCUSD` / `BTC/USD`, `M5`, 24/7, `LOT_SIZE = 0.01`, `$0.40` spread) with XM's **Nasdaq-100 Cash Index CFD (`US100Cash`)** on **15-minute (`M15`)** candles (`CANDLE_SECONDS = 900`, `LOT_SIZE = 0.10`, `CONTRACT_SIZE = 1.0`, `$0.10/pt`, `$0.25` assumed spread).
   - Note: XM's ticker `Nasdaq` (`Nasdaq Inc (NDAQ.OQ)`) is the corporate single-stock CFD (~`$85` share price, `$0.58` spread = `68 bps`); **`US100Cash`** is XM's Nasdaq-100 Cash Index CFD (~`1.2 bps` spread, 23h/day Mon–Fri).
2. **Clean Archival of BTC Era:**
   - Archived `trades.csv`, `forward_test_log.csv`, `skipped_trades.csv`, and `status.json` into `archive/btc/*_btc.*` and moved BTC review/port notes into `archive/btc/docs/`.
   - Initialized clean Day-0 `US100Cash` ledgers at `$200.00` equity.
3. **Zero-Wait Indicator Warm-Up (`mt5_warmup_candles.json`):**
   - `tools/mt5_feed.py` exports 250 closed `M15` bars on startup so `engine.py` warms `EMA200` (50 hours of M15 bars), `EMA50`, `RSI(14)`, and `ATR(14)` immediately without waiting 2+ days.
   - `tools/mt5_quotes.py` backfills up to `12,000` `M15` bars (~6 months) into `xm_data/candles_m15.csv` on its first cycle for immediate `tools/backtest.py` evaluation.
4. **US Exchange Hours & Session Blackouts (`America/New_York`, DST-aware):**
   - `trade_filter.py` enforces CME weekend/daily-break quiet hours (`is_market_quiet`) and blocks entries around `08:30 ET` macro drops, `09:30 ET` NASDAQ cash open whip-saws, and `16:45–18:15 ET` CME close/rollover spread spikes.
5. **Hardened LIVE Execution (`engine.py` + `tools/mt5_executor.py`):**
   - Fixed `SYMBOL_FILLING_*` bitmask -> `ORDER_FILLING_*` enum mapping, `position_id` exit deal reconciliation, live spread/volume/stops-level guards, `None`-result quarantine, `/opt/nasdaq/HALT` flatten switch, and Linux -> Wine `/opt/nasdaq/mt5_bridge/` IPC.

---

## Step-by-Step Server Migration (`/opt/bitcoin` -> `/opt/nasdaq`)

Run on the Ubuntu VPS once this branch is merged to `main`:

```bash
# 1. Stop old Bitcoin services & cron
sudo systemctl stop bitcoin-engine bitcoin-dashboard mt5feed mt5quotes-btc 2>/dev/null || true
sudo systemctl disable bitcoin-engine bitcoin-dashboard mt5feed mt5quotes-btc 2>/dev/null || true

# 2. Move / clone repo to /opt/nasdaq and update Wine MT5 Market Watch
sudo mv /opt/bitcoin /opt/nasdaq
cd /opt/nasdaq
git fetch origin main && git checkout main && git pull --ff-only origin main
rm -f /opt/nasdaq/mt5_last_candle.json /opt/nasdaq/mt5_warmup_candles.json
rm -rf /opt/nasdaq/xm_data

# (In the Wine MT5 GUI, right-click Market Watch -> Symbols -> Cash Indices -> enable US100Cash)

# 3. Install & start the Nasdaq systemd services (substitute $USER if running as non-root)
for unit in mt5feed:mt5feed-nasdaq mt5quotes:mt5quotes-nasdaq mt5exec:mt5exec-nasdaq \
            nasdaq-engine:nasdaq-engine nasdaq-dashboard:nasdaq-dashboard; do
    src="${unit%%:*}"
    dst="${unit##*:}"
    sudo cp "/opt/nasdaq/deploy/${src}.service" "/etc/systemd/system/${dst}.service"
    sudo sed -i "s/YOUR_LINUX_USER/$USER/g" "/etc/systemd/system/${dst}.service"
done
sudo systemctl daemon-reload
sudo systemctl enable --now mt5feed-nasdaq mt5quotes-nasdaq mt5exec-nasdaq nasdaq-engine nasdaq-dashboard

# 4. Update root cron for 15-minute autosync
# Replace /opt/bitcoin/tools/autosync.sh with:
# */15 * * * * /opt/nasdaq/tools/autosync.sh >> /var/log/nasdaq-autosync.log 2>&1

# 5. Verify health after 60 seconds
python3 /opt/nasdaq/tools/xm_quote_report.py
python3 /opt/nasdaq/tools/backtest.py /opt/nasdaq/xm_data/candles_m15.csv --spread 0.25
```
