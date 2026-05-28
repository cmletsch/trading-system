"""
fmp_client.py — Financial Modeling Prep API (Stable endpoints)
Plan: Starter ($19/mo) — gainers, quotes, news, float, profile
NOTE: Intraday candles require Premium+ — use Polygon for candles
"""
import os
import time
import requests
import pandas as pd
import pytz
from datetime import date, timedelta

FMP_KEY   = os.environ.get("FMP_API_KEY", "")
BASE_URL  = "https://financialmodelingprep.com/stable"
FMP_DELAY = 0.21   # 300 calls/min = 0.2s between calls

ET = pytz.timezone("America/New_York")


def _get(endpoint: str, params: dict = None) -> dict | list:
    """Raw GET against the stable API with error reporting."""
    if not FMP_KEY:
        print("  [FMP] No API key set")
        return {}
    p = {"apikey": FMP_KEY}
    if params:
        p.update(params)
    try:
        resp = requests.get(f"{BASE_URL}/{endpoint}", params=p, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and ("Error Message" in data or "message" in data):
                print(f"  [FMP ERROR] {endpoint}: {(data.get('Error Message') or data.get('message',''))[:80]}")
                return {}
            return data
        else:
            print(f"  [FMP HTTP {resp.status_code}] {endpoint}: {resp.text[:80]}")
            return {}
    except Exception as e:
        print(f"  [FMP EXCEPTION] {endpoint}: {str(e)[:80]}")
        return {}


# ── TOP GAINERS ───────────────────────────────────────────────────────────────

def fetch_top_gainers_fmp() -> list[dict]:
    """Fetch today's top % gainers (Starter plan supported)."""
    data = _get("biggest-gainers")
    if not data or not isinstance(data, list):
        return []
    results = []
    for item in data:
        sym    = str(item.get("symbol", "")).strip().upper()
        price  = float(item.get("price", 0) or 0)
        change = float(item.get("changesPercentage", 0) or 0)
        if sym and price >= 0.50 and change >= 10:
            results.append({
                "ticker":     sym,
                "price":      price,
                "change_pct": change,
                "volume":     int(item.get("volume", 0) or 0),
                "source":     "FMP_GAINERS",
            })
    print(f"    Found {len(results)} qualifying gainers")
    return results[:20]


# ── LIVE QUOTES (batch) ───────────────────────────────────────────────────────

def batch_fetch_live_data_fmp(tickers: list[str]) -> dict:
    """Batch quotes — {ticker: {price, chg_pct, volume}}. Starter supported."""
    if not tickers or not FMP_KEY:
        return {}
    results = {}
    chunk_size = 50
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        sym_str = ",".join(chunk)
        data = _get("quote", {"symbol": sym_str})
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

def _valid_float(val: str) -> str:
    """Return numeric float string or empty if invalid (rejects time strings etc.)."""
    try:
        v = float(str(val).replace("M", "").strip())
        return str(round(v, 2)) if v > 0 else ""
    except (ValueError, TypeError):
        return ""


def fetch_float_fmp(ticker: str) -> str:
    """Fetch share float from FMP profile. Starter supported."""
    data = _get("profile", {"symbol": ticker.upper()})
    if not data or not isinstance(data, list) or not data[0]:
        return ""
    try:
        shares = data[0].get("floatShares") or data[0].get("sharesOutstanding")
        if shares and float(shares) > 0:
            return str(round(float(shares) / 1_000_000, 2))
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
    """Fetch recent news. Starter supported."""
    data = _get("news/stock", {
        "symbols": ticker.upper(),
        "limit":   5,
    })
    if not data or not isinstance(data, list):
        return []
    results = []
    for item in data:
        title   = str(item.get("title",   "") or "")
        summary = str(item.get("text",    "") or item.get("content", "") or "")
        results.append({
            "title":   title,
            "summary": summary,
            "text":    f"{title} {summary}".lower(),
        })
    return results


# ── 1-MIN CANDLES (stable API) ────────────────────────────────────────────────

def _resample_to_2min(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1-min bars to 2-min OHLCV."""
    return df_1m.resample("2min").agg({
        "Open": "first", "High": "max",
        "Low":  "min",   "Close": "last", "Volume": "sum",
    }).dropna(subset=["Open"])


def fetch_candles_fmp_1min(ticker: str, target_date: date) -> pd.DataFrame:
    """Fetch 1-min bars from FMP stable API."""
    if not FMP_KEY:
        return pd.DataFrame()
    try:
        date_str = target_date.isoformat()
        data = _get("historical-chart/1min", {
            "symbol": ticker.upper(),
            "from":   date_str,
            "to":     date_str,
        })
        if not data or not isinstance(data, list):
            return pd.DataFrame()

        # Find most recent available date if target not present
        available = sorted(set(b["date"][:10] for b in data if "date" in b), reverse=True)
        use_date  = date_str if date_str in available else (available[0] if available else date_str)

        rows = []
        for bar in data:
            if not str(bar.get("date","")).startswith(use_date):
                continue
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
        return pd.DataFrame(rows).set_index("timestamp").sort_index()

    except Exception as e:
        print(f" [FMP_CANDLE_ERR:{str(e)[:50]}]", end="")
        return pd.DataFrame()


def fetch_candles_fmp_2min(ticker: str, target_date: date) -> pd.DataFrame:
    """Fetch 1-min bars, resample to 2-min, add MAs."""
    df_1 = fetch_candles_fmp_1min(ticker, target_date)
    if df_1.empty:
        return pd.DataFrame()
    df_2 = _resample_to_2min(df_1)
    if len(df_2) < 5:
        return pd.DataFrame()
    df_2["MA20"]  = df_2["Close"].rolling(20).mean()
    df_2["MA200"] = df_2["Close"].rolling(200).mean()
    return df_2
