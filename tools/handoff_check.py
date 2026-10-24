#!/usr/bin/env python3
"""
Freshness gate for docs/HANDOFF.md - Nasdaq-100 (US100Cash) M15 edition.

Machine-checks the `<!-- HANDOFF-SNAPSHOT ... -->` block at the top of
docs/HANDOFF.md against live data in the repo root.

Tolerance policy: 5 closed trades and 48 hours (TRADE_TOLERANCE = 5,
MAX_AGE_HOURS = 48, BAR_TOLERANCE = MAX_AGE_HOURS * 4 = 192 M15 bars).

Usage:
  python3 tools/handoff_check.py [repo_root]      # check
  python3 tools/handoff_check.py --update         # rewrite snapshot block in place
  python3 tools/handoff_check.py --quiet          # one-line verdict (digests)
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

BEGIN_MARK = "<!-- HANDOFF-SNAPSHOT"
END_MARK = "<!-- /HANDOFF-SNAPSHOT -->"

ADVISORY = {"as_of_utc", "data_collection"}

TRADE_TOLERANCE = 5
MAX_AGE_HOURS = 48
# M15 log rows of drift before STALE = MAX_AGE_HOURS * 4 bars/hour (192 rows).
BAR_TOLERANCE = MAX_AGE_HOURS * 4
SKIP_TOLERANCE = 60

TRADE_COUNT_KEYS = {"closed_trades", "live_era_trades", "log_covered_trades"}
OUTCOME_KEYS = {"wins_losses", "win_rate_pct"}
OPEN_TRADE_KEYS = {"open_trade"}
MONEY_KEYS = {"engine_ledger_usd", "true_equity_usd", "live_era_net_usd"}

KEY_ORDER = [
    "as_of_utc",
    "data_collection",
    "closed_trades",
    "wins_losses",
    "win_rate_pct",
    "engine_ledger_usd",
    "true_equity_usd",
    "live_era_trades",
    "live_era_net_usd",
    "log_covered_trades",
    "log_bars",
    "log_last_bar_utc",
    "skip_rows",
    "open_trade",
    "spread_usd_per_trade",
]


def live_facts(root, spread=None):
    sys.path.insert(0, HERE)
    import replay_lib as R  # noqa: E402

    f = {}
    status = {}
    sp = os.path.join(root, "status.json")
    if os.path.exists(sp):
        with open(sp) as fh:
            status = json.load(fh)

    trades = R.load_trades(os.path.join(root, "trades.csv"))
    bars = R.load_bars(os.path.join(root, "forward_test_log.csv"), with_indicators=True)
    covered, _ = R.coverage(trades, bars)

    skips = 0
    skp = os.path.join(root, "skipped_trades.csv")
    if os.path.exists(skp):
        with open(skp, newline="") as fh:
            skips = max(0, sum(1 for _ in fh) - 1)

    wins = sum(1 for t in trades if (t["profit"] or 0) > 0)
    losses = len(trades) - wins
    gross = sum(t["profit"] or 0 for t in trades)

    if spread is None:
        spread = 0.25
    live = [t for t in trades if t["et"] >= R.PORT_DEPLOY]
    live_net = sum(t["profit"] or 0 for t in live) - spread * len(live)

    f["closed_trades"] = str(len(trades))
    f["wins_losses"] = f"{wins}W/{losses}L"
    f["win_rate_pct"] = f"{100.0 * wins / len(trades):.1f}" if trades else "0.0"
    f["engine_ledger_usd"] = f"{status.get('equity', 200.0):.2f}"
    f["true_equity_usd"] = f"{200.0 + gross:.2f}"
    f["live_era_trades"] = str(len(live))
    f["live_era_net_usd"] = f"{live_net:+.2f}"
    f["log_covered_trades"] = str(len(covered))
    f["log_bars"] = str(len(bars))
    f["log_last_bar_utc"] = bars[-1]["dt"].strftime("%Y-%m-%d %H:%M") if bars else "none"
    f["skip_rows"] = str(skips)
    f["spread_usd_per_trade"] = f"{spread:.2f}"

    if status.get("trade_active"):
        f["open_trade"] = "{} #{} @ {}".format(
            status.get("trade_type") or "?",
            status.get("current_trade_num") or "?",
            status.get("entry_price") or "?")
    else:
        f["open_trade"] = "none"

    as_of = status.get("last_update") or ""
    as_of_dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            as_of_dt = datetime.strptime(as_of[:19], fmt)
            break
        except ValueError:
            continue
    if as_of_dt is None and bars:
        as_of_dt = bars[-1]["dt"]
    f["as_of_utc"] = as_of_dt.strftime("%Y-%m-%d %H:%M") if as_of_dt else "none"
    f["_as_of_dt"] = as_of_dt

    f["data_collection"] = _data_collection_number(root)
    return f


def _data_collection_number(root):
    try:
        out = subprocess.run(
            ["git", "log", "--format=%s", "-n", "50"],
            cwd=root, capture_output=True, text=True, timeout=20)
        nums = [int(m.group(1)) for m in
                (re.match(r"^data collection (\d+)$", line.strip())
                 for line in out.stdout.splitlines()) if m]
        return str(max(nums)) if nums else "0"
    except Exception:
        return "0"


def read_block(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    start = end = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith(BEGIN_MARK):
            start = i
        elif ln.strip() == END_MARK and start is not None:
            end = i
            break
    if start is None or end is None:
        return lines, None, None, {}
    doc = {}
    for ln in lines[start + 1:end]:
        m = re.match(r"^\|\s*([a-z_0-9]+)\s*\|\s*(.*?)\s*\|\s*$", ln.strip())
        if m:
            doc[m.group(1)] = m.group(2)
    return lines, start, end, doc


def render_block(facts, comment=None):
    head = BEGIN_MARK + (comment or
                         " machine-checked by tools/handoff_check.py;"
                         " refresh with --update -->")
    out = [head, "| key | value |", "|---|---|"]
    for k in KEY_ORDER:
        if k in facts:
            out.append(f"| {k} | {facts[k]} |")
    out.append(END_MARK)
    return out


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _minute(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _closed_gap(doc, facts):
    dn, ln = _num(doc.get("closed_trades")), _num(facts.get("closed_trades"))
    return None if dn is None or ln is None else ln - dn


def compare(doc, facts):
    rows = []
    cgap = _closed_gap(doc, facts)
    for k in KEY_ORDER:
        if k not in facts:
            continue
        d = doc.get(k)
        live = facts[k]
        if d is None:
            rows.append((k, "(missing)", live, "STALE", "key absent from the doc"))
            continue
        if d == live:
            rows.append((k, d, live, "OK", ""))
            continue
        if k in ADVISORY:
            rows.append((k, d, live, "DRIFT", "advisory"))
            continue

        if k == "log_last_bar_utc":
            if d in ("none", "?") and live != "none":
                nbars = _num(facts.get("log_bars")) or 0
                ok = nbars <= BAR_TOLERANCE
                rows.append((k, d, live, "OK" if ok else "STALE",
                             f"+{nbars:.0f} bars since Day-0 snapshot"))
                continue
            dd, ld = _minute(d), _minute(live)
            if dd is not None and ld is not None:
                mins = (ld - dd).total_seconds() / 60.0
                if mins < 0:
                    rows.append((k, d, live, "STALE",
                                 "snapshot is newer than the data (lost data, or a stale checkout?)"))
                else:
                    ok = mins <= BAR_TOLERANCE * 15
                    rows.append((k, d, live, "OK" if ok else "STALE",
                                 f"{mins / 15:+.0f} M15 bars since the snapshot"))
                continue

        if (k in OUTCOME_KEYS or k in OPEN_TRADE_KEYS) and cgap is not None:
            note = f"{cgap:+.0f} closed trades since the snapshot"
            if abs(cgap) > TRADE_TOLERANCE:
                rows.append((k, d, live, "STALE", note))
            elif k in OUTCOME_KEYS and cgap == 0:
                rows.append((k, d, live, "STALE",
                             "outcomes changed but the closed-trade count did not (ledger edited?)"))
            else:
                rows.append((k, d, live, "OK", note))
            continue

        dn, ln = _num(d), _num(live)
        if dn is not None and ln is not None:
            gap = abs(ln - dn)
            note = ""
            if k in TRADE_COUNT_KEYS:
                ok = gap <= TRADE_TOLERANCE
                note = f"{ln - dn:+.0f} trades since the snapshot"
            elif k == "log_bars":
                ok = gap <= BAR_TOLERANCE
                note = f"{ln - dn:+.0f} since the snapshot"
            elif k == "skip_rows":
                ok = gap <= SKIP_TOLERANCE
                note = f"{ln - dn:+.0f} since the snapshot"
            elif k in MONEY_KEYS:
                ok = gap <= TRADE_TOLERANCE * 15.0
                note = f"${ln - dn:+.2f} since the snapshot"
            else:
                ok = False
            rows.append((k, d, live, "OK" if ok else "STALE", note))
        else:
            rows.append((k, d, live, "STALE", "value changed"))
    return rows


def doc_consistency(root, doc, text):
    problems = []
    blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", text, flags=re.S)
    spread = _num(doc.get("spread_usd_per_trade"))
    if spread is not None and blocks:
        used = sorted({float(m) for b in blocks
                       for m in re.findall(r"--spread\s+([0-9.]+)", b)})
        bad = [u for u in used if abs(u - spread) > 1e-9]
        if bad:
            problems.append(
                "command blocks pass --spread " +
                ", ".join(f"{b:g}" for b in bad) +
                f" but the snapshot's cost assumption is ${spread:.2f}")

    for m in re.finditer(r"`((?:docs|archive|tools)/[A-Za-z0-9._/\-]+)`", text):
        ref = m.group(1)
        if re.search(r"YYYY|MM-DD|[*<>?]", ref):
            continue
        if not os.path.exists(os.path.join(root, ref)):
            problems.append(f"references `{ref}` which does not exist")
    return sorted(set(problems))


def main():
    args = [a for a in sys.argv[1:]]
    update = "--update" in args
    quiet = "--quiet" in args
    positional = [a for a in args if not a.startswith("--")]
    root = positional[0] if positional else os.path.dirname(HERE)

    path = os.path.join(root, "docs", "HANDOFF.md")
    if not os.path.exists(path):
        print(f"handoff_check: {path} not found")
        return 2

    lines, start, end, doc = read_block(path)
    if start is None:
        print(f"handoff_check: no {BEGIN_MARK} ... {END_MARK} block in {path}")
        return 2

    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    spread = _num(doc.get("spread_usd_per_trade"))
    if spread is None:
        spread = 0.25
    facts = live_facts(root, spread=spread)

    age_h = None
    age_txt = "?"
    if facts.get("_as_of_dt") and doc.get("as_of_utc") and doc.get("as_of_utc") != "none":
        try:
            snap = datetime.strptime(doc["as_of_utc"], "%Y-%m-%d %H:%M")
            age_h = (facts["_as_of_dt"] - snap).total_seconds() / 3600.0
            age_txt = f"{age_h:+.1f}"
        except ValueError:
            pass

    if update:
        keep = {k: doc[k] for k in doc if k not in facts}
        new = dict(facts)
        new.update({k: v for k, v in keep.items()})
        block = render_block(new)
        out = lines[:start] + block + lines[end + 1:]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out))
        changed = [k for k in KEY_ORDER
                   if k in facts and doc.get(k) not in (None, facts[k])]
        print("handoff_check: snapshot block updated in docs/HANDOFF.md")
        for k in changed:
            print(f"  {k:24s} {doc.get(k)} -> {facts[k]}")
        if not changed:
            print("  (no values changed)")
        print("  prose numbers are NOT touched - re-read §10's ritual and update"
              " §1/§4/§5/§7 yourself")
        return 0

    rows = compare(doc, facts)
    problems = doc_consistency(root, doc, text)

    stale = [r for r in rows if r[3] == "STALE"] + [("doc", "", "", "STALE", p) for p in problems]
    drift = [r for r in rows if r[3] == "DRIFT"]
    if age_h is not None and age_h > MAX_AGE_HOURS:
        stale.append(("as_of_utc", doc.get("as_of_utc"), facts["as_of_utc"],
                      "STALE", f"snapshot is {age_h:.0f} h older than the newest data"))

    if quiet:
        if stale:
            first = stale[0]
            print(f"STALE ({len(stale)} problem(s)): {first[0]} {first[4]}".rstrip())
        elif drift:
            print(f"fresh, {len(drift)} advisory drift (data moved since the snapshot)")
        else:
            print("fresh (snapshot matches the live data)")
        return 1 if stale else 0

    print(f"handoff_check - docs/HANDOFF.md vs live data in {root}")
    print(f"  snapshot as_of {doc.get('as_of_utc', '?')} | newest data "
          f"{facts['as_of_utc']} | age {age_txt} h")
    print()
    print(f"  {'key':24s} {'doc':>14s} {'live':>14s}  verdict")
    for k, d, live, verdict, note in rows:
        mark = {"OK": "  ok ", "DRIFT": " drift", "STALE": "STALE"}[verdict]
        print(f"  {k:24s} {str(d):>14s} {str(live):>14s}  [{mark}]"
              + (f"  {note}" if note else ""))
    if problems:
        print("\n== doc self-consistency ==")
        for p in problems:
            print(f"  [STALE] {p}")
    print()
    if stale:
        print(f"== result: HANDOFF STALE ({len(stale)} problem(s), "
              f"{len(drift)} advisory) ==")
        print("Fix: python3 tools/handoff_check.py --update   (snapshot block)")
        return 1
    print(f"== result: HANDOFF FRESH ({len(drift)} advisory drift) ==")
    if drift:
        print("Advisory drift is normal - refresh with: python3 tools/handoff_check.py --update")
    return 0


if __name__ == "__main__":
    sys.exit(main())
