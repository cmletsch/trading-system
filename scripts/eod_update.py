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
    # Allow override via EOD_TARGET_DATE env var (for backfill)
    override = os.environ.get("EOD_TARGET_DATE", "").strip()
    if override:
        from datetime import date as _date
        d = _date.fromisoformat(override)
        print(f"  [BACKFILL] Target date overridden → {d}")
        return d
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
from finnhub_client     import batch_fetch_live_data
from finnhub_client     import fetch_floats_batch
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
            "DATE":          today.isoformat(),
            "DOW":           today.strftime("%A"),
            "WEEK#":         str(today.isocalendar()[1]),
            "STOCK":         ticker,
            "FLOAT":         run.get("float", ""),
            "TOD":           run.get("tod", ""),
            "TIME IN":       run.get("entry_time", ""),
            "TIME OUT":      run.get("exit_time",  ""),
            "TRADE TIME":    "",
            "ENTRY TYPE":    run.get("pattern", ""),
            "ENTRY PRICE":   run.get("price_entry", ""),
            "EXIT PRICE":    run.get("price_exit",  ""),
            "20 MA":         run.get("ma20",  ""),
            "200 MA":        run.get("ma200", ""),
            "STATE":         run.get("state", ""),
            "RANGE":         run.get("range", ""),
            "POSITION":      run.get("position", ""),
            "GAIN $/SHARE":  gain_d,
            "G/L %/SHARE":   round(run.get("pct_gain", 0) / 100, 6) if run.get("pct_gain") else "",
            "# LEGS":        run.get("legs", ""),
            "A+ OPP?":       run.get("aplus", "N"),
            "MDR WATCHLIST": "",
            "NEWS Y/N":      "Y" if news.get("news_type") else "N",
            "NEWS CATEGORY": news.get("news_type", ""),
            "NOTES":         "",
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

    # ── STEP 2: Run 2-min analysis on AV gainers + SCAN LOG tickers ────────────
    # FMP — analyze scan log + AV gainers
    from ticker_collector import collect_gainers_only, fetch_scan_log, fetch_csv_drop
    av_tickers   = collect_gainers_only()
    scan_tickers = [t["ticker"] for t in fetch_scan_log()]
    csv_tickers  = [t["ticker"] for t in fetch_csv_drop()]
    # Scan log first (your hand-picked stocks), then AV gainers, deduped
    analysis_tickers = list(dict.fromkeys(scan_tickers + csv_tickers + av_tickers))
    print(f"  Running candle analysis on {len(analysis_tickers)} tickers "
          f"({len(scan_tickers)} scan log + {len(av_tickers)} AV gainers)")
    trading_date = get_trading_date()
    print(f"  Target trading date: {trading_date}")
    today_runs = run_batch_analysis(analysis_tickers, target_date=trading_date)
    if not today_runs:
        print("\n  No qualifying runs found today")

    # ── STEP 2b: Fetch floats for qualifying tickers ─────────────────────────
    if today_runs:
        qualifying_tickers = list({r["ticker"] for r in today_runs})
        print(f"  Fetching floats for {len(qualifying_tickers)} tickers...")
        float_map = fetch_floats_batch(qualifying_tickers)
        # Add float to each run
        for run in today_runs:
            run["float"] = float_map.get(run["ticker"], "")

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
    _skip_scoring = (
        os.environ.get("SKIP_SCORING","").strip().lower() in ("1","true","yes")
        or (bool(os.environ.get("EOD_TARGET_DATE","")) and datetime.now(ET).weekday() >= 5)
    )
    top_gainers_df = read_top_gainers(days_back=365)
    if _skip_scoring:
        print("\n[STEP 5] MDR scoring SKIPPED — preserving existing scores (backfill/weekend)")
        import json as _json
        _existing_mdr = "data/mdr.json"
        if os.path.exists(_existing_mdr):
            _mdr_raw = _json.loads(open(_existing_mdr).read())
            import pandas as _pd
            updated_mdr_df = _pd.DataFrame(_mdr_raw.get("records", []))
        else:
            updated_mdr_df, _ = update_mdr_watchlist(top_gainers_df, today_runs, news_map)
        removed_set = set()
    else:
        updated_mdr_df, removed_set = update_mdr_watchlist(top_gainers_df, today_runs, news_map)
        write_mdr_tracking(updated_mdr_df, removed_set)

    # ── STEP 6: Write data files for dashboard ────────────────────────────────
    print("\n[STEP 6] Writing data files...")
    gainers_data = build_gainers_json(top_gainers_df, today_runs)
    if _skip_scoring and os.path.exists("data/mdr.json"):
        print("  data/mdr.json preserved (skipped rescoring)")
        mdr_data = None
    else:
        mdr_data = build_mdr_json(updated_mdr_df, top_gainers_df=read_top_gainers(days_back=90), today_runs=today_runs)
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
