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
YAHOO_DELAY = 1.2  # Yahoo has no per-minute cap like Polygon's old free tier — much lighter pacing is safe
ET          = pytz.timezone("America/New_York")


def _fetch_1min_bars(ticker: str, date_str: str) -> list:
    """Fetch 1-min bars for a single date via Yahoo Finance (free, no API key).

    NOTE: This used to call Polygon's /v2/aggs/.../range/1/minute/... endpoint.
    Polygon discontinued free-tier access to that endpoint (~2026-06-29) and it now
    returns 403 NOT_AUTHORIZED on every call. The old code silently treated any
    non-200 response as 'no data' (returned []), so this failure was invisible —
    the EOD script kept reporting SUCCESS while finding zero qualifying runs, every
    night, since 6/29. Switched to Yahoo's chart API, which needs no key and is
    already used successfully elsewhere in this project (the Netlify screener).
    Yahoo retains 1-minute granularity for roughly the trailing 7 calendar days,
    which comfortably covers the 4-trading-day lookback this function needs.
    """
    try:
        target = date.fromisoformat(date_str)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
        resp = requests.get(url, params={
            "interval": "1m", "range": "8d", "includePrePost": "true",
        }, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        result = (data.get("chart", {}) or {}).get("result")
        if not result:
            return []
        r0 = result[0]
        timestamps = r0.get("timestamp") or []
        quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
        opens  = quote.get("open")  or []
        highs  = quote.get("high")  or []
        lows   = quote.get("low")   or []
        closes = quote.get("close") or []
        vols   = quote.get("volume") or []
        rows = []
        for i, ts in enumerate(timestamps):
            try:
                t = pd.Timestamp(ts, unit="s", tz="UTC").tz_convert(ET)
                if t.date() != target:
                    continue  # only keep bars for the requested day
                o, h, l, c = opens[i], highs[i], lows[i], closes[i]
                if o is None or h is None or l is None or c is None:
                    continue  # Yahoo pads gaps with nulls — skip them
                v = vols[i] if i < len(vols) and vols[i] is not None else 0
                rows.append({"timestamp": t,
                             "Open": float(o), "High": float(h),
                             "Low": float(l), "Close": float(c),
                             "Volume": float(v)})
            except Exception:
                continue
        return rows
    except Exception:
        return []


def fetch_candles_polygon_2min(ticker: str, target_date: date) -> pd.DataFrame:
    """
    Fetch 3 trading days of 1-min bars (via Yahoo Finance — see _fetch_1min_bars),
    resample to 2-min. MAs calculated over full window so 200 MA is always
    populated at entry bar. Returns only target_date bars with fully-calculated MAs.
    """
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
    Batch live quotes via Yahoo Finance (free, no API key).

    NOTE: This used to call Polygon's /v2/snapshot/.../tickers endpoint, which
    hit the same free-tier cutoff as the candle fetch above (403 NOT_AUTHORIZED).
    Switched to Yahoo's v7/finance/quote batch endpoint — the same proven pattern
    already used successfully elsewhere in this project's Netlify functions.
    Returns fields matching the MDR scorer's expected keys:
      price, day_chg, rvol, gap_pct, volume
    """
    if not tickers:
        return {}
    results = {}
    chunk_size = 75
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://finance.yahoo.com/",
        "Origin": "https://finance.yahoo.com",
    }
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        sym_str = ",".join(chunk)
        got_any = False
        for host in ("query1", "query2"):
            try:
                resp = requests.get(
                    f"https://{host}.finance.yahoo.com/v7/finance/quote",
                    params={"symbols": sym_str, "formatted": "false",
                            "lang": "en-US", "region": "US"},
                    headers=headers, timeout=15,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                quotes = ((data or {}).get("quoteResponse") or {}).get("result") or []
                if not quotes:
                    continue
                got_any = True
                for item in quotes:
                    sym = str(item.get("symbol", "")).upper()
                    if not sym:
                        continue
                    price = float(item.get("regularMarketPrice", 0) or 0)
                    # Prefer extended-hours price if that's the live session
                    if item.get("marketState") == "PRE" and item.get("preMarketPrice"):
                        price = float(item["preMarketPrice"])
                    elif item.get("marketState") == "POST" and item.get("postMarketPrice"):
                        price = float(item["postMarketPrice"])
                    if price <= 0:
                        continue

                    prev_close = float(item.get("regularMarketPreviousClose", 0) or 0)
                    day_open   = float(item.get("regularMarketOpen", 0) or 0)
                    day_chg = float(item.get("regularMarketChangePercent", 0) or 0)
                    if prev_close > 0:
                        day_chg = round((price - prev_close) / prev_close * 100, 2)

                    vol = float(item.get("regularMarketVolume", 0) or 0)
                    if item.get("marketState") == "PRE" and item.get("preMarketVolume"):
                        vol = float(item["preMarketVolume"])
                    elif item.get("marketState") == "POST" and item.get("postMarketVolume"):
                        vol = float(item["postMarketVolume"])
                    avg_vol = float(item.get("averageDailyVolume10Day", 0)
                                    or item.get("averageDailyVolume3Month", 0) or 0)
                    rvol = round(vol / avg_vol, 2) if avg_vol > 0 else 0

                    gap_pct = round((day_open - prev_close) / prev_close * 100, 2) \
                        if prev_close > 0 and day_open > 0 else 0

                    results[sym] = {
                        "price":   price,
                        "day_chg": day_chg,
                        "rvol":    rvol,
                        "gap_pct": gap_pct,
                        "volume":  int(vol),
                    }
                break  # this host worked, no need to try the other
            except Exception as e:
                print(f" [YAHOO_QUOTE_ERR:{str(e)[:40]}]", end="")
        if not got_any and i == 0:
            print(" [YAHOO_QUOTE_EMPTY]", end="")
        if i + chunk_size < len(tickers):
            time.sleep(0.3)
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
