"""
End-of-Day Update — main orchestrator.
Runs automatically at 8pm ET via GitHub Actions.

Flow:
  1. Collect tickers (Yahoo Finance + MDR Watchlist + Scan Log + CSV drop)
  2. Run calibrated 2-min FGE/Blast analysis on all tickers
  3. Fetch and classify news for qualifying tickers
  4. Append today's runs to TOP Gainers Data sheet
  5. Update MDR Watchlist (score, auto-add, timeout, exclusion)
  6. Generate both dashboards
  7. Deploy to Netlify
  8. Export backup Excel
"""

import os
import sys
import json
from datetime import date, datetime
import pandas as pd

# Add scripts dir to path
sys.path.insert(0, os.path.dirname(__file__))

from ticker_collector  import collect_all_tickers
from run_analysis      import run_batch_analysis
from news_classifier   import analyze_ticker_news
from mdr_scorer        import update_mdr_watchlist
from sheets_client     import (
    read_top_gainers, append_top_gainers_rows,
    write_mdr_tracking, export_all_to_excel
)
from generate_fge_dashboard import generate_fge_dashboard
from generate_mdr_dashboard import generate_mdr_dashboard


def build_top_gainers_rows(runs: list[dict], news_map: dict) -> list[dict]:
    """Convert run records to TOP Gainers Data sheet format."""
    from sheets_client import TOP_GAINERS_HEADERS
    today = date.today()

    rows = []
    for run in runs:
        ticker = run.get("ticker", "")
        news   = news_map.get(ticker, {})

        ep = run.get("price_entry", 0)
        xp = run.get("price_exit",  0)
        gain_d = round(float(xp) - float(ep), 4) if ep and xp else ""
        gain_p = run.get("pct_gain", "")

        # Calculate run time
        ti = run.get("entry_time", "")
        to = run.get("exit_time",  "")

        row = {
            "DATE":                      today.isoformat(),
            "DAY OF WEEK":               today.strftime("%A"),
            "STOCK":                     ticker,
            "FLOAT":                     "",
            "TOD":                       run.get("tod", ""),
            "TIME IN":                   ti,
            "TIME OUT":                  to,
            "RUN TIME":                  "",
            "ENTRY TYPE":                run.get("pattern", ""),
            "# LEGS":                    run.get("legs", ""),
            "A+ OPP?":                   run.get("aplus", "N"),
            "# OF RUNS ON CAL DAY":      "",
            "TYPE OF STATE":             run.get("state", ""),
            "RANGE":                     run.get("range", ""),
            "POSITION":                  run.get("position", ""),
            "ENTRY PRICE":               run.get("price_entry", ""),
            "EXIT PRICE":                run.get("price_exit",  ""),
            "HIGH PRICE INTRA":          run.get("price_hod",   ""),
            "20 MA":                     run.get("ma20",  ""),
            "200 MA":                    run.get("ma200", ""),
            "GAIN $/SHARE":              gain_d,
            "GAIN %/SHARE":              gain_p,
            "NEWS":                      news.get("news",      ""),
            "NEWS TYPE":                 news.get("news_type", ""),
            "NOTES":                     "",
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
        print("\n  No tickers found — exiting")
        return

    # ── STEP 2: Run 2-min analysis ────────────────────────────────────────────
    today_runs = run_batch_analysis(tickers)

    if not today_runs:
        print("\n  No qualifying runs found today")

    # ── STEP 3: Fetch news for qualifying tickers ─────────────────────────────
    print("\n[STEP 3] Fetching news...")
    qualifying_tickers = list({r["ticker"] for r in today_runs})
    news_map = {}
    for ticker in qualifying_tickers:
        print(f"  {ticker}...", end="", flush=True)
        news_map[ticker] = analyze_ticker_news(ticker)
        print(f" {news_map[ticker].get('news_type', 'no news')}")

    # ── STEP 4: Append to Google Sheets ──────────────────────────────────────
    print("\n[STEP 4] Writing to Google Sheets...")
    if today_runs:
        rows = build_top_gainers_rows(today_runs, news_map)
        append_top_gainers_rows(rows)

    # ── STEP 5: Update MDR Watchlist ──────────────────────────────────────────
    top_gainers_df = read_top_gainers(days_back=90)
    updated_mdr_df = update_mdr_watchlist(top_gainers_df, today_runs, news_map)
    write_mdr_tracking(updated_mdr_df)

    # ── STEP 6: Generate dashboards ───────────────────────────────────────────
    print("\n[STEP 5] Generating dashboards...")
    os.makedirs("dist", exist_ok=True)

    fresh_gainers = read_top_gainers(days_back=365)
    generate_fge_dashboard(fresh_gainers, "dist/fge.html")
    generate_mdr_dashboard(updated_mdr_df, today_runs, "dist/mdr.html")

    # Copy watchlist page
    generate_watchlist_page(updated_mdr_df, "dist/watchlist.html")

    # ── STEP 7: Export backup ─────────────────────────────────────────────────
    print("\n[STEP 6] Exporting backup...")
    backup_path = f"dist/trading_data_{date.today().isoformat()}.xlsx"
    export_all_to_excel(backup_path)

    print("\n" + "=" * 60)
    print(f"  EOD UPDATE COMPLETE")
    print(f"  Runs today:     {len(today_runs)}")
    print(f"  MDR watchlist:  {len(updated_mdr_df)} stocks")
    print(f"  Backup:         {backup_path}")
    print("=" * 60)


def generate_watchlist_page(mdr_df: pd.DataFrame, output_path: str):
    """
    Generate an updated watchlist.html that auto-loads MDR data
    without requiring manual Excel upload.
    """
    # Write MDR data as JSON for the page to consume
    records = mdr_df.to_dict(orient="records") if not mdr_df.empty else []

    # Write companion data file
    data_path = output_path.replace("watchlist.html", "watchlist-data.json")
    with open(data_path, "w") as f:
        json.dump({
            "updated": datetime.now().isoformat(),
            "stocks":  records,
        }, f, default=str)

    print(f"  Watchlist data → {data_path}")
    print(f"  Watchlist HTML → {output_path}")


if __name__ == "__main__":
    main()
