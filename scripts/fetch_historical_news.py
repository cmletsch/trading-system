"""
fetch_historical_news.py
Fetches news for all unique stocks in TOP Gainers Data that have
empty NEWS Y/N, writes Y/N and NEWS CATEGORY back to the sheet.
Processes in batches to respect rate limits.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

from sheets_client import get_sheet, read_top_gainers, TOP_GAINERS_HEADERS
from news_classifier import analyze_ticker_news
import gspread

BATCH_SIZE = 20   # tickers per batch
SLEEP_SEC  = 2    # seconds between batches

def main():
    print("=" * 50)
    print("  HISTORICAL NEWS FETCH")
    print("=" * 50)

    ws = get_sheet("TOP Gainers Data")
    all_vals = ws.get_all_values()
    if not all_vals:
        print("Sheet is empty"); return

    raw_headers = [h.strip() for h in all_vals[0]]
    print(f"Sheet: {len(all_vals)-1} rows, {len(raw_headers)} cols")

    # Find column indices
    def ci(name):
        return raw_headers.index(name) if name in raw_headers else None

    stock_col  = ci("STOCK")
    news_yn_col  = ci("NEWS Y/N")
    news_cat_col = ci("NEWS CATEGORY")

    if news_yn_col is None or news_cat_col is None:
        print("ERROR: NEWS Y/N or NEWS CATEGORY columns not found — run migrate_columns first")
        return

    # Collect rows that need news (NEWS Y/N is empty or blank)
    rows_needing_news = []  # (row_idx_1based, ticker)
    seen_tickers = {}  # ticker → (news_yn, news_cat) once fetched

    for i, row in enumerate(all_vals[1:], start=2):
        if len(row) <= max(stock_col, news_yn_col):
            continue
        ticker = str(row[stock_col]).strip().upper()
        yn = str(row[news_yn_col]).strip() if len(row) > news_yn_col else ""
        if ticker and yn == "":
            rows_needing_news.append((i, ticker))

    print(f"Rows needing news: {len(rows_needing_news)}")

    # Get unique tickers
    unique_tickers = list(dict.fromkeys(t for _, t in rows_needing_news))
    print(f"Unique tickers to fetch: {len(unique_tickers)}")

    # Fetch news in batches
    for i in range(0, len(unique_tickers), BATCH_SIZE):
        batch = unique_tickers[i:i+BATCH_SIZE]
        print(f"\nBatch {i//BATCH_SIZE+1}: {batch}")
        for ticker in batch:
            if ticker in seen_tickers:
                continue
            result = analyze_ticker_news(ticker)
            news_type = result.get("news_type", "") if result else ""
            seen_tickers[ticker] = ("Y" if news_type else "N", news_type)
            print(f"  {ticker}: {news_type or '(none)'}")
            time.sleep(0.3)
        time.sleep(SLEEP_SEC)

    # Write back to sheet in batch
    print(f"\nWriting results to sheet...")
    updates = []
    for row_i, ticker in rows_needing_news:
        if ticker not in seen_tickers:
            continue
        yn, cat = seen_tickers[ticker]
        updates.append({
            "range": gspread.utils.rowcol_to_a1(row_i, news_yn_col + 1),
            "values": [[yn]]
        })
        updates.append({
            "range": gspread.utils.rowcol_to_a1(row_i, news_cat_col + 1),
            "values": [[cat]]
        })

    # Batch update in chunks of 500
    written = 0
    for i in range(0, len(updates), 500):
        ws.batch_update(updates[i:i+500])
        written += len(updates[i:i+500]) // 2
        print(f"  Written {written} rows")
        time.sleep(1)

    print(f"\n✓ News fetch complete — {written} rows updated")

if __name__ == "__main__":
    main()
