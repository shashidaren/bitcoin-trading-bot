#!/usr/bin/env python3
import csv
import json
import os
import time
from flask import Flask, render_template_string

import feed_health
import pressure as tape_pressure

app = Flask(__name__)

DATA_DIR = os.getenv("NASDAQ_DATA_DIR", "/opt/nasdaq")
LOG_FILE_PATH = os.getenv("NASDAQ_LOG_FILE", os.path.join(DATA_DIR, "forward_test_log.csv"))
STATUS_FILE_PATH = os.getenv("NASDAQ_STATUS_FILE", os.path.join(DATA_DIR, "status.json"))
TRADES_FILE_PATH = os.getenv("NASDAQ_TRADES_FILE", os.path.join(DATA_DIR, "trades.csv"))
JOURNAL_FILE_PATH = os.getenv("NASDAQ_JOURNAL_FILE", os.path.join(DATA_DIR, "journal.csv"))
MT5_FEED_FILE = os.getenv("MT5_FEED_FILE", os.path.join(DATA_DIR, "mt5_last_candle.json"))
MT5_FEED_HEALTH_FILE = os.getenv("MT5_FEED_HEALTH_FILE", os.path.join(DATA_DIR, "mt5_feed_health.json"))


def feed_banner(status, health_path=None, feed_path=None, now_epoch=None):
    """Read-only feed verdict for the dashboard header.

    Shows WHY there is no fresh M15 bar (missing file / foreign symbol / frozen
    candle / silent sidecar) instead of only that the funnel is idle.
    """
    health_path = health_path or MT5_FEED_HEALTH_FILE
    feed_path = feed_path or MT5_FEED_FILE
    now = time.time() if now_epoch is None else float(now_epoch)
    block = (status or {}).get("feed") or {}
    health = feed_health.diagnose_sidecar_health(health_path, now)
    diag = feed_health.diagnose_feed_file(feed_path, expected_symbol=(status or {}).get("symbol"),
                                          now_epoch=now)
    reason = diag.get("reason")
    ok = bool(diag.get("ok")) or block.get("reason") == feed_health.REASON_OK

    def _mins(seconds):
        return "n/a" if seconds is None else (f"{seconds / 60:.0f} min" if seconds >= 90
                                              else f"{seconds:.0f}s")

    lines = []
    if diag.get("exists"):
        lines.append(f"last closed M15 bar: {diag.get('candle_open_utc')} UTC open "
                     f"({_mins(diag.get('candle_age_s'))} old), file written "
                     f"{_mins(diag.get('file_age_s'))} ago")
    else:
        lines.append(f"{os.path.basename(feed_path)} missing - the mt5feed sidecar is not publishing")
    sidecar = feed_health.summarize_sidecar(health)
    if sidecar:
        lines.append(sidecar)
    else:
        lines.append("no mt5feed heartbeat yet (mt5_feed_health.json)")

    return {
        "ok": ok,
        "reason": reason,
        "detail": diag.get("detail") or block.get("detail"),
        "frozen_since_utc": diag.get("frozen_since_utc") or block.get("frozen_since_utc"),
        "lines": lines,
    }

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nasdaq-100 (US100Cash) Trading Engine Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <meta http-equiv="refresh" content="5">
</head>
<body class="bg-slate-900 text-slate-100 font-sans p-6">
    <div class="max-w-7xl mx-auto">

        <!-- Tab navigation -->
        <nav class="flex gap-2 mb-6 border-b border-slate-700 pb-2">
            <button id="tab-dashboard" onclick="switchTab('dashboard')"
                class="tab-btn active bg-cyan-600 text-white px-4 py-2 rounded-lg text-sm font-semibold shadow-md">
                NDX Dashboard
            </button>
            <button id="tab-journal" onclick="switchTab('journal')"
                class="tab-btn text-slate-400 hover:text-slate-300 px-4 py-2 rounded-lg text-sm font-semibold">
                Journal (event log)
            </button>
        </nav>

        <div id="panel-dashboard" class="tab-panel">

            <!-- Header -->
        <header class="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 border-b border-slate-800 pb-4 gap-4">
            <div>
                <h1 class="text-3xl font-bold text-cyan-400">Nasdaq-100 ({{ status.symbol or 'US100Cash' }}) Engine</h1>
                <p class="text-slate-400 text-sm">
                    XM US100Cash Bidirectional M15 &bull; Auto-refreshes every 5s &bull; Last update: {{ status.last_update or '&mdash;' }}
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
                    <span class="text-xs text-slate-400 block">Engine Ledger Balance</span>
                    <span class="text-3xl font-semibold {{ 'text-emerald-400' if status.equity >= 200 else 'text-rose-400' }}">
                        ${{ "%.2f"|format(status.equity) }}
                    </span>
                    <span class="text-[10px] text-slate-500 block">0.10 lot US100Cash ($0.10/pt)</span>
                </div>
            </div>
        </header>

        {% if feed and not feed.ok %}
        <div role="status" class="bg-rose-950/60 border border-rose-700/60 text-rose-100 rounded-lg px-4 py-3 mb-5 text-sm">
            <p class="font-semibold">M15 feed problem: {{ feed.reason }}</p>
            <p class="text-rose-200/90">{{ feed.detail }}</p>
            <ul class="mt-1 text-xs text-rose-300/80 list-disc list-inside">
                {% for line in feed.lines %}<li>{{ line }}</li>{% endfor %}
            </ul>
            <p class="mt-1 text-xs text-rose-300/70">Triage: <code>python3 tools/feed_doctor.py</code></p>
        </div>
        {% endif %}

        {% if trade_stats_warning %}
        <div role="status" class="bg-amber-950/60 border border-amber-700/60 text-amber-200 rounded-lg px-4 py-3 mb-5 text-sm">
            {{ trade_stats_warning }}
        </div>
        {% endif %}

        <!-- Main Stats -->
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-4 mb-6">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Closed Trades</p>
                <p class="text-2xl font-bold text-cyan-400">{{ status.total_trades }}</p>
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
                <p class="text-xs text-slate-400">M15 Candles</p>
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
                    <span class="text-lg font-semibold">{{ "%.2f"|format(status.entry_price or 0) }}</span>
                </div>
                <div>
                    <span class="text-slate-400">Stop Loss</span><br>
                    <span class="text-lg font-semibold text-rose-400">{{ "%.2f"|format(status.stop_loss or 0) }}</span>
                </div>
                <div>
                    <span class="text-slate-400">Take Profit</span><br>
                    <span class="text-lg font-semibold text-emerald-400">{{ "%.2f"|format(status.take_profit or 0) }}</span>
                </div>
            </div>
        </div>
        {% endif %}

        <!-- Indicator Snapshot -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">EMA 50 (M15)</p>
                <p class="text-xl font-bold text-cyan-400">
                    {% if status.ema_fast %}{{ "%.2f"|format(status.ema_fast) }}{% else %}&mdash;{% endif %}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">EMA 200 (M15)</p>
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
                <p class="text-xs text-slate-400">ATR (14, pts)</p>
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
                        <p class="text-xs text-slate-400">{{ pressure.window if pressure else 60 }} closed M15 bars · 15-hour context · {{ pressure.as_of if pressure and pressure.as_of else 'warming up' }}</p>
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
                <p class="mt-4 text-xs text-slate-500">Weighted descriptive composite of tick-count-weighted M15 candle flow, 60-bar momentum, EMA trend, EMA slope and RSI. Context only; never a standalone predictor.</p>
                {% else %}
                <p class="text-sm text-slate-400 py-8 text-center">Waiting for enough valid M15 candles and indicators to calculate the 15-hour read.</p>
                {% endif %}
            </section>

            <section class="bg-slate-800 p-5 rounded-xl border border-slate-700">
                <h2 class="text-lg font-semibold text-slate-100 mb-1">20-bar M15 Location</h2>
                <p class="text-xs text-slate-400 mb-5">Current close against the previous 20 M15 candle range (5h)</p>
                {% if location %}
                <div class="mb-4">
                    <div class="flex justify-between text-xs text-slate-400 mb-1"><span>Floor {{ "%.2f"|format(location.floor) }}</span><span>Ceiling {{ "%.2f"|format(location.ceiling) }}</span></div>
                    <div class="relative h-2 rounded-full bg-slate-700">
                        {% set loc_pct = (((location.close - location.floor) / (location.ceiling - location.floor)) * 100) if location.ceiling > location.floor else 50 %}
                        <div class="absolute -top-1 h-4 w-1 rounded bg-cyan-400" style="left: {{ '%.2f'|format([0, [loc_pct, 100]|min]|max) }}%"></div>
                    </div>
                    <div class="text-center text-sm font-semibold text-cyan-300 mt-2">Close {{ "%.2f"|format(location.close) }}</div>
                </div>
                <div class="grid grid-cols-2 gap-3 text-sm">
                    <div class="bg-slate-900/60 p-3 rounded-lg"><span class="text-xs text-slate-400">Above floor</span><br><span class="font-semibold">{{ "%.2f"|format(location.floor_atr) if location.floor_atr is not none else '—' }} ATR</span></div>
                    <div class="bg-slate-900/60 p-3 rounded-lg"><span class="text-xs text-slate-400">Below ceiling</span><br><span class="font-semibold">{{ "%.2f"|format(location.ceiling_atr) if location.ceiling_atr is not none else '—' }} ATR</span></div>
                </div>
                {% if location.floor_logged is not none and (location.floor_logged - location.floor)|abs > 0.02 %}
                <p class="text-xs text-amber-300 mt-3">Level check: recomputed floor differs from logged floor by {{ "%.2f"|format((location.floor_logged - location.floor)|abs) }} pts.</p>
                {% endif %}
                {% else %}
                <p class="text-sm text-slate-400 py-8 text-center">Waiting for at least 21 usable M15 candles.</p>
                {% endif %}
                <p class="text-xs text-slate-500 mt-4">Location only. The panel does not evaluate or alter risk gates.</p>
            </section>
        </div>

        <!-- Funnel Stats -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
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
                Recent M15 Candle Log (last 30)
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
                                {% if not row.Close or row.Close == 'Calculating' %}&mdash;{% else %}{{ row.Close }}{% endif %}
                            </td>
                            <td class="px-3 py-2">{{ row.Wick_Ratio or '&mdash;' }}</td>
                            <td class="px-3 py-2">
                                {% if not row.Dynamic_Floor or row.Dynamic_Floor == 'Calculating' %}&mdash;{% else %}{{ row.Dynamic_Floor }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                {% if not row.EMA_50 or row.EMA_50 == 'Calculating' %}&mdash;{% else %}{{ row.EMA_50 }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                {% if not row.EMA_200 or row.EMA_200 == 'Calculating' %}&mdash;{% else %}{{ row.EMA_200 }}{% endif %}
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

        <!-- Journal panel -->
        <div id="panel-journal" class="tab-panel hidden">
            <div class="flex justify-between items-start md:items-center gap-3 mb-4">
                <div>
                    <h2 class="text-lg font-semibold text-slate-100">Event Journal</h2>
                    <p class="text-xs text-slate-400">
                        engine.py journals every US100Cash trade entry, exit, skip and feed alert here;
                        this tab shows the most recent 100 entries (newest first).
                    </p>
                </div>
                {% if journal_error %}
                <span class="text-xs text-rose-400 bg-rose-900/30 border border-rose-700/30 px-2 py-1 rounded">
                    {{ journal_error }}
                </span>
                {% endif %}
            </div>
            {% if journal %}
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm text-slate-300">
                    <thead class="bg-slate-900/50 text-slate-400 uppercase text-xs sticky top-0 z-10">
                        <tr>
                            <th class="px-3 py-3">Timestamp (UTC)</th>
                            <th class="px-3 py-3">Event</th>
                            <th class="px-3 py-3">Detail</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-700">
                        {% for entry in journal %}
                        <tr class="hover:bg-slate-700/40">
                            <td class="px-3 py-2 font-mono text-xs">{{ entry.Timestamp }}</td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs
                                    {{ 'bg-emerald-900/50 text-emerald-400' if entry.Event == 'TRADE_ENTRY' else
                                       'bg-rose-900/50 text-rose-400' if entry.Event == 'TRADE_EXIT' else
                                       'bg-blue-900/50 text-blue-400' if entry.Event == 'LIVE_ENTRY' else
                                       'bg-orange-900/50 text-orange-400' if entry.Event == 'LIVE_EXIT' else
                                       'bg-amber-900/50 text-amber-400' if entry.Event in ('BUY_SKIP', 'SELL_SKIP') else
                                       'bg-slate-900 text-slate-400' }}">
                                    {{ entry.Event }}
                                </span>
                            </td>
                            <td class="px-3 py-2 font-mono text-xs">{{ entry.Detail }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <p class="text-sm text-slate-500 py-8 text-center">No journal events yet.</p>
            {% endif %}
        </div>

    </div>
</body>
</html>
<script>
    var TAB_STORAGE_KEY = 'nasdaq-dashboard-tab';
    (function () {
        var saved = localStorage.getItem(TAB_STORAGE_KEY);
        if (saved) switchTab(saved);
    })();

    function switchTab(tab) {
        document.querySelectorAll('.tab-panel').forEach(function (p) {
            p.classList.add('hidden');
        });
        document.querySelectorAll('.tab-btn').forEach(function (b) {
            b.classList.remove('bg-cyan-600', 'text-white', 'shadow-md');
            b.classList.add('text-slate-400');
        });
        var panel = document.getElementById('panel-' + tab);
        if (!panel) return;
        panel.classList.remove('hidden');
        var btn = document.getElementById('tab-' + tab);
        if (btn) {
            btn.classList.remove('text-slate-400');
            btn.classList.add('bg-cyan-600', 'text-white', 'shadow-md');
        }
        localStorage.setItem(TAB_STORAGE_KEY, tab);
    }
</script>
"""


@app.route("/")
def index():
    status = {
        "symbol": "US100Cash",
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

    ledger_stats = tape_pressure.trade_summary(tape_pressure.read_rows(TRADES_FILE_PATH))
    trade_stats_warning = None
    if ledger_stats["total_trades"]:
        status_counts_match = True
        for key in ("total_trades", "wins", "losses"):
            try:
                status_counts_match = status_counts_match and int(status.get(key)) == ledger_stats[key]
            except (TypeError, ValueError):
                status_counts_match = False
        status.update(ledger_stats)
        if not status_counts_match:
            trade_stats_warning = (
                "Closed-trade counters in status.json differ from trades.csv. "
                "Showing ledger counts; the engine balance remains the internal status.json value "
                "(not all-time P/L). No engine state was modified."
            )

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

    journal = []
    journal_error = None
    if os.path.isfile(JOURNAL_FILE_PATH):
        try:
            with open(JOURNAL_FILE_PATH, newline="") as f:
                for row in csv.DictReader(f):
                    journal.append(row)
        except Exception as e:
            journal_error = f"could not read journal: {e}"
    journal = list(reversed(journal))[:100]

    return render_template_string(
        HTML_TEMPLATE,
        rows=recent_rows,
        status=status,
        total=total_rows,
        funnel=funnel,
        pressure=pressure_read,
        location=location_read,
        trade_stats_warning=trade_stats_warning,
        feed=feed_banner(status),
        journal=journal,
        journal_error=journal_error,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6001)
