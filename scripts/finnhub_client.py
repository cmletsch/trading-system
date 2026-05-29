"""
finnhub_client.py — Polygon.io candle client
1-min intraday data for OTC/penny stocks via Polygon Starter ($29/mo)
All other data (gainers, quotes, news, float) handled by fmp_client.py or Polygon REST
"""
import os
import requests
import pandas as pd
import pytz
from datetime import date

POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")
POLY_DELAY  = 12.5
ET          = pytz.timezone("America/New_York")


def fetch_candles_polygon_2min(ticker: str, target_date: date) -> pd.DataFrame:
    """Fetch 1-min bars from Polygon, resample to 2-min, add MAs."""
    if not POLYGON_KEY:
        print(" [NO POLYGON KEY]", end="")
        return pd.DataFrame()
    try:
        date_str = target_date.isoformat()
        url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker.upper()}"
               f"/range/1/minute/{date_str}/{date_str}")
        resp = requests.get(url, params={
            "adjusted": "true", "sort": "asc",
            "limit": 50000, "apiKey": POLYGON_KEY,
        }, timeout=15)

        if resp.status_code != 200:
            return pd.DataFrame()
        data = resp.json()
        if data.get("status") not in ("OK", "DELAYED") or not data.get("results"):
            return pd.DataFrame()

        rows = []
        for bar in data["results"]:
            try:
                ts = pd.Timestamp(bar["t"], unit="ms").tz_localize("UTC").tz_convert(ET)
                rows.append({
                    "timestamp": ts,
                    "Open":   float(bar["o"]),
                    "High":   float(bar["h"]),
                    "Low":    float(bar["l"]),
                    "Close":  float(bar["c"]),
                    "Volume": float(bar.get("v", 0)),
                })
            except Exception:
                continue

        if not rows:
            return pd.DataFrame()

        df_1 = pd.DataFrame(rows).set_index("timestamp").sort_index()
        df_2  = df_1.resample("2min").agg({
            "Open": "first", "High": "max",
            "Low":  "min",   "Close": "last", "Volume": "sum",
        }).dropna(subset=["Open"])

        if len(df_2) < 5:
            return pd.DataFrame()

        df_2["MA20"]  = df_2["Close"].rolling(20).mean()
        df_2["MA200"] = df_2["Close"].rolling(200).mean()
        return df_2

    except Exception as e:
        print(f" [POLY_ERR:{str(e)[:50]}]", end="")
        return pd.DataFrame()


# ── BATCH QUOTES via Polygon snapshot ────────────────────────────────────────

def batch_fetch_live_data(tickers: list[str]) -> dict:
    """Batch live quotes via Polygon snapshot endpoint."""
    if not tickers or not POLYGON_KEY:
        return {}
    results = {}
    import time
    chunk_size = 100
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        sym_str = ",".join(chunk)
        try:
            resp = requests.get(
                "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers",
                params={"tickers": sym_str, "apiKey": POLYGON_KEY},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("tickers", []):
                    sym   = str(item.get("ticker", "")).upper()
                    day   = item.get("day", {})
                    price = float(item.get("lastTrade", {}).get("p", 0) or
                                  day.get("c", 0) or 0)
                    chg   = float(item.get("todaysChangePerc", 0) or 0)
                    vol   = int(day.get("v", 0) or 0)
                    if sym and price > 0:
                        results[sym] = {"price": price, "chg_pct": chg, "volume": vol}
        except Exception as e:
            print(f" [POLY_QUOTE_ERR:{str(e)[:40]}]", end="")
        if i + chunk_size < len(tickers):
            time.sleep(0.5)
    return results


# ── NEWS via Polygon ──────────────────────────────────────────────────────────

def fetch_news_polygon(ticker: str) -> list[dict]:
    """Fetch recent news from Polygon."""
    try:
        resp = requests.get(
            f"https://api.polygon.io/v2/reference/news",
            params={"ticker": ticker.upper(), "limit": 5, "apiKey": POLYGON_KEY},
            timeout=10
        )
        if resp.status_code != 200:
            return []
        items = resp.json().get("results", [])
        results = []
        for item in items:
            title   = str(item.get("title", "") or "")
            summary = str(item.get("description", "") or "")
            results.append({
                "title":   title,
                "summary": summary,
                "text":    f"{title} {summary}".lower(),
            })
        return results
    except Exception:
        return []
