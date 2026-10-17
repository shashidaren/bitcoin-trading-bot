#!/usr/bin/env python3
import os
import csv
import json
from flask import Flask, render_template_string

import pressure as tape_pressure

app = Flask(__name__)

DATA_DIR = os.getenv("BTC_DATA_DIR", "/opt/bitcoin")
LOG_FILE_PATH = os.getenv("BTC_LOG_FILE", os.path.join(DATA_DIR, "forward_test_log.csv"))
STATUS_FILE_PATH = os.getenv("BTC_STATUS_FILE", os.path.join(DATA_DIR, "status.json"))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bitcoin Trading Engine Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <meta http-equiv="refresh" content="5">
</head>
<body class="bg-slate-900 text-slate-100 font-sans p-6">
    <div class="max-w-7xl mx-auto">

        <!-- Header -->
        <header class="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 border-b border-slate-800 pb-4 gap-4">
            <div>
                <h1 class="text-3xl font-bold text-orange-400">&#8383; Bitcoin Engine Dashboard</h1>
                <p class="text-slate-400 text-sm">
                    BTC/USD Bidirectional M5 &bull; Auto-refreshes every 5s &bull; Last update: {{ status.last_update or '&mdash;' }}
                </p>
            </div>
            <div class="flex items-center gap-4">
                <div class="bg-slate-800 px-4 py-2 rounded-xl border border-slate-700 text-right">
                    <span class="text-xs text-slate-400 block">Daily SLs (Max {{ status.max_daily_losses or 3 }})</span>
                    <span class="text-xl font-bold {{ 'text-rose-400' if (status.daily_losses or 0) >= (status.max_daily_losses or 3) else 'text-slate-200' }}">
                        {{ status.daily_losses or 0 }} / {{ status.max_daily_losses or 3 }}
                        {% if (status.daily_losses or 0) >= (status.max_daily_losses or 3) %}
                        <span class="text-xs bg-rose-900/60 text-rose-300 px-2 py-0.5 rounded ml-1 font-semibold">HALTED</span>
                        {% endif %}
                    </span>
                </div>
                <div class="bg-slate-800 px-5 py-3 rounded-xl border border-slate-700 text-right">
                    <span class="text-xs text-slate-400 block">Simulated Equity</span>
                    <span class="text-3xl font-semibold {{ 'text-emerald-400' if status.equity >= 200 else 'text-rose-400' }}">
                        ${{ "%.2f"|format(status.equity) }}
                    </span>
                </div>
            </div>
        </header>

        <!-- Main Stats -->
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-4 mb-6">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Closed Trades</p>
                <p class="text-2xl font-bold text-orange-400">{{ status.total_trades }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Wins</p>
                <p class="text-2xl font-bold text-emerald-400">{{ status.wins }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Losses</p>
                <p class="text-2xl font-bold text-rose-400">{{ status.losses }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Win Rate</p>
                <p class="text-2xl font-bold text-blue-400">{{ status.win_rate }}%</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Next Trade #</p>
                <p class="text-2xl font-bold text-cyan-400">{{ status.next_trade_num or '&mdash;' }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Active Trade</p>
                <p class="text-2xl font-bold {{ 'text-emerald-400' if status.trade_active else 'text-slate-500' }}">
                    {% if status.trade_active %}
                        {{ status.trade_type or 'BUY' }}
                    {% else %}
                        No
                    {% endif %}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Total Candles</p>
                <p class="text-2xl font-bold">{{ total }}</p>
            </div>
        </div>

        <!-- Active Trade Panel -->
        {% if status.trade_active %}
        <div class="bg-slate-800 border {{ 'border-emerald-600/50' if status.trade_type == 'BUY' else 'border-rose-600/50' }} rounded-xl p-4 mb-6">
            <div class="flex items-center justify-between mb-2">
                <p class="text-sm font-semibold {{ 'text-emerald-400' if status.trade_type == 'BUY' else 'text-rose-400' }}">
                    Active {{ status.trade_type or 'BUY' }} Position (#{{ status.current_trade_num or '&mdash;' }})
                </p>
                <span class="text-xs text-slate-400">Entered: {{ status.entry_time or '&mdash;' }}</span>
            </div>
            <div class="grid grid-cols-3 gap-4 text-sm">
                <div>
                    <span class="text-slate-400">Entry</span><br>
                    <span class="text-lg font-semibold">${{ "%.2f"|format(status.entry_price or 0) }}</span>
                </div>
                <div>
                    <span class="text-slate-400">Stop Loss</span><br>
                    <span class="text-lg font-semibold text-rose-400">${{ "%.2f"|format(status.stop_loss or 0) }}</span>
                </div>
                <div>
                    <span class="text-slate-400">Take Profit</span><br>
                    <span class="text-lg font-semibold text-emerald-400">${{ "%.2f"|format(status.take_profit or 0) }}</span>
                </div>
            </div>
        </div>
        {% endif %}

        <!-- Indicator Snapshot -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">EMA 50</p>
                <p class="text-xl font-bold text-cyan-400">
                    {% if status.ema_fast %}{{ "%.2f"|format(status.ema_fast) }}{% else %}&mdash;{% endif %}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">EMA 200</p>
                <p class="text-xl font-bold text-blue-400">
                    {% if status.ema_slow %}{{ "%.2f"|format(status.ema_slow) }}{% else %}&mdash;{% endif %}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">RSI (14)</p>
                <p class="text-xl font-bold text-purple-400">
                    {% if status.rsi %}{{ "%.1f"|format(status.rsi) }}{% else %}&mdash;{% endif %}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">ATR (14)</p>
                <p class="text-xl font-bold text-orange-400">
                    {% if status.atr %}{{ "%.2f"|format(status.atr) }}{% else %}&mdash;{% endif %}
                </p>
            </div>
        </div>

        <!-- Descriptive tape-pressure read (never an entry/exit signal) -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
            <section class="lg:col-span-2 bg-slate-800 p-5 rounded-xl border border-slate-700">
                <div class="flex flex-wrap items-start justify-between gap-3 mb-4">
                    <div>
                        <h2 class="text-lg font-semibold text-slate-100">Buy / Sell Tape Pressure</h2>
                        <p class="text-xs text-slate-400">{{ pressure.window if pressure else 60 }} closed M5 bars · five-hour context · {{ pressure.as_of if pressure and pressure.as_of else 'warming up' }}</p>
                    </div>
                    <span class="text-xs px-2.5 py-1 rounded-full bg-amber-900/40 text-amber-300 border border-amber-700/40">Context only · not a signal</span>
                </div>
                {% if pressure %}
                <div class="flex items-center justify-between text-sm mb-2">
                    <span class="font-semibold text-emerald-400">BUY {{ "%.1f"|format(pressure.buy_pct) }}%</span>
                    <span class="text-slate-300">{{ pressure.label }}</span>
                    <span class="font-semibold text-rose-400">SELL {{ "%.1f"|format(pressure.sell_pct) }}%</span>
                </div>
                <div class="h-3 w-full rounded-full overflow-hidden bg-rose-500/80 flex mb-5" role="img" aria-label="Buy pressure {{ '%.1f'|format(pressure.buy_pct) }} percent; sell pressure {{ '%.1f'|format(pressure.sell_pct) }} percent">
                    <div class="h-full bg-emerald-500" style="width: {{ '%.2f'|format(pressure.buy_pct) }}%"></div>
                    <div class="h-full bg-rose-500" style="width: {{ '%.2f'|format(pressure.sell_pct) }}%"></div>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
                    {% for item in pressure.components %}
                    <div>
                        <div class="flex justify-between gap-2 text-xs mb-1">
                            <span class="text-slate-300">{{ item.label }} <span class="text-slate-500">({{ "%.0f"|format(item.weight * 100) }}%)</span></span>
                            <span class="font-mono text-slate-300">{{ item.raw }} {{ item.unit }}</span>
                        </div>
                        <div class="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                            <div class="h-full bg-cyan-500 rounded-full" style="width: {{ '%.2f'|format(item.buy_pct) }}%"></div>
                        </div>
                    </div>
                    {% endfor %}
                </div>
                <p class="mt-4 text-xs text-slate-500">Weighted descriptive composite of tick-count-weighted candle flow, 60-bar momentum, EMA trend, EMA slope and RSI. EMA trend/slope also gate this strategy, so the dial can echo the permitted trade side; it is not a probability or a proven predictor.</p>
                {% else %}
                <p class="text-sm text-slate-400 py-8 text-center">Waiting for enough valid candles and indicators to calculate the five-hour read.</p>
                {% endif %}
            </section>

            <section class="bg-slate-800 p-5 rounded-xl border border-slate-700">
                <h2 class="text-lg font-semibold text-slate-100 mb-1">20-bar Location</h2>
                <p class="text-xs text-slate-400 mb-5">Current close against the previous 20 M5 candle range</p>
                {% if location %}
                <div class="mb-4">
                    <div class="flex justify-between text-xs text-slate-400 mb-1"><span>Floor ${{ "%.2f"|format(location.floor) }}</span><span>Ceiling ${{ "%.2f"|format(location.ceiling) }}</span></div>
                    <div class="relative h-2 rounded-full bg-slate-700">
                        {% set loc_pct = (((location.close - location.floor) / (location.ceiling - location.floor)) * 100) if location.ceiling > location.floor else 50 %}
                        <div class="absolute -top-1 h-4 w-1 rounded bg-orange-400" style="left: {{ '%.2f'|format([0, [loc_pct, 100]|min]|max) }}%"></div>
                    </div>
                    <div class="text-center text-sm font-semibold text-orange-300 mt-2">Close ${{ "%.2f"|format(location.close) }}</div>
                </div>
                <div class="grid grid-cols-2 gap-3 text-sm">
                    <div class="bg-slate-900/60 p-3 rounded-lg"><span class="text-xs text-slate-400">Above floor</span><br><span class="font-semibold">{{ "%.2f"|format(location.floor_atr) if location.floor_atr is not none else '—' }} ATR</span></div>
                    <div class="bg-slate-900/60 p-3 rounded-lg"><span class="text-xs text-slate-400">Below ceiling</span><br><span class="font-semibold">{{ "%.2f"|format(location.ceiling_atr) if location.ceiling_atr is not none else '—' }} ATR</span></div>
                </div>
                {% if location.floor_logged is not none and (location.floor_logged - location.floor)|abs > 0.02 %}
                <p class="text-xs text-amber-300 mt-3">Level check: recomputed floor differs from logged floor by ${{ "%.2f"|format((location.floor_logged - location.floor)|abs) }}.</p>
                {% endif %}
                {% else %}
                <p class="text-sm text-slate-400 py-8 text-center">Waiting for at least 21 usable candles.</p>
                {% endif %}
                <p class="text-xs text-slate-500 mt-4">Location only. The panel does not evaluate or alter risk gates.</p>
            </section>
        </div>

        <!-- Funnel Stats -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
            <!-- Long Funnel -->
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <h3 class="text-sm font-semibold text-emerald-400 mb-3">Buy (Long) Funnel</h3>
                <div class="grid grid-cols-3 gap-2 text-xs">
                    <div><span class="text-slate-400">Tested Floor:</span> <span class="font-bold text-blue-400">{{ funnel.tested_floor or 0 }}</span></div>
                    <div><span class="text-slate-400">Valid Rej:</span> <span class="font-bold text-orange-400">{{ funnel.valid_rejection or 0 }}</span></div>
                    <div><span class="text-slate-400">Held Floor:</span> <span class="font-bold text-emerald-400">{{ funnel.held_support or 0 }}</span></div>
                    <div><span class="text-slate-400">Trend OK:</span> <span class="font-bold text-cyan-400">{{ funnel.trend_confirmed or 0 }}</span></div>
                    <div><span class="text-slate-400">Slope OK:</span> <span class="font-bold text-purple-400">{{ funnel.slope_confirmed or 0 }}</span></div>
                    <div><span class="text-slate-400">All Confirmed:</span> <span class="font-bold text-emerald-300">{{ funnel.all_confirmed or 0 }}</span></div>
                </div>
            </div>

            <!-- Short Funnel -->
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <h3 class="text-sm font-semibold text-rose-400 mb-3">Sell (Short) Funnel</h3>
                <div class="grid grid-cols-3 gap-2 text-xs">
                    <div><span class="text-slate-400">Tested Ceil:</span> <span class="font-bold text-blue-400">{{ funnel.sell_tested_ceiling or 0 }}</span></div>
                    <div><span class="text-slate-400">Valid Rej:</span> <span class="font-bold text-orange-400">{{ funnel.sell_valid_rejection or 0 }}</span></div>
                    <div><span class="text-slate-400">Held Ceil:</span> <span class="font-bold text-rose-400">{{ funnel.sell_held_resistance or 0 }}</span></div>
                    <div><span class="text-slate-400">Trend OK:</span> <span class="font-bold text-cyan-400">{{ funnel.sell_trend_confirmed or 0 }}</span></div>
                    <div><span class="text-slate-400">Slope OK:</span> <span class="font-bold text-purple-400">{{ funnel.sell_slope_confirmed or 0 }}</span></div>
                    <div><span class="text-slate-400">All Confirmed:</span> <span class="font-bold text-rose-300">{{ funnel.sell_all_confirmed or 0 }}</span></div>
                </div>
            </div>
        </div>

        <!-- Candle Log -->
        <div class="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-700 font-semibold text-slate-200">
                Recent Candle Log (last 30)
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm text-slate-300">
                    <thead class="bg-slate-900/50 text-slate-400 uppercase text-xs">
                        <tr>
                            <th class="px-3 py-3">Timestamp</th>
                            <th class="px-3 py-3">Close</th>
                            <th class="px-3 py-3">Wick %</th>
                            <th class="px-3 py-3">Floor</th>
                            <th class="px-3 py-3">EMA50</th>
                            <th class="px-3 py-3">EMA200</th>
                            <th class="px-3 py-3">RSI</th>
                            <th class="px-3 py-3">Trend</th>
                            <th class="px-3 py-3">Tested</th>
                            <th class="px-3 py-3">Held</th>
                            <th class="px-3 py-3">Rejection</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-700">
                        {% for row in rows %}
                        <tr class="hover:bg-slate-700/40">
                            <td class="px-3 py-2 font-mono text-xs">{{ row.Timestamp or '&mdash;' }}</td>
                            <td class="px-3 py-2 font-semibold">
                                {% if not row.Close or row.Close == 'Calculating' %}&mdash;{% else %}${{ row.Close }}{% endif %}
                            </td>
                            <td class="px-3 py-2">{{ row.Wick_Ratio or '&mdash;' }}</td>
                            <td class="px-3 py-2">
                                {% if not row.Dynamic_Floor or row.Dynamic_Floor == 'Calculating' %}&mdash;{% else %}${{ row.Dynamic_Floor }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                {% if not row.EMA_50 or row.EMA_50 == 'Calculating' %}&mdash;{% else %}${{ row.EMA_50 }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                {% if not row.EMA_200 or row.EMA_200 == 'Calculating' %}&mdash;{% else %}${{ row.EMA_200 }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                {% if not row.RSI or row.RSI == 'Calculating' %}&mdash;{% else %}{{ row.RSI }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs
                                    {{ 'bg-emerald-900/50 text-emerald-400' if row.Trend_Confirmed == 'True' else 'bg-rose-900/50 text-rose-400' }}">
                                    {{ row.Trend_Confirmed or 'False' }}
                                </span>
                            </td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs
                                    {{ 'bg-blue-900/50 text-blue-400' if row.Tested_Floor == 'True' else 'bg-slate-700 text-slate-500' }}">
                                    {{ row.Tested_Floor or 'False' }}
                                </span>
                            </td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs
                                    {{ 'bg-emerald-900/50 text-emerald-400' if row.Held_Floor == 'True' else 'bg-slate-700 text-slate-500' }}">
                                    {{ row.Held_Floor or 'False' }}
                                </span>
                            </td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs
                                    {{ 'bg-orange-900/50 text-orange-400' if row.Valid_Rejection == 'True' else 'bg-slate-700 text-slate-500' }}">
                                    {{ row.Valid_Rejection or 'False' }}
                                </span>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

    </div>
</body>
</html>
"""

@app.route("/")
def index():
    status = {
        "symbol": "BTC/USD",
        "equity": 200.00,
        "total_trades": 0,
        "next_trade_num": None,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "trade_active": False,
        "trade_type": None,
        "daily_losses": 0,
        "max_daily_losses": 3,
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "last_update": None,
        "rsi": None,
        "ema_fast": None,
        "ema_slow": None,
        "atr": None,
        "funnel": {},
    }

    if os.path.isfile(STATUS_FILE_PATH):
        try:
            with open(STATUS_FILE_PATH) as f:
                status.update(json.load(f))
        except Exception:
            pass

    funnel = status.get("funnel") or {}
    rows = []
    total_rows = 0

    if os.path.isfile(LOG_FILE_PATH):
        try:
            with open(LOG_FILE_PATH, mode="r") as f:
                reader = csv.DictReader(f)
                for line in reader:
                    rows.append(line)
                    total_rows += 1
        except Exception as e:
            print(f"Error reading log: {e}")

    pressure_read = tape_pressure.pressure(rows[-500:])
    location_read = tape_pressure.location(rows[-25:])
    recent_rows = list(reversed(rows))[:30]

    return render_template_string(
        HTML_TEMPLATE,
        rows=recent_rows,
        status=status,
        total=total_rows,
        funnel=funnel,
        pressure=pressure_read,
        location=location_read,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6001)
