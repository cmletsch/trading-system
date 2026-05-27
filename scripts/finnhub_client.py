"""
Finnhub API client.
Used for:
  - 1-min candles (resampled to 2-min) for run analysis
  - Live quote data for MDR scoring
"""

import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, date
import pytz

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
BASE_URL    = "https://finnhub.io/api/v1"
ET          = pytz.timezone("America/New_York")

# Respect free tier: 60 calls/min
CALL_DELAY  = 0.15   # seconds between calls in batch


def _get(endpoint: str, params: dict) -> dict:
    """Make a single Finnhub API call."""
    params["token"] = FINNHUB_KEY
    try:
        resp = requests.get(
            f"{BASE_URL}{endpoint}",
            params=params,
            timeout=12,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ── CANDLES ───────────────────────────────────────────────────────────────────

def get_candles_1min(ticker: str, target_date: date) -> pd.DataFrame:
    """
    Fetch 1-minute candles for a ticker on target_date (full session 4am-8pm ET).
    Returns DataFrame with OHLCV indexed by ET timestamp, or empty DataFrame.
    """
    # Build unix timestamps for the full trading day in ET
    start_dt = ET.localize(datetime(target_date.year, target_date.month,
                                     target_date.day, 4, 0, 0))
    end_dt   = ET.localize(datetime(target_date.year, target_date.month,
                                     target_date.day, 20, 5, 0))
    from_ts  = int(start_dt.timestamp())
    to_ts    = int(end_dt.timestamp())

    data = _get("/stock/candle", {
        "symbol":     ticker.upper(),
        "resolution": "1",
        "from":       from_ts,
        "to":         to_ts,
    })

    if data.get("s") != "ok" or not data.get("t"):
        return pd.DataFrame()

    df = pd.DataFrame({
        "Open":   data["o"],
        "High":   data["h"],
        "Low":    data["l"],
        "Close":  data["c"],
        "Volume": data["v"],
    }, index=pd.to_datetime(data["t"], unit="s", utc=True).tz_convert(ET))

    return df


def resample_to_2min(df_1min: pd.DataFrame) -> pd.DataFrame:
    """Resample 1-min OHLCV DataFrame to 2-min bars."""
    if df_1min.empty:
        return df_1min
    df = df_1min.resample("2min").agg({
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }).dropna(subset=["Close"])
    return df


def fetch_candles_for_analysis(ticker: str, target_date: date) -> pd.DataFrame:
    """
    Full pipeline: fetch 1-min, resample to 2-min, add MAs.
    Returns ready-to-analyze DataFrame or empty DataFrame.
    """
    df_1 = get_candles_1min(ticker, target_date)
    if df_1.empty:
        return pd.DataFrame()
    df_2 = resample_to_2min(df_1)
    if len(df_2) < 5:
        return pd.DataFrame()
    df_2["MA20"]  = df_2["Close"].rolling(20).mean()
    df_2["MA200"] = df_2["Close"].rolling(200).mean()
    return df_2


# ── LIVE QUOTES ───────────────────────────────────────────────────────────────

def get_quote(ticker: str) -> dict:
    """
    Fetch current quote for a ticker.
    Returns dict with price, prev, open, day_chg, gap_pct.
    """
    safe = {"price": 0, "prev": 0, "open": 0,
            "day_chg": 0, "gap_pct": 0, "rvol": 0}
    data = _get("/quote", {"symbol": ticker.upper()})
    if "error" in data or not data.get("c"):
        return safe
    price  = float(data.get("c",  0) or 0)
    prev   = float(data.get("pc", 0) or 0)
    open_p = float(data.get("o",  0) or 0)
    dp     = float(data.get("dp", 0) or 0)
    if price == 0:
        return safe
    day_chg = dp
    gap_pct = ((open_p - prev) / prev * 100) if prev > 0 else 0
    return {
        "price":   round(price,   4),
        "prev":    round(prev,    4),
        "open":    round(open_p,  4),
        "day_chg": round(day_chg, 2),
        "gap_pct": round(gap_pct, 2),
        "rvol":    0,   # not available in free quote endpoint
    }


def batch_get_quotes(tickers: list[str]) -> dict:
    """
    Fetch live quotes for multiple tickers.
    Returns {ticker: quote_dict}.
    Respects rate limit with small delay between calls.
    """
    results = {}
    for i, ticker in enumerate(tickers):
        results[ticker] = get_quote(ticker)
        if i < len(tickers) - 1:
            time.sleep(CALL_DELAY)
    return results


# ── TOP GAINERS (Finnhub stock screener) ──────────────────────────────────────

def get_top_gainers_finnhub() -> list[dict]:
    """
    Use Finnhub market news to find top movers.
    Note: Finnhub free tier doesn't have a dedicated top gainers endpoint,
    so we fall back to returning empty list (MDR watchlist is the primary source).
    """
    return []
