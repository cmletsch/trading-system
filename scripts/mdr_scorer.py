"""
MDR scoring engine.
Scores stocks on the MDR watchlist, auto-adds qualifying new stocks,
handles timeouts and exclusions.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

from config import (
    MDR_LOOKBACK_DAYS, MDR_MIN_DAYS,
    MDR_SCORE_DAYS, MDR_SCORE_ESCALATING, MDR_SCORE_PRICE_GTE,
    MDR_SCORE_DAY_CHANGE, MDR_SCORE_RVOL, MDR_SCORE_GAP,
    MDR_SCORE_PATTERNS, NEWS_SCORES,
    MDR_TIER_STRONG_REGULAR, MDR_TIER_STRONG_EXTENDED, MDR_TIER_WATCH,
    MDR_OVERRIDE_DAY_LOSS, MDR_OVERRIDE_PRICE_PCT,
    MDR_TIMEOUT, MDR_EXCLUDE_PRICE,
)


# ── LIVE DATA ─────────────────────────────────────────────────────────────────

def fetch_live_data(ticker: str) -> dict:
    """Fetch current price, rvol, gap, day change for scoring."""
    safe = {"price": 0, "prev": 0, "open": 0, "day_chg": 0, "gap_pct": 0, "rvol": 0}
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="5d", interval="1d")
        if hist.empty:
            return safe

        inf    = t.fast_info
        price  = float(getattr(inf, "last_price", 0) or 0)
        if price == 0 and not hist.empty:
            price = float(hist["Close"].iloc[-1])

        prev   = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else float(hist["Close"].iloc[-1])
        open_p = float(hist["Open"].iloc[-1])  if len(hist) >= 1 else 0

        avg_vol = hist["Volume"].replace(0, np.nan).mean()
        cur_vol = float(hist["Volume"].iloc[-1]) if len(hist) >= 1 else 0

        day_chg = ((price - prev) / prev * 100) if prev > 0 else 0
        gap_pct = ((open_p - prev) / prev * 100) if prev > 0 else 0
        rvol    = (cur_vol / avg_vol) if avg_vol and avg_vol > 0 else 0

        return {
            "price":   round(price,   4),
            "prev":    round(prev,    4),
            "open":    round(open_p,  4),
            "day_chg": round(day_chg, 2),
            "gap_pct": round(gap_pct, 2),
            "rvol":    round(rvol,    2),
        }
    except Exception:
        return safe


# ── PATTERN DETECTION ─────────────────────────────────────────────────────────

def detect_pattern(ticker: str, live: dict) -> str:
    """Simple pattern detection from recent daily bars."""
    try:
        hist = yf.Ticker(ticker).history(period="5d", interval="1d")
        if len(hist) < 3:
            return "Unknown"
        closes = hist["Close"].values
        c0, c1, c2 = closes[-1], closes[-2], closes[-3]

        if c0 > c1 > c2:
            return "Breakout"
        if abs(c0 - c1) / c1 < 0.03 and abs(c1 - c2) / c2 < 0.03:
            return "Consolidating"
        if c0 >= c1 * 0.97:
            return "Holding"
        if c0 < c1 * 0.90:
            return "Fading"
        return "Pulling"
    except Exception:
        return "Unknown"


# ── SCORING ───────────────────────────────────────────────────────────────────

def calc_mdr_score(stock_row: dict, live: dict, days_on_list: int,
                   escalating: bool, first_entry: float,
                   news_category: str = "") -> int:
    """
    Calculate MDR score (0-100) using full scoring rules.
    """
    sc = 0
    price = live.get("price", 0)

    # Hard overrides → score = 0
    if live.get("day_chg", 0) <= MDR_OVERRIDE_DAY_LOSS:
        return 0
    if first_entry > 0 and price < first_entry * MDR_OVERRIDE_PRICE_PCT:
        return 0

    # Days on watchlist
    if days_on_list >= 3:
        sc += MDR_SCORE_DAYS["3+"]
    elif days_on_list >= 2:
        sc += MDR_SCORE_DAYS["2"]

    # Escalating exits
    if escalating:
        sc += MDR_SCORE_ESCALATING

    # Price vs first entry
    if first_entry > 0:
        if price >= first_entry:
            sc += MDR_SCORE_PRICE_GTE
        elif price >= first_entry * 0.85:
            sc += 4

    # Day change
    if live.get("day_chg", 0) > 0:
        sc += MDR_SCORE_DAY_CHANGE

    # RVOL
    rvol = live.get("rvol", 0)
    for threshold in sorted(MDR_SCORE_RVOL.keys(), reverse=True):
        if rvol >= threshold:
            sc += MDR_SCORE_RVOL[threshold]
            break

    # Gap
    gap = live.get("gap_pct", 0)
    for threshold in sorted(MDR_SCORE_GAP.keys(), reverse=True):
        if gap >= threshold:
            sc += MDR_SCORE_GAP[threshold]
            break

    # Pattern
    pattern = detect_pattern(stock_row.get("STOCK", ""), live)
    for pat_key, pat_score in MDR_SCORE_PATTERNS.items():
        if pat_key in pattern:
            sc += pat_score
            break

    # News
    if news_category:
        sc += NEWS_SCORES.get(news_category, 0)

    return max(0, min(100, sc))


def get_tier(score: int, session: str = "regular") -> str:
    """Return tier label based on score and session."""
    threshold = MDR_TIER_STRONG_EXTENDED if session in ("premarket", "afterhours") \
                else MDR_TIER_STRONG_REGULAR
    if score >= threshold:
        return "Strong Setup"
    if score >= MDR_TIER_WATCH:
        return "Watch"
    return "Weakening"


# ── TIMEOUT CHECK ─────────────────────────────────────────────────────────────

def is_timed_out(days_on_list: int, days_since_last_run: int) -> tuple[bool, bool]:
    """
    Returns (should_weaken, should_remove) based on timeout rules.
    """
    for (min_days, max_days), (weaken_at, remove_at) in MDR_TIMEOUT.items():
        if min_days <= days_on_list <= max_days:
            if days_since_last_run >= remove_at:
                return True, True
            if days_since_last_run >= weaken_at:
                return True, False
    return False, False


# ── QUALIFY CHECK ─────────────────────────────────────────────────────────────

def qualifies_for_watchlist(ticker: str, top_gainers_df: pd.DataFrame) -> dict | None:
    """
    Check if a ticker qualifies for the MDR watchlist.
    Needs 2+ top-gainer days with valid entry/exit in last 90 days.
    Returns qualifying data dict or None.
    """
    if top_gainers_df.empty:
        return None

    ticker = ticker.upper().strip()
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=MDR_LOOKBACK_DAYS)

    cols = top_gainers_df.columns.tolist()

    # Require STOCK and DATE at minimum
    if "STOCK" not in cols or "DATE" not in cols:
        return None

    try:
        mask = (
            (top_gainers_df["STOCK"].astype(str).str.upper().str.strip() == ticker) &
            (pd.to_datetime(top_gainers_df["DATE"], errors="coerce") >= cutoff)
        )
        if "ENTRY PRICE" in cols:
            mask &= (top_gainers_df["ENTRY PRICE"].astype(str).str.strip() != "")
        if "EXIT PRICE" in cols:
            mask &= (top_gainers_df["EXIT PRICE"].astype(str).str.strip() != "")
        subset = top_gainers_df[mask]
    except Exception as e:
        print(f"    Warning: could not filter {ticker}: {e}")
        return None

    if len(subset) < MDR_MIN_DAYS:
        return None

    if len(subset) < MDR_MIN_DAYS:
        return None

    try:
        sorted_sub = subset.sort_values("DATE")
        latest     = sorted_sub.iloc[-1]

        # Escalating exits
        if "EXIT PRICE" in cols:
            exits = pd.to_numeric(sorted_sub["EXIT PRICE"], errors="coerce").dropna()
            escalating = all(exits.iloc[i] > exits.iloc[i-1] for i in range(1, len(exits)))
        else:
            escalating = False

        # First entry price
        if "ENTRY PRICE" in cols:
            first_entry = pd.to_numeric(sorted_sub["ENTRY PRICE"].iloc[0], errors="coerce")
            first_entry = float(first_entry) if not pd.isna(first_entry) else 0
        else:
            first_entry = 0

        def safe_get(row, *keys):
            for k in keys:
                v = row.get(k, "")
                if v not in ("", None): return str(v)
            return ""

        return {
            "days_count":   len(subset),
            "escalating":   escalating,
            "first_entry":  first_entry,
            "latest_date":  safe_get(latest, "DATE"),
            "latest_entry": safe_get(latest, "ENTRY PRICE", "ENTRY"),
            "latest_exit":  safe_get(latest, "EXIT PRICE", "EXIT"),
            "latest_legs":  safe_get(latest, "# LEGS", "LEGS"),
            "latest_state": safe_get(latest, "TYPE OF STATE", "STATE"),
            "latest_range": safe_get(latest, "RANGE"),
            "latest_pos":   safe_get(latest, "POSITION"),
            "latest_ma20":  safe_get(latest, "20 MA", "MA20"),
            "latest_ma200": safe_get(latest, "200 MA", "MA200"),
            "float":        safe_get(latest, "FLOAT"),
            "entry_type":   safe_get(latest, "ENTRY TYPE"),
        }
    except Exception as e:
        print(f"    Warning: could not build qual data for {ticker}: {e}")
        return None


# ── MAIN: UPDATE FULL WATCHLIST ───────────────────────────────────────────────

def update_mdr_watchlist(top_gainers_df: pd.DataFrame,
                          today_runs: list[dict],
                          news_map: dict) -> pd.DataFrame:
    """
    Full MDR watchlist update:
    1. Score all existing stocks
    2. Auto-add new qualifying stocks from today's runs
    3. Apply timeouts and exclusions
    Returns updated MDR DataFrame.
    """
    from sheets_client import read_mdr_tracking, MDR_HEADERS
    print("\n[STEP 4] Updating MDR Watchlist...")

    df = read_mdr_tracking()
    today = date.today()

    # ── Auto-add new stocks from today's runs ─────────────────────────────────
    today_tickers = list({r["ticker"] for r in today_runs})
    existing_tickers = set(df["STOCK"].str.upper().str.strip().tolist()) if not df.empty else set()

    new_added = 0
    for ticker in today_tickers:
        if ticker in existing_tickers:
            continue
        qual = qualifies_for_watchlist(ticker, top_gainers_df)
        if not qual:
            continue

        print(f"    + Adding {ticker} to MDR watchlist ({qual['days_count']} qualifying days)")
        new_row = {h: "" for h in MDR_HEADERS}
        new_row.update({
            "STOCK":           ticker,
            "INITIAL BO DATE": qual["latest_date"],
            "MDR LIST DATE":   today.isoformat(),
            "ENTRY TYPE":      qual["entry_type"],
            "FLOAT":           qual["float"],
            "ENTRY PRICE":     qual["latest_entry"],
            "EXIT PRICE":      qual["latest_exit"],
            "# LEGS":          qual["latest_legs"],
            "20 MA":           qual["latest_ma20"],
            "200 MA":          qual["latest_ma200"],
            "STATE":           qual["latest_state"],
            "RANGE":           qual["latest_range"],
            "POSITION":        qual["latest_pos"],
            "LAST RUN DATE":   today.isoformat(),
            "DAYS ON LIST":    "1",
            "NEWS TYPE":       news_map.get(ticker, {}).get("news_type", ""),
        })
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        existing_tickers.add(ticker)
        new_added += 1

    # ── Score and update all stocks ───────────────────────────────────────────
    rows_to_remove = []
    for idx, row in df.iterrows():
        ticker = str(row.get("STOCK", "")).strip().upper()
        if not ticker:
            continue

        print(f"    Scoring {ticker}...", end="", flush=True)

        # Days on list
        list_date = pd.to_datetime(row.get("MDR LIST DATE", ""), errors="coerce")
        days_on_list = (pd.Timestamp(today) - list_date).days if not pd.isna(list_date) else 1

        # Days since last run
        last_run = pd.to_datetime(row.get("LAST RUN DATE", ""), errors="coerce")
        days_since_run = (pd.Timestamp(today) - last_run).days if not pd.isna(last_run) else 999

        # Check timeout
        should_weaken, should_remove = is_timed_out(days_on_list, days_since_run)
        if should_remove:
            rows_to_remove.append(idx)
            print(f" REMOVED (timed out)")
            continue

        # Live data
        live = fetch_live_data(ticker)

        # Exclusion: price below $0.50 (we check current price)
        if live["price"] > 0 and live["price"] < MDR_EXCLUDE_PRICE:
            rows_to_remove.append(idx)
            print(f" REMOVED (price ${live['price']} < ${MDR_EXCLUDE_PRICE})")
            continue

        # Escalating exits from top gainers history
        qual = qualifies_for_watchlist(ticker, top_gainers_df)
        escalating   = qual["escalating"]   if qual else False
        first_entry  = qual["first_entry"]  if qual else 0

        # News
        news_cat = news_map.get(ticker, {}).get("news_type", "")

        # Score
        score = calc_mdr_score(
            row.to_dict(), live, days_on_list,
            escalating, first_entry, news_cat
        )

        if should_weaken:
            score = min(score, MDR_TIER_WATCH - 1)

        tier = get_tier(score)

        # Update last run date if stock ran today
        if ticker in {r["ticker"] for r in today_runs}:
            df.at[idx, "LAST RUN DATE"] = today.isoformat()

        # Write back
        df.at[idx, "MDR SCORE"]   = score
        df.at[idx, "TIER"]        = tier
        df.at[idx, "DAYS ON LIST"] = days_on_list
        df.at[idx, "NEWS TYPE"]   = news_cat or row.get("NEWS TYPE", "")

        print(f" score={score} → {tier}")

    # Remove timed-out/excluded stocks
    if rows_to_remove:
        df = df.drop(index=rows_to_remove).reset_index(drop=True)
        print(f"    Removed {len(rows_to_remove)} stocks from watchlist")

    print(f"\n  MDR Watchlist: {len(df)} stocks total, {new_added} added today")
    return df
