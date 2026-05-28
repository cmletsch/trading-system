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
            hp_raw = str(row.get("HIGH PRICE INTRA", "") or "")
            gp_raw = str(row.get("GAIN %/SHARE", "") or "").replace("%", "").strip()

            # Normalize gain percent: convert decimal (0.45) → percentage (45)
            gp_raw_clean = str(gp_raw).replace("%","").strip()
            try:
                gp_num = float(gp_raw_clean)
                if gp_num != 0 and abs(gp_num) < 2:
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
                "news":     str(row.get("NEWS", "") or ""),
                "newsType": str(row.get("NEWS TYPE", "") or ""),
            })

    # Today's new runs (not yet in Google Sheets)
    today_str = date.today().isoformat()
    existing_keys = {(r["stock"], r["date"], r["ti"]) for r in records}

    for run in today_runs:
        ticker = run.get("ticker", "").upper()
        ti     = run.get("entry_time", "")
        key    = (ticker, today_str, ti)
        if key in existing_keys:
            continue
        records.append({
            "stock":    ticker,
            "date":     today_str,
            "float":    "",
            "tod":      run.get("tod", ""),
            "ti":       ti,
            "to":       run.get("exit_time", ""),
            "et":       run.get("pattern", ""),
            "ep":       run.get("price_entry", ""),
            "xp":       run.get("price_exit",  ""),
            "hp":       run.get("price_hod",   ""),
            "ma20":     run.get("ma20",  ""),
            "ma200":    run.get("ma200", ""),
            "state":    run.get("state", ""),
            "range":    run.get("range", ""),
            "pos":      run.get("position", ""),
            "legs":     run.get("legs", ""),
            "aplus":    run.get("aplus", "N"),
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

def build_mdr_json(mdr_df: pd.DataFrame) -> dict:
    """Build mdr.json in the format dashboard.html expects."""
    records = []
    if not mdr_df.empty:
        for _, row in mdr_df.iterrows():
            stock = str(row.get("STOCK", "") or "").strip().upper()
            if not stock:
                continue
            records.append({
                "stock":    stock,
                "float":    str(row.get("FLOAT", "") or ""),
                "listDate": str(row.get("MDR LIST DATE",   "") or "")[:10],
                "boDate":   str(row.get("INITIAL BO DATE", "") or "")[:10],
                "tod":      str(row.get("TOD",        "") or ""),
                "ti":       str(row.get("ENTRY TIME", "") or ""),
                "to":       str(row.get("EXIT TIME",  "") or ""),
                "et":       str(row.get("ENTRY TYPE", "") or ""),
                "ep":       _num(str(row.get("ENTRY PRICE", "") or "")),
                "xp":       _num(str(row.get("EXIT PRICE",  "") or "")),
                "hp":       "",
                "ma20":     _num(str(row.get("20 MA",  "") or "")),
                "ma200":    _num(str(row.get("200 MA", "") or "")),
                "state":    str(row.get("STATE", "") or ""),
                "range":    _num(str(row.get("RANGE",    "") or "")),
                "pos":      _num(str(row.get("POSITION", "") or "")),
                "legs":     _num(str(row.get("# LEGS",   "") or "")),
                "score":    _num(str(row.get("MDR SCORE", "") or "")),
                "tier":     str(row.get("TIER", "") or ""),
                "days":     _num(str(row.get("DAYS ON LIST", "") or "")),
                "newsType": str(row.get("NEWS TYPE", "") or ""),
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
                ].sort_values("DATE", errors="ignore")
                exits2 = pd.to_numeric(
                    subset2.get("EXIT PRICE", pd.Series()), errors="coerce"
                ).dropna().tolist()
                escalating = len(exits2) >= 2 and all(
                    exits2[i] > exits2[i-1] for i in range(1, len(exits2))
                )

            stocks.append({
                "sym":        sym,
                "days":       int(days),
                "firstEntry": first_entry,
                "lastExit":   last_exit,
                "bestGain":   best_gain,
                "floatStr":   float_str,
                "floatRaw":   float_raw,
                "maxLegs":    int(max_legs) if max_legs else None,
                "mdrTag":     "MDR",
                "escalating": escalating,
                "addedDate":  str(row.get("MDR LIST DATE", "") or
                                  date.today().strftime("%a %b %d %Y")),
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
