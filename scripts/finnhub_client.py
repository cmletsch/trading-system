"""
finnhub_client.py — Polygon.io candle + quote + news client
"""
import os
import time
import requests
import pandas as pd
import pytz
from datetime import date, timedelta

POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")
POLY_DELAY  = 12.5
ET          = pytz.timezone("America/New_York")


def _fetch_1min_bars(ticker: str, date_str: str) -> list:
    """Fetch 1-min bars for a single date from Polygon."""
    url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker.upper()}"
           f"/range/1/minute/{date_str}/{date_str}")
    try:
        resp = requests.get(url, params={
            "adjusted": "true", "sort": "asc",
            "limit": 50000, "apiKey": POLYGON_KEY,
        }, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if data.get("status") not in ("OK", "DELAYED") or not data.get("results"):
            return []
        rows = []
        for bar in data["results"]:
            try:
                ts = pd.Timestamp(bar["t"], unit="ms").tz_localize("UTC").tz_convert(ET)
                rows.append({"timestamp": ts,
                             "Open": float(bar["o"]), "High": float(bar["h"]),
                             "Low": float(bar["l"]), "Close": float(bar["c"]),
                             "Volume": float(bar.get("v", 0))})
            except Exception:
                continue
        return rows
    except Exception:
        return []


def fetch_candles_polygon_2min(ticker: str, target_date: date) -> pd.DataFrame:
    """
    Fetch 3 trading days of 1-min bars, resample to 2-min.
    MAs calculated over full window so 200 MA is always populated at entry bar.
    Returns only target_date bars with fully-calculated MAs.
    """
    if not POLYGON_KEY:
        print(" [NO POLYGON KEY]", end="")
        return pd.DataFrame()
    try:
        all_rows = []
        check_date = target_date
        days_fetched = 0

        # Collect up to 4 trading days (target + 3 prior) for 200-bar window
        while days_fetched < 4:
            rows = _fetch_1min_bars(ticker, check_date.isoformat())
            if rows:
                all_rows.extend(rows)
                days_fetched += 1
            check_date -= timedelta(days=1)
            while check_date.weekday() >= 5:
                check_date -= timedelta(days=1)
            if check_date < target_date - timedelta(days=10):
                break

        if not all_rows:
            return pd.DataFrame()

        df_1 = pd.DataFrame(all_rows).set_index("timestamp").sort_index()
        df_2  = df_1.resample("2min").agg({
            "Open": "first", "High": "max",
            "Low":  "min",   "Close": "last", "Volume": "sum",
        }).dropna(subset=["Open"])

        if len(df_2) < 5:
            return pd.DataFrame()

        # MAs over full multi-day window — 200 MA always populated
        df_2["MA20"]  = df_2["Close"].rolling(20, min_periods=5).mean()
        df_2["MA200"] = df_2["Close"].rolling(200, min_periods=50).mean()

        # Return only target date bars (MAs now populated from prior days)
        target_bars = df_2[df_2.index.date == target_date]
        return target_bars if not target_bars.empty else pd.DataFrame()

    except Exception as e:
        print(f" [POLY_ERR:{str(e)[:50]}]", end="")
        return pd.DataFrame()


# ── BATCH QUOTES via Polygon snapshot ────────────────────────────────────────

def batch_fetch_live_data(tickers: list) -> dict:
    """
    Batch live quotes via Polygon snapshot.
    Returns fields matching the MDR scorer's expected keys:
      price, day_chg, rvol, gap_pct, volume
    """
    if not tickers or not POLYGON_KEY:
        return {}
    results = {}
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
            if resp.status_code != 200:
                print(f" [POLY_SNAP_ERR {resp.status_code}:{resp.text[:60]}]", end="")
                continue
            if resp.status_code == 200:
                data = resp.json()
                if i == 0 and not data.get("tickers"):
                    print(f" [POLY_SNAP_EMPTY: {str(data)[:80]}]", end="")
                for item in data.get("tickers", []):
                    sym      = str(item.get("ticker", "")).upper()
                    day      = item.get("day", {})
                    prev_day = item.get("prevDay", {})
                    price    = float(item.get("lastTrade", {}).get("p", 0)
                                     or day.get("c", 0) or 0)
                    if not sym or price <= 0:
                        continue

                    # Day change %
                    day_chg = float(item.get("todaysChangePerc", 0) or 0)

                    # Volume + RVOL (today vs yesterday)
                    vol      = float(day.get("v", 0) or 0)
                    prev_vol = float(prev_day.get("v", 0) or 0)
                    rvol     = round(vol / prev_vol, 2) if prev_vol > 0 else 0

                    # Gap % = (today open - prev close) / prev close * 100
                    day_open  = float(day.get("o", 0) or 0)
                    prev_close= float(prev_day.get("c", 0) or 0)
                    gap_pct   = round((day_open - prev_close) / prev_close * 100, 2)                                 if prev_close > 0 and day_open > 0 else 0

                    results[sym] = {
                        "price":   price,
                        "day_chg": day_chg,
                        "rvol":    rvol,
                        "gap_pct": gap_pct,
                        "volume":  int(vol),
                    }
        except Exception as e:
            print(f" [POLY_QUOTE_ERR:{str(e)[:40]}]", end="")
        if i + chunk_size < len(tickers):
            time.sleep(0.5)
    return results


# ── NEWS via Polygon ──────────────────────────────────────────────────────────

def fetch_news_polygon(ticker: str) -> list:
    """Fetch recent news from Polygon."""
    try:
        resp = requests.get(
            "https://api.polygon.io/v2/reference/news",
            params={"ticker": ticker.upper(), "limit": 5, "apiKey": POLYGON_KEY},
            timeout=10
        )
        if resp.status_code != 200:
            return []
        results = []
        for item in resp.json().get("results", []):
            title   = str(item.get("title", "") or "")
            summary = str(item.get("description", "") or "")
            results.append({"title": title, "summary": summary,
                            "text": f"{title} {summary}".lower()})
        return results
    except Exception:
        return []


# ── FLOAT via Polygon reference ───────────────────────────────────────────────

def fetch_float_polygon(ticker: str) -> str:
    """Fetch share float (millions) from Polygon ticker reference."""
    if not POLYGON_KEY:
        return ""
    try:
        resp = requests.get(
            f"https://api.polygon.io/v3/reference/tickers/{ticker.upper()}",
            params={"apiKey": POLYGON_KEY},
            timeout=10
        )
        if resp.status_code != 200:
            return ""
        result = resp.json().get("results", {})
        shares = (result.get("share_class_shares_outstanding") or
                  result.get("weighted_shares_outstanding") or 0)
        if shares and float(shares) > 0:
            return str(round(float(shares) / 1_000_000, 2))
    except Exception:
        pass
    return ""


def fetch_floats_batch(tickers: list) -> dict:
    """Fetch floats for a list of tickers. Returns {ticker: float_str}."""
    result = {}
    for ticker in tickers:
        result[ticker] = fetch_float_polygon(ticker)
        time.sleep(0.3)
    return result


# ── TOP GAINERS via Polygon ───────────────────────────────────────────────────

def fetch_top_gainers_polygon() -> list:
    """Fetch today's top % gainers via Polygon snapshot."""
    if not POLYGON_KEY:
        return []
    try:
        resp = requests.get(
            "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers",
            params={"apiKey": POLYGON_KEY, "include_otc": "true"},
            timeout=15
        )
        if resp.status_code != 200:
            print(f"  [POLY_GAINERS_ERR {resp.status_code}: {resp.text[:80]}]")
            return []
        raw = resp.json()
        if not raw.get("tickers"):
            print(f"  [POLY_GAINERS_EMPTY: {str(raw)[:80]}]")
        results = []
        for item in raw.get("tickers", []):
            sym   = str(item.get("ticker", "")).upper()
            day   = item.get("day", {})
            price = float(item.get("lastTrade", {}).get("p", 0) or day.get("c", 0) or 0)
            chg   = float(item.get("todaysChangePerc", 0) or 0)
            vol   = int(day.get("v", 0) or 0)
            if sym and price >= 0.50 and chg >= 10:
                results.append({
                    "ticker":     sym,
                    "price":      price,
                    "change_pct": chg,
                    "volume":     vol,
                    "source":     "POLYGON_GAINERS",
                })
        print(f"    Found {len(results)} qualifying gainers")
        return results[:45]
    except Exception as e:
        print(f"  [POLY_GAINERS_ERR:{str(e)[:50]}]")
        return []
