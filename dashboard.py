#!/usr/bin/env python3
import csv
import json
import os
from flask import Flask, render_template_string

STATUS_FILE_PATH = "/opt/bitcoin/status.json"
LOG_FILE_PATH = "/opt/bitcoin/forward_test_log.csv"

app = Flask(__name__)

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Bitcoin Forward Test Dashboard</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body { background:#0b1120; color:#e2e8f0; font-family: -apple-system, sans-serif; margin:0; padding:24px; }
        h1 { color:#f7931a; font-size:28px; margin:0; }
        .sub { color:#94a3b8; font-size:13px; margin-top:4px; }
        .grid { display:flex; flex-wrap:wrap; gap:16px; margin-top:24px; }
        .card { background:#111827; border:1px solid #1f2937; border-radius:10px; padding:16px 20px; min-width:150px; }
        .card .label { color:#94a3b8; font-size:12px; }
        .card .value { font-size:24px; font-weight:600; margin-top:4px; }
        .equity { color:#ec4899; }
        .wins { color:#22c55e; }
        .losses { color:#ec4899; }
        .winrate { color:#3b82f6; }
        .active-trade { background:#111827; border:1px solid #f7931a; border-radius:10px; padding:16px 20px; margin-top:16px; }
        table { width:100%; border-collapse:collapse; margin-top:16px; font-size:13px; }
        th { text-align:left; color:#94a3b8; padding:8px; border-bottom:1px solid #1f2937; }
        td { padding:8px; border-bottom:1px solid #1f2937; }
        .true { color:#f7931a; background:#3f2a10; padding:2px 8px; border-radius:4px; }
        .false { color:#64748b; background:#1f2937; padding:2px 8px; border-radius:4px; }
    </style>
</head>
<body>
    <h1>&#8383; Bitcoin Forward Test Dashboard</h1>
    <div class="sub">BTC/USD - Auto-refreshes every 5s - Last status: {{ status.last_update or '-' }}</div>

    <div class="grid">
        <!-- Added |float here to prevent TypeErrors -->
        <div class="card"><div class="label">Simulated Equity</div><div class="value equity">${{ '%.2f'|format(status.equity|float) }}</div></div>
        <div class="card"><div class="label">Total Candles</div><div class="value">{{ status.funnel.candles_evaluated if status.funnel else 0 }}</div></div>
        <div class="card"><div class="label">Trades Taken</div><div class="value">{{ status.total_trades or 0 }}</div></div>
        <div class="card"><div class="label">Wins</div><div class="value wins">{{ status.wins or 0 }}</div></div>
        <div class="card"><div class="label">Losses</div><div class="value losses">{{ status.losses or 0 }}</div></div>
        <div class="card"><div class="label">Win Rate</div><div class="value winrate">{{ status.win_rate or 0 }}%</div></div>
        <div class="card"><div class="label">Open Trade</div><div class="value">{{ 'YES' if status.trade_active else 'No' }}</div></div>
    </div>

    {% if status.trade_active %}
    <div class="active-trade">
        <strong>Active Virtual Trade</strong>
        <div class="grid" style="margin-top:8px;">
            <!-- Added |float to all pricing variables below -->
            <div><div class="label" style="color:#94a3b8;font-size:12px;">Entry</div><div style="font-size:20px;">${{ '%.2f'|format(status.entry_price|float) }}</div></div>
            <div><div class="label" style="color:#94a3b8;font-size:12px;">Stop Loss</div><div style="font-size:20px;color:#ec4899;">${{ '%.2f'|format(status.stop_loss|float) }}</div></div>
            <div><div class="label" style="color:#94a3b8;font-size:12px;">Take Profit</div><div style="font-size:20px;color:#22c55e;">${{ '%.2f'|format(status.take_profit|float) }}</div></div>
        </div>
    </div>
    {% endif %}

    <div class="grid">
        <div class="card"><div class="label">EMA 50</div><div class="value" style="color:#22d3ee;">{{ status.ema_fast or '-' }}</div></div>
        <div class="card"><div class="label">EMA 200</div><div class="value" style="color:#3b82f6;">{{ status.ema_slow or '-' }}</div></div>
        <div class="card"><div class="label">RSI (14)</div><div class="value" style="color:#c084fc;">{{ status.rsi or '-' }}</div></div>
        <div class="card"><div class="label">ATR (14)</div><div class="value" style="color:#f7931a;">{{ status.atr or '-' }}</div></div>
    </div>

    {% if status.funnel %}
    <div class="grid">
        <div class="card"><div class="label">Trend Confirmed</div><div class="value" style="color:#3b82f6;">{{ status.funnel.trend_confirmed }}</div></div>
        <div class="card"><div class="label">Volume Spikes</div><div class="value" style="color:#c084fc;">{{ status.funnel.volume_confirmed }}</div></div>
        <div class="card"><div class="label">Valid Rejections</div><div class="value" style="color:#f7931a;">{{ status.funnel.valid_rejection }}</div></div>
    </div>
    {% endif %}

    <div style="margin-top:24px;">
        <h3>Recent Candle Log (last 30)</h3>
        <table>
            <tr>
                <th>TIMESTAMP</th><th>CLOSE</th><th>WICK %</th><th>FLOOR</th><th>EMA50</th><th>EMA200</th>
                <th>RSI</th><th>TREND</th><th>TESTED</th><th>HELD</th><th>REJECTION</th>
            </tr>
            {% for row in rows %}
            <tr>
                <td>{{ row.Timestamp }}</td>
                <td>${{ row.Close }}</td>
                <td>{{ row.Wick_Ratio }}</td>
                <td>${{ row.Dynamic_Floor }}</td>
                <td>${{ row.EMA_50 }}</td>
                <td>${{ row.EMA_200 }}</td>
                <td>{{ row.RSI }}</td>
                <td><span class="{{ 'true' if row.Trend_Confirmed == 'True' else 'false' }}">{{ row.Trend_Confirmed }}</span></td>
                <td><span class="{{ 'true' if row.Tested_Floor == 'True' else 'false' }}">{{ row.Tested_Floor }}</span></td>
                <td><span class="{{ 'true' if row.Held_Floor == 'True' else 'false' }}">{{ row.Held_Floor }}</span></td>
                <td><span class="{{ 'true' if row.Valid_Rejection == 'True' else 'false' }}">{{ row.Valid_Rejection }}</span></td>
            </tr>
            {% endfor %}
        </table>
    </div>
</body>
</html>
"""

def load_status():
    if not os.path.isfile(STATUS_FILE_PATH):
        return {}
    try:
        with open(STATUS_FILE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def load_recent_rows(n=30):
    if not os.path.isfile(LOG_FILE_PATH):
        return []
    try:
        with open(LOG_FILE_PATH, "r") as f:
            reader = list(csv.DictReader(f))
        return list(reversed(reader[-n:]))
    except Exception:
        return []

@app.route("/")
def index():
    status = load_status()
    rows = load_recent_rows()
    return render_template_string(TEMPLATE, status=status, rows=rows)

if __name__ == "__main__":
    # Added debug=True so you can see exact errors if anything else fails
    app.run(host="0.0.0.0", port=6001, debug=True)
