"""
Collects tickers from all sources and returns a deduplicated master list.

Sources:
  1. Yahoo Finance top gainers (cookie/crumb session)
  2. MDR Watchlist (Google Sheets MDR TRACKING tab)
  3. Today's scan log (Google Sheets SCAN LOG tab)
  4. Optional CSV drop (screener export, if file present in repo root)
"""

import requests
import os
import time
import pandas as pd
from datetime import date

from config import (
    YF_GAINERS_COUNT, YF_MIN_GAIN_PCT, YF_MIN_PRICE, YF_MAX_PRICE
)



# ── SOURCE 1: FMP Top Gainers ────────────────────────────────────────────────

def fetch_top_gainers() -> list[dict]:
    """Pull today's top gainers from FMP."""
    print("  [Source 1] Fetching top gainers via FMP...")
    try:
        from fmp_client import fetch_top_gainers_fmp
        return fetch_top_gainers_fmp()
    except Exception as e:
        print(f"    FMP error: {e}")
        return []


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
            ticker = str(row.get('STOCK', '')).strip().upper()
            if ticker:
                tickers.append({'ticker': ticker, 'source': 'MDR_WATCHLIST'})
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
        result = [{'ticker': t, 'source': 'SCAN_LOG'} for t in tickers]
        print(f"    Found {len(result)} tickers in today's scan log")
        return result
    except Exception as e:
        print(f"    Scan log read failed: {e}")
        return []


# ── SOURCE 4: Optional CSV Drop ───────────────────────────────────────────────

def fetch_csv_drop() -> list[dict]:
    """If screener_drop.csv exists in repo root, read tickers from it."""
    csv_path = 'screener_drop.csv'
    if not os.path.exists(csv_path):
        return []
    print(f"  [Source 4] Reading screener CSV drop...")
    try:
        df = pd.read_csv(csv_path)
        for col in ['Symbol', 'Ticker', 'TICKER', 'SYMBOL', 'symbol', 'ticker']:
            if col in df.columns:
                tickers = [
                    {'ticker': str(t).strip().upper(), 'source': 'CSV_DROP'}
                    for t in df[col].dropna()
                    if str(t).strip()
                ]
                print(f"    Found {len(tickers)} tickers from CSV drop")
                return tickers
        print("    CSV found but no ticker column recognised")
        return []
    except Exception as e:
        print(f"    CSV drop read failed: {e}")
        return []


# ── MASTER COLLECTOR ──────────────────────────────────────────────────────────

def collect_all_tickers() -> list[str]:
    """Collect from all sources, deduplicate, return sorted list."""
    print("\n[STEP 1] Collecting tickers from all sources...")
    all_raw = []

    all_raw.extend(fetch_top_gainers())
    all_raw.extend(fetch_mdr_watchlist())
    all_raw.extend(fetch_scan_log())
    all_raw.extend(fetch_csv_drop())

    seen   = set()
    unique = []
    for item in all_raw:
        t = item['ticker'].upper().strip()
        if not t or len(t) > 6 or not t.isalpha():
            continue
        if t not in seen:
            seen.add(t)
            unique.append(t)

    unique.sort()
    print(f"\n  Total unique tickers: {len(unique)}")
    if unique:
        print(f"  {', '.join(unique[:20])}{'...' if len(unique) > 20 else ''}")
    return unique


def collect_gainers_only() -> list[str]:
    """Return just the Alpha Vantage top gainer tickers for candle analysis."""
    return [t["ticker"] for t in fetch_top_gainers()]
