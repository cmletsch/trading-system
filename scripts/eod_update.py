"""
End-of-Day Update — main orchestrator.
Runs automatically at 8pm ET via GitHub Actions.

Flow:
  1. Collect tickers (Yahoo Finance + MDR Watchlist + Scan Log)
  2. Run calibrated 2-min FGE/Blast analysis on all tickers
  3. Fetch and classify news for qualifying tickers
  4. Write today's runs to Google Sheets (TOP Gainers Data)
  5. Update MDR Watchlist (score, auto-add, timeout, exclusion)
  6. Write data/gainers.json + data/mdr.json for dashboard
  7. Update watchlist via Netlify function
  8. Export backup Excel to data/
"""

import os
import sys
import json
from datetime import date, datetime, timedelta
import pandas as pd
import pytz

def get_trading_date() -> date:
    """Get the most recent completed trading day regardless of when script runs."""
    et  = pytz.timezone("America/New_York")
    now = datetime.now(et)
    d   = now.date()
    # Before 4pm ET means today's market hasn't closed — use yesterday
    if now.hour < 16:
        d -= timedelta(days=1)
    # Skip weekends back to Friday
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d

sys.path.insert(0, os.path.dirname(__file__))

from ticker_collector   import collect_all_tickers
from run_analysis       import run_batch_analysis
from news_classifier    import analyze_ticker_news
from mdr_scorer         import update_mdr_watchlist
from sheets_client      import (
    read_top_gainers, append_top_gainers_rows,
    write_mdr_tracking, export_all_to_excel,
    TOP_GAINERS_HEADERS,
)
from generate_data_files import (
    build_gainers_json, build_mdr_json,
    build_watchlist_payload, update_netlify_watchlist,
    write_data_files,
)


def build_top_gainers_rows(runs: list[dict], news_map: dict) -> list[dict]:
    today = get_trading_date()
    rows = []
    for run in runs:
        ticker = run.get("ticker", "")
        news   = news_map.get(ticker, {})
        ep = run.get("price_entry", 0)
        xp = run.get("price_exit",  0)
        gain_d = round(float(xp) - float(ep), 4) if ep and xp else ""
        row = {
            "DATE":                  today.isoformat(),
            "DAY OF WEEK":           today.strftime("%A"),
            "STOCK":                 ticker,
            "FLOAT":                 "",
            "TOD":                   run.get("tod", ""),
            "TIME IN":               run.get("entry_time", ""),
            "TIME OUT":              run.get("exit_time",  ""),
            "RUN TIME":              "",
            "ENTRY TYPE":            run.get("pattern", ""),
            "# LEGS":                run.get("legs", ""),
            "A+ OPP?":               run.get("aplus", "N"),
            "# OF RUNS ON CAL DAY":  "",
            "TYPE OF STATE":         run.get("state", ""),
            "RANGE":                 run.get("range", ""),
            "POSITION":              run.get("position", ""),
            "ENTRY PRICE":           run.get("price_entry", ""),
            "EXIT PRICE":            run.get("price_exit",  ""),
            "HIGH PRICE INTRA":      run.get("price_hod",   ""),
            "20 MA":                 run.get("ma20",  ""),
            "200 MA":                run.get("ma200", ""),
            "GAIN $/SHARE":          gain_d,
            "GAIN %/SHARE":          run.get("pct_gain", ""),
            "NEWS":                  news.get("news",      ""),
            "NEWS TYPE":             news.get("news_type", ""),
            "NOTES":                 "",
        }
        rows.append(row)
    return rows


def main():
    print("=" * 60)
    print(f"  EOD UPDATE — {date.today()}  {datetime.now().strftime('%H:%M ET')}")
    print("=" * 60)

    # ── STEP 1: Collect tickers ───────────────────────────────────────────────
    tickers = collect_all_tickers()
    if not tickers:
        print("\n  No tickers found — writing empty data files and exiting")
        write_data_files(
            {"updated": datetime.utcnow().isoformat()+"Z", "records": []},
            {"updated": datetime.utcnow().isoformat()+"Z", "records": []},
        )
        return

    # ── STEP 2: Run 2-min analysis on today's top gainers ──────────────────────
    # Alpha Vantage already called in STEP 1 — reuse those gainers for candles
    # Limit to 20 to stay within AV 25 calls/day budget (1 used for top gainers)
    from ticker_collector import collect_gainers_only
    analysis_tickers = collect_gainers_only()[:20]
    print(f"  Running candle analysis on {len(analysis_tickers)} active tickers "
          f"(MDR watchlist scored separately)")
    trading_date = get_trading_date()
    print(f"  Target trading date: {trading_date}")
    today_runs = run_batch_analysis(analysis_tickers, target_date=trading_date)
    if not today_runs:
        print("\n  No qualifying runs found today")

    # ── STEP 3: Fetch news ────────────────────────────────────────────────────
    print("\n[STEP 3] Fetching news...")
    news_map = {}
    for ticker in list({r["ticker"] for r in today_runs}):
        print(f"  {ticker}...", end="", flush=True)
        news_map[ticker] = analyze_ticker_news(ticker)
        print(f" {news_map[ticker].get('news_type', 'no news')}")

    # ── STEP 4: Write runs to Google Sheets ───────────────────────────────────
    print("\n[STEP 4] Writing to Google Sheets...")
    if today_runs:
        rows = build_top_gainers_rows(today_runs, news_map)
        append_top_gainers_rows(rows)

    # ── STEP 5: Update MDR Watchlist ──────────────────────────────────────────
    top_gainers_df  = read_top_gainers(days_back=365)
    updated_mdr_df, removed_set = update_mdr_watchlist(top_gainers_df, today_runs, news_map)
    write_mdr_tracking(updated_mdr_df, removed_set)

    # ── STEP 6: Write data files for dashboard ────────────────────────────────
    print("\n[STEP 6] Writing data files...")
    gainers_data = build_gainers_json(top_gainers_df, today_runs)
    mdr_data     = build_mdr_json(updated_mdr_df)
    write_data_files(gainers_data, mdr_data)

    # ── STEP 7: Update watchlist via Netlify function ─────────────────────────
    print("\n[STEP 7] Updating watchlist...")
    wl_payload = build_watchlist_payload(updated_mdr_df, top_gainers_df)
    update_netlify_watchlist(wl_payload)

    # ── STEP 8: Export backup ─────────────────────────────────────────────────
    print("\n[STEP 8] Exporting backup...")
    os.makedirs("data", exist_ok=True)
    backup_path = f"data/trading_data_{date.today().isoformat()}.xlsx"
    export_all_to_excel(backup_path)

    print("\n" + "=" * 60)
    print(f"  EOD UPDATE COMPLETE")
    print(f"  Runs today:     {len(today_runs)}")
    print(f"  MDR watchlist:  {len(updated_mdr_df)} stocks")
    print("=" * 60)


if __name__ == "__main__":
    main()
