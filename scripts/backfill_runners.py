"""
One-time backfill: scan ~60 days of 5-minute extended-hours history for every
known ticker and add a RUNNER row for each ticker-day-session that ran
RUNNER_MIN_PCT or more. Safe to re-run: rows already in the sheet are skipped.

Tickers: MDR watchlist + TOP Gainers history (data/*.json) + data/runner_seed_tickers.txt
(optional, one ticker per line - add names from your lists that aren't there yet).
Run from the Actions tab: "Backfill Runners".  Env DRY_RUN=1 prints without writing.
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(__file__))
from runner_capture import fetch_5m, runners_from_bars
from config import RUNNER_MIN_PCT


def load_tickers():
    names = set()
    for f, key in (("data/mdr.json", "records"), ("data/gainers.json", "records")):
        try:
            d = json.load(open(f))
            for r in d.get(key, []):
                t = str(r.get("stock") or r.get("ticker") or "").upper().strip()
                if t.isalpha() and len(t) <= 6:
                    names.add(t)
        except Exception as e:
            print(f"  [{f}: {str(e)[:60]}]")
    if os.path.exists("data/runner_seed_tickers.txt"):
        for line in open("data/runner_seed_tickers.txt"):
            t = line.strip().upper()
            if t.isalpha() and len(t) <= 6:
                names.add(t)
    return sorted(names)


def main():
    from eod_update import build_top_gainers_rows
    from finnhub_client import fetch_floats_batch
    from sheets_client import append_top_gainers_rows
    tickers = load_tickers()
    print(f"Backfill: {len(tickers)} tickers, threshold +{RUNNER_MIN_PCT:.0f}%")
    runs = []
    for i, t in enumerate(tickers, 1):
        df = fetch_5m(t, days=60)
        got = runners_from_bars(t, df)
        if got:
            print(f"  [{i}/{len(tickers)}] {t}: {len(got)} runner session(s)")
        runs += got
        time.sleep(0.4)
    print(f"Total runner rows: {len(runs)} on {len({r['ticker'] for r in runs})} tickers")
    if os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes"):
        for r in runs[:40]:
            print("  ", r["date"], r["ticker"], r["session"], r["move_pct"], r["note"])
        return
    fl = fetch_floats_batch(sorted({r["ticker"] for r in runs}))
    for r in runs:
        r["float"] = fl.get(r["ticker"], "")
    append_top_gainers_rows(build_top_gainers_rows(runs, {}))


if __name__ == "__main__":
    main()
