"""
fmp_client.py — Financial Modeling Prep API client
Replaces: Polygon (candles), Alpha Vantage (gainers), Finnhub (quotes/news/float)
Plan: Starter ($19/mo) — 300 calls/min, 1-min intraday, US coverage
"""
import os
import time
import requests
import pandas as pd
import numpy as np
import pytz
from datetime import date, datetime, timedelta

FMP_KEY  = os.environ.get("FMP_API_KEY", "")
BASE_URL = "https://financialmodelingprep.com/api/v3"
ET       = pytz.timezone("America/New_York")
FMP_DELAY = 0.21  # ~300 calls/min = 0.2s between calls

def _get(endpoint: str, params: dict = None) -> dict | list:
    """Raw GET with error handling."""
    if not FMP_KEY:
        return {}
    p = {"apikey": FMP_KEY}
    if params:
        p.update(params)
    try:
        resp = requests.get(f"{BASE_URL}/{endpoint}", params=p, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        return {}
    except Exception:
        return {}


# ── CANDLES ───────────────────────────────────────────────────────────────────

def fetch_candles_fmp_1min(ticker: str, target_date: date) -> pd.DataFrame:
    """Fetch 1-min bars from FMP, return ET-indexed OHLCV DataFrame."""
    if not FMP_KEY:
        return pd.DataFrame()
    try:
        date_str = target_date.isoformat()
        data = _get(f"historical-chart/1min/{ticker.upper()}", {
            "from": date_str,
            "to":   date_str,
        })
        if not data or not isinstance(data, list):
            return pd.DataFrame()

        rows = []
        for bar in data:
            try:
                ts = pd.Timestamp(bar["date"]).tz_localize(ET)
                rows.append({
                    "timestamp": ts,
                    "Open":   float(bar["open"]),
                    "High":   float(bar["high"]),
                    "Low":    float(bar["low"]),
                    "Close":  float(bar["close"]),
                    "Volume": float(bar.get("volume", 0)),
                })
            except Exception:
                continue

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).set_index("timestamp").sort_index()
        return df

    except Exception:
        return pd.DataFrame()


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



def fetch_candles_fmp_2min(ticker: str, target_date: date) -> pd.DataFrame:
    """Fetch 1-min bars, resample to 2-min, add MAs."""
    df_1 = fetch_candles_fmp_1min(ticker, target_date)
    if df_1.empty:
        return pd.DataFrame()
    df_2 = resample_to_2min(df_1)
    if len(df_2) < 5:
        return pd.DataFrame()
    df_2["MA20"]  = df_2["Close"].rolling(20).mean()
    df_2["MA200"] = df_2["Close"].rolling(200).mean()
    return df_2


# ── TOP GAINERS ───────────────────────────────────────────────────────────────

def fetch_top_gainers_fmp() -> list[dict]:
    """Fetch today's top % gainers from FMP."""
    data = _get("stock_market/gainers")
    if not data or not isinstance(data, list):
        return []
    results = []
    for item in data:
        sym    = str(item.get("symbol", "")).strip().upper()
        price  = float(item.get("price", 0) or 0)
        change = float(item.get("changesPercentage", 0) or 0)
        if sym and price >= 0.50 and change >= 10:
            results.append({
                "ticker":      sym,
                "price":       price,
                "change_pct":  change,
                "volume":      int(item.get("volume", 0) or 0),
                "source":      "FMP_GAINERS",
            })
    print(f"    Found {len(results)} qualifying gainers")
    return results[:20]


# ── LIVE QUOTES (batch) ───────────────────────────────────────────────────────

def batch_fetch_live_data_fmp(tickers: list[str]) -> dict:
    """Fetch live quotes for a list of tickers. Returns {ticker: {price, chg, vol}}."""
    if not tickers or not FMP_KEY:
        return {}
    results = {}
    # FMP allows batch quotes: /quote/AAPL,MSFT,GOOG
    chunk_size = 50
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        sym_str = ",".join(chunk)
        data = _get(f"quote/{sym_str}")
        if not data or not isinstance(data, list):
            continue
        for item in data:
            sym   = str(item.get("symbol", "")).strip().upper()
            price = float(item.get("price", 0) or 0)
            chg   = float(item.get("changesPercentage", 0) or 0)
            vol   = int(item.get("volume", 0) or 0)
            if sym and price > 0:
                results[sym] = {"price": price, "chg_pct": chg, "volume": vol}
        if i + chunk_size < len(tickers):
            time.sleep(FMP_DELAY)
    return results


# ── FLOAT / PROFILE ───────────────────────────────────────────────────────────

def fetch_float_fmp(ticker: str) -> str:
    """Fetch share float from FMP company profile."""
    data = _get(f"profile/{ticker.upper()}")
    if not data or not isinstance(data, list) or not data[0]:
        return ""
    try:
        shares = data[0].get("floatShares") or data[0].get("sharesOutstanding")
        if shares and float(shares) > 0:
            return str(round(float(shares) / 1_000_000, 2))  # in millions
    except Exception:
        pass
    return ""


def fetch_floats_batch_fmp(tickers: list[str]) -> dict[str, str]:
    """Fetch float for multiple tickers."""
    result = {}
    for ticker in tickers:
        result[ticker] = fetch_float_fmp(ticker)
        time.sleep(FMP_DELAY)
    return result


# ── NEWS ──────────────────────────────────────────────────────────────────────

def fetch_news_fmp(ticker: str) -> list[dict]:
    """Fetch recent news from FMP."""
    data = _get("stock_news", {
        "tickers": ticker.upper(),
        "limit":   5,
    })
    if not data or not isinstance(data, list):
        return []
    results = []
    for item in data:
        title   = str(item.get("title",   "") or "")
        summary = str(item.get("text",    "") or "")
        results.append({
            "title":   title,
            "summary": summary,
            "text":    f"{title} {summary}".lower(),
        })
    return results
