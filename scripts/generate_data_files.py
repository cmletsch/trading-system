"""
Generates data/gainers.json and data/mdr.json for the existing dashboards,
and calls the Netlify watchlist function to auto-update the watchlist.

gainers.json  → read by dashboard.html (Top Gainers tab)
mdr.json      → read by dashboard.html (MDR Tracking tab)
save-tickers  → called to update watchlist.html
"""

import json
import os
import requests
import pandas as pd
from datetime import datetime, date


NETLIFY_WATCHLIST_URL = "https://rage-traders.netlify.app/.netlify/functions/save-tickers"


# ── GAINERS.JSON ──────────────────────────────────────────────────────────────

def build_gainers_json(top_gainers_df: pd.DataFrame, today_runs: list[dict]) -> dict:
    """
    Build gainers.json in the format dashboard.html expects.
    Merges historical Google Sheets data with today's new runs.
    """
    records = []

    # Historical records from Google Sheets
    if not top_gainers_df.empty:
        for _, row in top_gainers_df.iterrows():
            stock = str(row.get("STOCK", "") or "").strip().upper()
            dt    = str(row.get("DATE", "") or "")[:10]
            if not stock or not dt:
                continue

            ep_raw = str(row.get("ENTRY PRICE", "") or "")
            xp_raw = str(row.get("EXIT PRICE",  "") or "")
            hp_raw = ""  # HIGH PRICE INTRA removed
            gp_raw = str(row.get("GAIN %/SHARE", "") or "").replace("%", "").strip()

            # Normalize gain percent: convert decimal (0.45) → percentage (45)
            gp_raw_clean = str(gp_raw).replace("%","").strip()
            try:
                gp_num = float(gp_raw_clean)
                # Historical data: stored as decimal (0.67 = 67%)
                # Automated data: stored as percentage (47.87 = 47.87%)
                # Heuristic: if < 10, assume decimal and multiply by 100
                if gp_num != 0 and abs(gp_num) < 10:
                    gp_num = round(gp_num * 100, 2)
                gainPct = str(round(gp_num, 2)) + "%"
            except Exception:
                gainPct = ""

            records.append({
                "stock":    stock,
                "date":     dt,
                "float":    str(row.get("FLOAT", "") or ""),
                "tod":      str(row.get("TOD", "") or ""),
                "ti":       str(row.get("TIME IN",  "") or ""),
                "to":       str(row.get("TIME OUT", "") or ""),
                "et":       str(row.get("ENTRY TYPE", "") or ""),
                "legs":     str(_num(str(row.get("# LEGS", "") or ""))),
                "aplus":    "Y" if str(row.get("A+ OPP?","")).upper().strip()=="Y" else "N",
                "runs":     str(row.get("# OF RUNS ON CAL DAY", "") or ""),
                "state":    str(row.get("TYPE OF STATE", "") or ""),
                "range":    str(_num(str(row.get("RANGE", "") or ""))),
                "pos":      str(_num(str(row.get("POSITION", "") or ""))),
                "ep":       str(_num(ep_raw)),
                "xp":       str(_num(xp_raw)),
                "hp":       str(_num(hp_raw)),
                "ma20":     str(_num(str(row.get("20 MA",  "") or ""))),
                "ma200":    str(_num(str(row.get("200 MA", "") or ""))),
                "gainD":    str(_num(str(row.get("GAIN $/SHARE", "") or ""))),
                "gainPct":  gainPct,
                "traded":   "N",
                "notes":    str(row.get("NOTES", "") or ""),
                "mdrWl":    "",
                "news":     str(row.get("NEWS Y/N", "") or ""),
                "newsType": str(row.get("NEWS CATEGORY", "") or ""),
            })

    # Today's new runs (not yet in Google Sheets)
    # Use trading date (same as eod_update uses) to avoid duplicate records
    try:
        from datetime import timedelta
        import pytz
        _et  = pytz.timezone("America/New_York")
        _now = datetime.now(_et)
        _d   = _now.date()
        if _now.hour < 16:
            _d -= timedelta(days=1)
        while _d.weekday() >= 5:
            _d -= timedelta(days=1)
        today_str = _d.isoformat()
    except Exception:
        today_str = date.today().isoformat()
    existing_keys = {(r["stock"], r["date"], r["ti"]) for r in records}

    for run in today_runs:
        ticker = run.get("ticker", "").upper()
        ti     = run.get("entry_time", "")
        key    = (ticker, today_str, ti)
        if key in existing_keys:
            continue
        ep = run.get("price_entry", "")
        xp = run.get("price_exit",  "")
        try:
            _gain_d = round(float(xp) - float(ep), 4) if ep and xp else ""
            _gain_p = str(round(float(run.get("pct_gain", 0)), 2)) + "%" if run.get("pct_gain") else ""
        except Exception:
            _gain_d, _gain_p = "", ""
        records.append({
            "stock":    ticker,
            "date":     today_str,
            "float":    str(run.get("float", "") or ""),
            "tod":      run.get("tod", ""),
            "ti":       ti,
            "to":       run.get("exit_time", ""),
            "et":       run.get("pattern", ""),
            "ep":       str(ep),
            "xp":       str(xp),
            "hp":       str(run.get("price_hod", "")),
            "ma20":     str(run.get("ma20",  "")),
            "ma200":    str(run.get("ma200", "")),
            "gainD":    str(_gain_d),
            "gainPct":  _gain_p,
            "state":    run.get("state", ""),
            "range":    run.get("range", ""),
            "pos":      run.get("position", ""),
            "legs":     run.get("legs", ""),
            "aplus":    run.get("aplus", "N"),
            "traded":   "N",
            "news":     "",
            "newsType": "",
            "notes":    "",
            "ts":       run.get("state", ""),
            "mdrWl":    "",
        })
        existing_keys.add(key)

    return {
        "updated": datetime.utcnow().isoformat() + "Z",
        "records": records,
    }


# ── MDR.JSON ──────────────────────────────────────────────────────────────────

def build_mdr_json(mdr_df: pd.DataFrame, top_gainers_df: pd.DataFrame = None) -> dict:
    """
    Build mdr.json with full watchlist card data including daily history,
    dates array, and escalating flag — sourced from TOP Gainers history.
    """
    records = []

    # Build lookup from TOP Gainers for daily data
    tg_by_stock = {}
    if top_gainers_df is not None and not top_gainers_df.empty:
        for _, tg_row in top_gainers_df.iterrows():
            sym = str(tg_row.get("STOCK", "") or "").strip().upper()
            if not sym:
                continue
            try:
                d = pd.to_datetime(tg_row.get("DATE"), errors="coerce")
                if pd.isna(d):
                    continue
                ep_raw = tg_row.get("ENTRY PRICE", "") or ""
                xp_raw = tg_row.get("EXIT PRICE",  "") or ""
                gp_raw = tg_row.get("GAIN %/SHARE", "") or ""

                def _parse_price(v):
                    """Parse price — handles floats, strings, dollar signs."""
                    try:
                        return float(str(v).replace("$","").replace(",","").strip())
                    except (ValueError, TypeError):
                        return None

                def _parse_gain(v):
                    """Parse gain — handles 0.49 (decimal), 49 (pct), '49%' (str pct)."""
                    if v is None or v == "":
                        return None
                    try:
                        s = str(v).replace("%","").replace(",","").strip()
                        g = float(s)
                        return g / 100 if abs(g) >= 2 else g
                    except (ValueError, TypeError):
                        return None

                try:
                    ep = _parse_price(ep_raw) if ep_raw else None
                    xp = _parse_price(xp_raw) if xp_raw else None
                    gp = _parse_gain(gp_raw) if gp_raw else None
                except (ValueError, TypeError):
                    ep = xp = gp = None

                if sym not in tg_by_stock:
                    tg_by_stock[sym] = []
                tg_by_stock[sym].append({
                    "date": d.strftime("%Y-%m-%d"),
                    "ep": round(ep, 4) if ep else None,
                    "xp": round(xp, 4) if xp else None,
                    "gp": round(gp, 4) if gp else None,
                })
            except Exception:
                continue

    if not mdr_df.empty:
        for _, row in mdr_df.iterrows():
            stock = str(row.get("STOCK", "") or "").strip().upper()
            if not stock:
                continue

            # Build daily array from TOP Gainers history
            raw_days = tg_by_stock.get(stock, [])
            # Group by date, average entry/exit/gain per day
            by_date = {}
            for r in raw_days:
                dt = r["date"]
                if dt not in by_date:
                    by_date[dt] = {"entries": [], "exits": [], "gains": []}
                if r["ep"]: by_date[dt]["entries"].append(r["ep"])
                if r["xp"]: by_date[dt]["exits"].append(r["xp"])
                if r["gp"]: by_date[dt]["gains"].append(r["gp"])

            daily = []
            for dt in sorted(by_date.keys()):
                d = by_date[dt]
                avg_ep = round(sum(d["entries"]) / len(d["entries"]), 4) if d["entries"] else None
                avg_xp = round(sum(d["exits"]) / len(d["exits"]), 4) if d["exits"] else None
                avg_gp = round(sum(d["gains"]) / len(d["gains"]), 4) if d["gains"] else None
                daily.append({"date": dt, "ep": avg_ep, "xp": avg_xp, "gp": avg_gp})

            # Escalating: each day's exit > previous day's exit
            escalating = False
            if len(daily) >= 2:
                exits = [d["xp"] for d in daily if d["xp"]]
                if len(exits) >= 2:
                    escalating = all(exits[i] > exits[i-1] for i in range(1, len(exits)))

            # Dates array from actual trading days
            dates = sorted(set(d["date"] for d in daily)) if daily else []

            records.append({
                "stock":       stock,
                "float":       str(row.get("FLOAT", "") or ""),
                "listDate":    str(row.get("MDR LIST DATE",   "") or "")[:10],
                "boDate":      str(row.get("INITIAL BO DATE", "") or "")[:10],
                "tod":         str(row.get("TOD",        "") or ""),
                "ti":          str(row.get("ENTRY TIME", "") or ""),
                "to":          str(row.get("EXIT TIME",  "") or ""),
                "et":          str(row.get("ENTRY TYPE", "") or ""),
                "ep":          (daily[0]["ep"] if daily and daily[0].get("ep") else _num(str(row.get("ENTRY PRICE", "") or ""))),
                "xp":          (daily[-1]["xp"] if daily and daily[-1].get("xp") else _num(str(row.get("EXIT PRICE", "") or ""))),
                "ma20":        _num(str(row.get("20 MA",  "") or "")),
                "ma200":       _num(str(row.get("200 MA", "") or "")),
                "state":       str(row.get("STATE", "") or ""),
                "range":       _num(str(row.get("RANGE",    "") or "")),
                "pos":         _num(str(row.get("POSITION", "") or "")),
                "legs":        _num(str(row.get("# LEGS",   "") or "")),
                "score":       _num(str(row.get("MDR SCORE", "") or "")),
                "tier":        str(row.get("TIER", "") or ""),
                "days":        _num(str(row.get("DAYS ON LIST", "") or "")),
                "newsType":    str(row.get("NEWS CATEGORY", "") or ""),
                "lastRunDate": str(row.get("LAST RUN DATE", "") or "")[:10],
                "daily":       daily,
                "dates":       dates,
                "escalating":  escalating,
            })
    return {
        "updated": datetime.utcnow().isoformat() + "Z",
        "records": records,
    }


# ── WATCHLIST UPDATE ──────────────────────────────────────────────────────────

def build_watchlist_payload(mdr_df: pd.DataFrame,
                             top_gainers_df: pd.DataFrame) -> dict:
    """
    Build the payload for /.netlify/functions/save-tickers
    in the format watchlist.html expects.
    """
    stocks = []
    tickers = []

    if not mdr_df.empty:
        cutoff = (pd.Timestamp.today() - pd.Timedelta(days=90)).strftime("%Y-%m-%d")

        for _, row in mdr_df.iterrows():
            sym = str(row.get("STOCK", "") or "").strip().upper()
            if not sym:
                continue

            tickers.append(sym)
            days = _num(str(row.get("DAYS ON LIST", "") or "")) or 1

            # Calculate firstEntry, lastExit, bestGain from top gainers history
            first_entry = _num(str(row.get("ENTRY PRICE", "") or "")) or None
            last_exit   = _num(str(row.get("EXIT PRICE",  "") or "")) or None
            best_gain   = None

            if not top_gainers_df.empty and "STOCK" in top_gainers_df.columns:
                subset = top_gainers_df[
                    top_gainers_df["STOCK"].astype(str).str.upper().str.strip() == sym
                ]
                if not subset.empty:
                    if "ENTRY PRICE" in subset.columns:
                        entries = pd.to_numeric(subset["ENTRY PRICE"], errors="coerce").dropna()
                        if not entries.empty:
                            first_entry = float(entries.min())
                    if "EXIT PRICE" in subset.columns:
                        exits = pd.to_numeric(subset["EXIT PRICE"], errors="coerce").dropna()
                        if not exits.empty:
                            last_exit = float(exits.max())
                    if "GAIN %/SHARE" in subset.columns:
                        gains = pd.to_numeric(
                            subset["GAIN %/SHARE"].astype(str).str.replace("%","").str.strip(),
                            errors="coerce"
                        ).dropna()
                        if not gains.empty:
                            best_gain = float(gains.max())

            # Float
            float_raw = None
            float_str = "-"
            fval = str(row.get("FLOAT", "") or "").strip()
            if fval:
                try:
                    fnum = float(fval.replace("M","").replace("m","").replace(",",""))
                    if "M" in fval.upper():
                        float_raw = fnum
                    elif fnum > 1000:
                        float_raw = fnum / 1_000_000
                    else:
                        float_raw = fnum
                    float_str = f"{float_raw:.2f}M"
                except Exception:
                    pass

            # Max legs
            max_legs = _num(str(row.get("# LEGS", "") or "")) or None

            escalating = False
            if not top_gainers_df.empty and "STOCK" in top_gainers_df.columns \
               and "EXIT PRICE" in top_gainers_df.columns:
                subset2 = top_gainers_df[
                    top_gainers_df["STOCK"].astype(str).str.upper().str.strip() == sym
                ].sort_values("DATE")
                exits2 = pd.to_numeric(
                    subset2.get("EXIT PRICE", pd.Series()), errors="coerce"
                ).dropna().tolist()
                escalating = len(exits2) >= 2 and all(
                    exits2[i] > exits2[i-1] for i in range(1, len(exits2))
                )

            # Build dates list from TOP Gainers history for this stock
            stock_dates = []
            if not top_gainers_df.empty and "STOCK" in top_gainers_df.columns and "DATE" in top_gainers_df.columns:
                try:
                    mask = top_gainers_df["STOCK"].astype(str).str.upper().str.strip() == sym
                    stock_rows = top_gainers_df[mask]
                    unique_dates = sorted(set(
                        str(d)[:10] for d in pd.to_datetime(stock_rows["DATE"], errors="coerce").dropna()
                    ))
                    stock_dates = unique_dates[-90:]  # last 90 unique days
                except Exception:
                    stock_dates = []

            added_date = str(row.get("MDR LIST DATE", "") or date.today().strftime("%a %b %d %Y"))
            last_run = str(row.get("LAST RUN DATE", "") or "")[:10]

            stocks.append({
                "sym":        sym,
                "days":       int(days),
                "dates":      stock_dates,
                "firstEntry": first_entry,
                "lastExit":   last_exit,
                "bestGain":   best_gain,
                "floatStr":   float_str,
                "floatRaw":   float_raw,
                "maxLegs":    int(max_legs) if max_legs else None,
                "mdrTag":     "MDR",
                "escalating": escalating,
                "addedDate":  added_date,
                "lastRunDate": last_run,
            })

    return {
        "tickers":    tickers,
        "stocks":     stocks,
        "benchmarks": {"totalMdr": len(stocks)},
        "fileDate":   date.today().isoformat(),
    }


def update_netlify_watchlist(payload: dict) -> bool:
    """POST payload to Netlify save-tickers function."""
    try:
        resp = requests.post(
            NETLIFY_WATCHLIST_URL,
            json=payload,
            timeout=20,
            headers={"Content-Type": "application/json"},
        )
        if resp.ok:
            print(f"  Watchlist updated: {len(payload['tickers'])} stocks")
            return True
        else:
            print(f"  Watchlist update failed: {resp.status_code} {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"  Watchlist update error: {e}")
        return False


# ── WRITE FILES ───────────────────────────────────────────────────────────────

def write_data_files(gainers_data: dict, mdr_data: dict):
    """Write JSON files to data/ folder for GitHub commit."""
    os.makedirs("data", exist_ok=True)
    with open("data/gainers.json", "w") as f:
        json.dump(gainers_data, f, default=str)
    with open("data/mdr.json", "w") as f:
        json.dump(mdr_data, f, default=str)
    print(f"  data/gainers.json — {len(gainers_data['records'])} records")
    print(f"  data/mdr.json     — {len(mdr_data['records'])} records")


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _num(s: str):
    """Convert string to number, return empty string if not numeric."""
    try:
        v = float(str(s).replace(",", "").strip())
        return int(v) if v == int(v) else v
    except Exception:
        return ""
