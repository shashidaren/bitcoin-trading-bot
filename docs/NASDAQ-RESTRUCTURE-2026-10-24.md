# Nasdaq-100 (`US100Cash` M15) Architecture & VPS Cutover — 2026-10-24

## Summary of Architecture

1. **Instrument & Timeframe (`US100Cash`, `M15`):**
   - Trades XM's **Nasdaq-100 Cash Index CFD (`US100Cash`)** on **15-minute (`M15`)** candles (`CANDLE_SECONDS = 900`, `LOT_SIZE = 0.10`, `CONTRACT_SIZE = 1.0`, `$0.10/pt`, `$0.25` assumed spread).
   - Note: In XM MT5 Market Watch, select **`US100Cash`** (Cash Indices), *not* `Nasdaq` (`Nasdaq Inc (NDAQ.OQ)` corporate single-stock CFD).
2. **Clean Day-0 Ledger:**
   - All prior legacy data and archives were discarded; `trades.csv`, `forward_test_log.csv`, `skipped_trades.csv`, and `status.json` start clean at `$200.00` equity (`0W/0L`).
3. **Zero-Wait Indicator Warm-Up (`mt5_warmup_candles.json`):**
   - `tools/mt5_feed.py` exports 250 closed `M15` bars on startup so `engine.py` warms `EMA200` (50h), `EMA50`, `RSI(14)`, and `ATR(14)` immediately on boot.
   - `tools/mt5_quotes.py` backfills up to `12,000` `M15` bars (~6 months) into `xm_data/candles_m15.csv` on its first cycle for immediate `tools/backtest.py` evaluation.
4. **US Exchange Hours & Session Blackouts (`America/New_York`, DST-aware):**
   - `trade_filter.py` enforces CME weekend/daily-break quiet hours (`is_market_quiet`) and blocks entries around `08:30 ET` macro drops, `09:30 ET` NASDAQ cash open whip-saws, and `16:45–18:15 ET` CME close/rollover spread spikes.
5. **Hardened LIVE Execution (`engine.py` + `tools/mt5_executor.py`):**
   - Dormant (`MT5_EXEC_ENABLED=0`) and demo-locked (`MT5_EXEC_ALLOW_REAL=0`) by default; bridges Linux -> Wine via `/opt/nasdaq/mt5_bridge/` with `intent_id` idempotency, `None`-result quarantine, `/opt/nasdaq/HALT` emergency flatten, live spread/volume guards, and `position_id` deal reconciliation.

---

## Step-by-Step Server Cutover (`/opt/nasdaq`)

Run these commands on your Ubuntu VPS:

```bash
# 1. Disable old cron entry FIRST so old autosync cannot push old data
sudo crontab -l 2>/dev/null | grep -v '/opt/bitcoin/tools/autosync.sh' | sudo crontab - || true

# 2. Stop & remove old services
for svc in bitcoin-engine bitcoin-dashboard mt5feed mt5quotes-btc; do
    sudo systemctl stop "$svc" 2>/dev/null || true
    sudo systemctl disable "$svc" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${svc}.service"
done
sudo systemctl daemon-reload

# 3. Move directory to /opt/nasdaq, sync to origin/main, and ensure clean Day-0 state
sudo mv /opt/bitcoin /opt/nasdaq
cd /opt/nasdaq
git fetch origin main
git checkout main
git reset --hard origin/main
rm -f /opt/nasdaq/mt5_last_candle.json /opt/nasdaq/mt5_warmup_candles.json /opt/nasdaq/journal.csv
rm -rf /opt/nasdaq/xm_data /opt/nasdaq/mt5_bridge

# Ensure Day-0 clean Nasdaq data files (in case old cron pushed one last tick before step 1):
printf 'Trade_Num,Trade_Type,Entry_Time,Exit_Time,Entry_Price,Stop_Loss,Take_Profit,Exit_Price,Exit_Reason,Profit,Balance_After,RSI_At_Entry,ATR_At_Entry,Wick_Ratio_At_Entry,EMA50_At_Entry,EMA200_At_Entry\n' > /opt/nasdaq/trades.csv
printf 'Timestamp,Open,High,Low,Close,Wick_Ratio,Volume,Vol_MA,Vol_Confirmed,Dynamic_Floor,EMA_50,EMA_200,Trend_Confirmed,Tested_Floor,Valid_Rejection,Held_Floor,RSI,ATR\n' > /opt/nasdaq/forward_test_log.csv
printf 'Timestamp,Reason,Price,ATR\n' > /opt/nasdaq/skipped_trades.csv
cat > /opt/nasdaq/status.json <<'EOF'
{
  "symbol": "US100Cash",
  "mode": "FORWARD_TEST",
  "data_source": "MT5",
  "timeframe": "M15",
  "equity": 200.0,
  "total_trades": 0,
  "next_trade_num": 1,
  "wins": 0,
  "losses": 0,
  "win_rate": 0.0,
  "daily_losses": 0,
  "max_daily_losses": 3,
  "trade_active": false,
  "trade_type": null,
  "entry_price": null,
  "stop_loss": null,
  "take_profit": null,
  "entry_time": null,
  "current_trade_num": null,
  "last_update": "2026-10-24 00:00:00",
  "funnel": {}
}
EOF

# Fix virtualenv shebangs if /opt/bitcoin/venv was moved -> recreate venv cleanly in 15s:
rm -rf /opt/nasdaq/venv
python3 -m venv /opt/nasdaq/venv
/opt/nasdaq/venv/bin/pip install --upgrade pip flask python-dotenv requests

# 4. In your Wine MT5 terminal GUI (~/.mt5):
#    Right-click Market Watch -> Symbols -> Cash Indices -> double-click US100Cash to enable it!

# 5. Install & start the 5 Nasdaq systemd services
LINUX_USER="${SUDO_USER:-$USER}"
for pair in mt5feed:mt5feed-nasdaq mt5quotes:mt5quotes-nasdaq mt5exec:mt5exec-nasdaq \
            nasdaq-engine:nasdaq-engine nasdaq-dashboard:nasdaq-dashboard; do
    src="${pair%%:*}"
    dst="${pair##*:}"
    sudo cp "/opt/nasdaq/deploy/${src}.service" "/etc/systemd/system/${dst}.service"
    sudo sed -i "s/YOUR_LINUX_USER/${LINUX_USER}/g" "/etc/systemd/system/${dst}.service"
done
sudo systemctl daemon-reload
sudo systemctl enable --now mt5feed-nasdaq mt5quotes-nasdaq mt5exec-nasdaq nasdaq-engine nasdaq-dashboard

# 6. Install the new 15-minute Nasdaq autosync cron job (as root)
( sudo crontab -l 2>/dev/null | grep -v 'autosync\.sh' ; echo '*/15 * * * * /opt/nasdaq/tools/autosync.sh >> /var/log/nasdaq-autosync.log 2>&1' ) | sudo crontab -

# 7. Verify everything after ~60 seconds
systemctl status mt5feed-nasdaq mt5quotes-nasdaq mt5exec-nasdaq nasdaq-engine nasdaq-dashboard --no-pager
python3 /opt/nasdaq/tools/xm_quote_report.py
python3 /opt/nasdaq/tools/backtest.py /opt/nasdaq/xm_data/candles_m15.csv --spread 0.25
```
