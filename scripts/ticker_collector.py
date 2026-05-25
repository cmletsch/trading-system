"""
Collects tickers from all sources and returns a deduplicated master list.

Sources:
  1. Yahoo Finance top gainers (auto-pull)
  2. MDR Watchlist (Google Sheets MDR TRACKING tab)
  3. Today's scan log (Google Sheets SCAN LOG tab)
  4. Optional CSV drop (screener export, if file present in repo root)
"""

import requests
import yfinance as yf
import pandas as pd
from datetime import date
import os
import json

from config import (
    YF_GAINERS_COUNT, YF_MIN_GAIN_PCT, YF_MIN_PRICE, YF_MAX_PRICE
)


# ── SOURCE 1: Yahoo Finance Top Gainers ───────────────────────────────────────

def fetch_yahoo_gainers() -> list[dict]:
    """Pull top gainers from Yahoo Finance screener."""
    print("  [Source 1] Fetching Yahoo Finance top gainers...")
    url = (
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        "?formatted=false&lang=en-US&region=US&scrIds=day_gainers"
        f"&count={YF_GAINERS_COUNT}&start=0"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        quotes = resp.json()["finance"]["result"][0]["quotes"]
        tickers = []
        for q in quotes:
            symbol = q.get("symbol", "")
            price = float(q.get("regularMarketPrice", 0) or 0)
            gain_pct = float(q.get("regularMarketChangePercent", 0) or 0)
            if not symbol:
                continue
            if gain_pct < YF_MIN_GAIN_PCT:
                continue
            if price < YF_MIN_PRICE or price > YF_MAX_PRICE:
                continue
            tickers.append({
                "ticker": symbol.upper().strip(),
                "gain_pct": round(gain_pct, 2),
                "price": round(price, 4),
                "source": "YF_GAINERS",
            })
        print(f"    Found {len(tickers)} qualifying gainers from Yahoo Finance")
        return tickers
    except Exception as e:
        print(f"    Yahoo Finance fetch failed: {e}")
        # Fallback: use yfinance screener
        return _fetch_yahoo_gainers_fallback()


def _fetch_yahoo_gainers_fallback() -> list[dict]:
    """Fallback using yfinance download of known gainer ETFs or direct yf screener."""
    print("    Trying yfinance fallback...")
    try:
        # Use yfinance's built-in screener if available
        import yfinance as yf
        screener = yf.Screener()
        screener.set_default_body({"offset": 0, "size": YF_GAINERS_COUNT,
                                   "sortField": "percentchange", "sortType": "DESC",
                                   "quoteType": "EQUITY", "query": {"operator": "AND",
                                   "operands": [{"operator": "GT",
                                                  "operands": ["percentchange", YF_MIN_GAIN_PCT]}]},
                                   "userId": "", "userIdType": "guid"})
        result = screener.response
        quotes = result.get("quotes", [])
        tickers = []
        for q in quotes:
            symbol = q.get("symbol", "")
            price = float(q.get("regularMarketPrice", 0) or 0)
            gain_pct = float(q.get("regularMarketChangePercent", 0) or 0)
            if symbol and YF_MIN_PRICE <= price <= YF_MAX_PRICE:
                tickers.append({"ticker": symbol, "gain_pct": gain_pct,
                                 "price": price, "source": "YF_FALLBACK"})
        return tickers
    except Exception as e:
        print(f"    Fallback also failed: {e}")
        return []


# ── SOURCE 2: MDR Watchlist ───────────────────────────────────────────────────

def fetch_mdr_watchlist() -> list[dict]:
    """Pull active tickers from MDR TRACKING sheet."""
    print("  [Source 2] Reading MDR Watchlist from Google Sheets...")
    try:
        from sheets_client import read_mdr_tracking
        df = read_mdr_tracking()
        if df.empty:
            print("    MDR TRACKING sheet is empty")
            return []
        tickers = []
        for _, row in df.iterrows():
            ticker = str(row.get("STOCK", "")).strip().upper()
            if ticker:
                tickers.append({"ticker": ticker, "source": "MDR_WATCHLIST"})
        print(f"    Found {len(tickers)} tickers on MDR Watchlist")
        return tickers
    except Exception as e:
        print(f"    MDR Watchlist read failed: {e}")
        return []


# ── SOURCE 3: Today's Scan Log ────────────────────────────────────────────────

def fetch_scan_log() -> list[dict]:
    """Pull tickers logged to SCAN LOG today."""
    print("  [Source 3] Reading today's scan log from Google Sheets...")
    try:
        from sheets_client import read_today_scan_log
        tickers = read_today_scan_log()
        result = [{"ticker": t, "source": "SCAN_LOG"} for t in tickers]
        print(f"    Found {len(result)} tickers in today's scan log")
        return result
    except Exception as e:
        print(f"    Scan log read failed: {e}")
        return []


# ── SOURCE 4: Optional CSV Drop ───────────────────────────────────────────────

def fetch_csv_drop() -> list[dict]:
    """
    If a file named 'screener_drop.csv' exists in the repo root,
    read tickers from it. File is expected to have a 'Symbol' or 'Ticker' column.
    """
    csv_path = "screener_drop.csv"
    if not os.path.exists(csv_path):
        return []
    print(f"  [Source 4] Reading screener CSV drop: {csv_path}")
    try:
        df = pd.read_csv(csv_path)
        # Try common column names
        for col in ["Symbol", "Ticker", "TICKER", "SYMBOL", "symbol", "ticker"]:
            if col in df.columns:
                tickers = [{"ticker": str(t).strip().upper(), "source": "CSV_DROP"}
                           for t in df[col].dropna() if str(t).strip()]
                print(f"    Found {len(tickers)} tickers from CSV drop")
                return tickers
        print("    CSV drop found but no recognizable ticker column")
        return []
    except Exception as e:
        print(f"    CSV drop read failed: {e}")
        return []


# ── MASTER COLLECTOR ─────────────────────────────────────────────────────────

def collect_all_tickers() -> list[str]:
    """
    Collect tickers from all sources, deduplicate, and return a sorted list.
    """
    print("\n[STEP 1] Collecting tickers from all sources...")
    all_raw = []

    # Run all sources
    all_raw.extend(fetch_yahoo_gainers())
    all_raw.extend(fetch_mdr_watchlist())
    all_raw.extend(fetch_scan_log())
    all_raw.extend(fetch_csv_drop())

    # Deduplicate
    seen = set()
    unique = []
    for item in all_raw:
        t = item["ticker"].upper().strip()
        # Basic validation
        if not t or len(t) > 6 or not t.isalpha():
            continue
        if t not in seen:
            seen.add(t)
            unique.append(t)

    unique.sort()
    print(f"\n  Total unique tickers to analyze: {len(unique)}")
    print(f"  Tickers: {', '.join(unique[:20])}{'...' if len(unique) > 20 else ''}")
    return unique
