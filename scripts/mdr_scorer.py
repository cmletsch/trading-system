"""
MDR scoring engine.
Scores stocks on the MDR watchlist, auto-adds qualifying new stocks,
handles timeouts and exclusions.
"""

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



def _batch_fetch_live(tickers: list[str]) -> dict:
    """Fetch live price data for all tickers via Polygon snapshot."""
    from finnhub_client import batch_fetch_live_data as batch_get_quotes
    if not tickers:
        return {}
    return batch_get_quotes(tickers)

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


def _valid_float(val: str) -> str:
    """Return numeric float string or empty if invalid (rejects time strings etc.)."""
    try:
        v = float(str(val).replace("M", "").strip())
        return str(round(v, 2)) if v > 0 else ""
    except (ValueError, TypeError):
        return ""

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

    # Must have MDR_MIN_DAYS SEPARATE calendar days (not just multiple runs same day)
    unique_days = pd.to_datetime(subset["DATE"], errors="coerce").dt.date.nunique()
    if unique_days < MDR_MIN_DAYS:
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

        # Validate entry_type — must be a real pattern, not Y/N/blank
        VALID_ENTRY_TYPES = {"FGE", "BLAST", "FGE+BLAST", "FGE/BLAST", "BREAKOUT", "BO"}
        raw_et = safe_get(latest, "ENTRY TYPE")
        entry_type = raw_et if raw_et.upper() in VALID_ENTRY_TYPES else ""
        # If latest is bad, try mode of all rows
        if not entry_type and "ENTRY TYPE" in cols:
            mode_et = subset["ENTRY TYPE"].astype(str).str.strip()
            mode_et = mode_et[mode_et.str.upper().isin(VALID_ENTRY_TYPES)]
            if not mode_et.empty:
                entry_type = mode_et.mode().iloc[0]

        # Validate # LEGS — must be numeric
        raw_legs = safe_get(latest, "# LEGS", "LEGS")
        try:
            legs_val = str(int(float(raw_legs))) if raw_legs else ""
        except (ValueError, TypeError):
            legs_val = ""

        # Validate RANGE — must be numeric
        raw_range = safe_get(latest, "RANGE")
        try:
            range_val = str(round(float(raw_range), 4)) if raw_range else ""
        except (ValueError, TypeError):
            range_val = ""

        # Validate STATE — must be a real state
        VALID_STATES = {"NARROW", "EXTENDED", "BREAKOUT", "BULL", "BEAR", "CONSOLIDATING", "SQUEEZE"}
        raw_state = safe_get(latest, "TYPE OF STATE", "STATE")
        state_val = raw_state if raw_state.upper() in VALID_STATES else ""

        # Best gain from all rows
        best_gain_d = ""
        best_gain_p = ""
        if "GAIN %/SHARE" in cols:
            gains = pd.to_numeric(subset["GAIN %/SHARE"], errors="coerce").dropna()
            if not gains.empty:
                best_pct = float(gains.max())
                # Normalize to decimal if stored as percent
                if best_pct >= 2:
                    best_pct = round(best_pct / 100, 6)
                best_gain_p = str(round(best_pct, 6))
        if "GAIN $/SHARE" in cols:
            gains_d = pd.to_numeric(subset["GAIN $/SHARE"], errors="coerce").dropna()
            if not gains_d.empty:
                best_gain_d = str(round(float(gains_d.max()), 4))

        # Best run stats (highest gain day)
        best_ti, best_to, best_rt = "", "", ""
        if "GAIN %/SHARE" in cols and not subset.empty:
            _g_series = pd.to_numeric(subset["GAIN %/SHARE"], errors="coerce")
            idx_max = _g_series.idxmax() if not _g_series.dropna().empty else None
            if idx_max is not None and pd.notna(idx_max):
                best_row = subset.loc[idx_max]
                best_ti = safe_get(best_row, "TIME IN")
                best_to = safe_get(best_row, "TIME OUT")
                best_rt = safe_get(best_row, "RUN TIME", "TRADE TIME")

        return {
            "days_count":   len(subset),
            "escalating":   escalating,
            "first_entry":  first_entry,
            "latest_date":  safe_get(latest, "DATE"),
            "latest_entry": safe_get(latest, "ENTRY PRICE", "ENTRY"),
            "latest_exit":  safe_get(latest, "EXIT PRICE", "EXIT"),
            "latest_legs":  legs_val,
            "latest_state": state_val,
            "latest_range": range_val,
            "latest_pos":   safe_get(latest, "POSITION"),
            "latest_ma20":  safe_get(latest, "20 MA", "MA20"),
            "latest_ma200": safe_get(latest, "200 MA", "MA200"),
            "float":        _valid_float(safe_get(latest, "FLOAT")),
            "entry_type":   entry_type,
            "best_gain_p":  best_gain_p,
            "best_gain_d":  best_gain_d,
            "best_ti":      best_ti,
            "best_to":      best_to,
            "best_rt":      best_rt,
        }
    except Exception as e:
        print(f"    Warning: could not build qual data for {ticker}: {e}")
        return None


# ── MAIN: UPDATE FULL WATCHLIST ───────────────────────────────────────────────

def update_mdr_watchlist(top_gainers_df: pd.DataFrame,
                          today_runs: list[dict],
                          news_map: dict,
                          target_date: date = None) -> tuple[pd.DataFrame, set]:
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
    today = target_date if target_date is not None else date.today()

    # ── Auto-add qualifying stocks from full TOP Gainers history ─────────────
    # Scan ALL historical data (not just today) — same logic as old dashboard:
    # any stock with 2+ appearances in last 90 days qualifies
    existing_tickers = set(df["STOCK"].str.upper().str.strip().tolist()) if not df.empty else set()

    # Gather all candidate tickers from history + today's runs
    history_tickers = set()
    if not top_gainers_df.empty and "STOCK" in top_gainers_df.columns:
        cutoff = (pd.Timestamp.today() - pd.Timedelta(days=MDR_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        counts = (
            top_gainers_df[pd.to_datetime(top_gainers_df["DATE"], errors="coerce")
                          >= pd.Timestamp(cutoff)]
            ["STOCK"].astype(str).str.upper().str.strip()
            .value_counts()
        )
        history_tickers = set(counts[counts >= MDR_MIN_DAYS].index)

    today_tickers  = {r["ticker"] for r in today_runs}
    all_candidates = (history_tickers | today_tickers) - existing_tickers

    new_added = 0
    for ticker in sorted(all_candidates):
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
            "ENTRY TIME":      qual["best_ti"],
            "EXIT TIME":       qual["best_to"],
            "TRADE TIME":      qual["best_rt"],
            "FLOAT":           qual["float"],
            "ENTRY PRICE":     qual["latest_entry"],
            "EXIT PRICE":      qual["latest_exit"],
            "# LEGS":          qual["latest_legs"],
            "20 MA":           qual["latest_ma20"],
            "200 MA":          qual["latest_ma200"],
            "STATE":           qual["latest_state"],
            "RANGE":           qual["latest_range"],
            "POSITION":        qual["latest_pos"],
            "GAIN $/SHARE":    qual["best_gain_d"],
            "GAIN %/SHARE":    qual["best_gain_p"],
            "LAST RUN DATE":   qual["latest_date"],
            "DAYS ON LIST":    str(qual["days_count"]),
            "NEWS TYPE":       news_map.get(ticker, {}).get("news_type", ""),
        })
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        existing_tickers.add(ticker)
        new_added += 1

    # ── Deduplicate df before scoring ────────────────────────────────────────
    df = df.drop_duplicates(subset=["STOCK"], keep="last").reset_index(drop=True)

    # ── Pre-fetch all live data in one batch ──────────────────────────────────
    all_tickers = list(dict.fromkeys([str(r.get("STOCK","")).strip().upper() for _, r in df.iterrows() if r.get("STOCK")]))
    print(f"    Pre-fetching live data for {len(all_tickers)} stocks...")
    live_cache = _batch_fetch_live(all_tickers)
    print(f"    Got live data for {len(live_cache)} stocks")

    # ── Score and update all stocks ───────────────────────────────────────────
    rows_to_remove = set()  # tickers explicitly excluded
    for idx, row in df.iterrows():
        ticker = str(row.get("STOCK", "")).strip().upper()
        if not ticker:
            continue

        print(f"    Scoring {ticker}...", end="", flush=True)

        # Days on list
        list_date = pd.to_datetime(row.get("MDR LIST DATE", ""), errors="coerce")
        days_on_list = (pd.Timestamp(today) - list_date).days if not pd.isna(list_date) else 1

        # Days since last run — only apply timeout if there IS a recorded run date
        last_run = pd.to_datetime(row.get("LAST RUN DATE", ""), errors="coerce")
        if pd.isna(last_run):
            # No run date recorded — don't timeout, stock is still being tracked
            should_weaken, should_remove = False, False
            days_since_run = 0
        else:
            days_since_run = (pd.Timestamp(today) - last_run).days
            should_weaken, should_remove = is_timed_out(days_on_list, days_since_run)

        if should_remove:
            rows_to_remove.add(ticker)
            print(f" REMOVED (timed out)")
            continue

        # Live data from cache
        live = live_cache.get(ticker, {"price": 0, "prev": 0, "open": 0,
                                        "day_chg": 0, "gap_pct": 0, "rvol": 0})

        # Exclusion: price below $0.50 — but NEVER remove if stock ran today
        ran_today = ticker in {r.get("ticker","").upper() for r in (today_runs or [])}
        if not ran_today and live["price"] > 0 and live["price"] < MDR_EXCLUDE_PRICE:
            rows_to_remove.add(ticker)
            print(f" REMOVED (price ${live['price']} < ${MDR_EXCLUDE_PRICE})")
            continue

        # Escalating exits from top gainers history
        qual = qualifies_for_watchlist(ticker, top_gainers_df)
        escalating   = qual["escalating"]   if qual else False
        try:
            first_entry = float(qual["first_entry"]) if qual and qual.get("first_entry") else 0.0
        except (ValueError, TypeError):
            first_entry = 0.0

        # Backfill any blank fields from TOP Gainers history (runs every night)
        if qual:
            def _blank(field):
                v = row.get(field, "")
                return v is None or str(v).strip() in ("", "nan", "None", "0", "0.0")
            if _blank("GAIN %/SHARE") and qual.get("best_gain_p"):
                df.at[idx, "GAIN %/SHARE"] = qual["best_gain_p"]
            if _blank("GAIN $/SHARE") and qual.get("best_gain_d"):
                df.at[idx, "GAIN $/SHARE"] = qual["best_gain_d"]
            if _blank("ENTRY PRICE") and qual.get("latest_entry"):
                df.at[idx, "ENTRY PRICE"]  = qual["latest_entry"]
            if _blank("EXIT PRICE") and qual.get("latest_exit"):
                df.at[idx, "EXIT PRICE"]   = qual["latest_exit"]
            if _blank("ENTRY TIME") and qual.get("best_ti"):
                df.at[idx, "ENTRY TIME"]   = qual["best_ti"]
            if _blank("EXIT TIME") and qual.get("best_to"):
                df.at[idx, "EXIT TIME"]    = qual["best_to"]
            if _blank("TRADE TIME") and qual.get("best_rt"):
                df.at[idx, "TRADE TIME"]   = qual["best_rt"]
            if _blank("20 MA") and qual.get("latest_ma20"):
                df.at[idx, "20 MA"]        = qual["latest_ma20"]
            if _blank("200 MA") and qual.get("latest_ma200"):
                df.at[idx, "200 MA"]       = qual["latest_ma200"]
            if _blank("FLOAT") and qual.get("float"):
                df.at[idx, "FLOAT"]        = qual["float"]
            if _blank("ENTRY TYPE") and qual.get("entry_type"):
                df.at[idx, "ENTRY TYPE"]   = qual["entry_type"]

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

        # Update all fields when stock runs today
        if ticker in {r["ticker"] for r in today_runs}:
            df.at[idx, "LAST RUN DATE"] = today.isoformat()
            qual2 = qualifies_for_watchlist(ticker, top_gainers_df)
            if qual2:
                if qual2["latest_entry"]: df.at[idx, "ENTRY PRICE"]  = qual2["latest_entry"]
                if qual2["latest_exit"]:  df.at[idx, "EXIT PRICE"]   = qual2["latest_exit"]
                if qual2["best_gain_p"]:  df.at[idx, "GAIN %/SHARE"] = qual2["best_gain_p"]
                if qual2["best_gain_d"]:  df.at[idx, "GAIN $/SHARE"] = qual2["best_gain_d"]
                if qual2["best_ti"]:      df.at[idx, "ENTRY TIME"]   = qual2["best_ti"]
                if qual2["best_to"]:      df.at[idx, "EXIT TIME"]    = qual2["best_to"]
                if qual2["best_rt"]:      df.at[idx, "TRADE TIME"]   = qual2["best_rt"]
                if qual2["latest_ma20"]:  df.at[idx, "20 MA"]        = qual2["latest_ma20"]
                if qual2["latest_ma200"]: df.at[idx, "200 MA"]       = qual2["latest_ma200"]
                if qual2["float"]:        df.at[idx, "FLOAT"]        = qual2["float"]

        # Write back scores and news
        df.at[idx, "MDR SCORE"]    = score
        df.at[idx, "TIER"]         = tier
        df.at[idx, "DAYS ON LIST"] = days_on_list
        df.at[idx, "NEWS TYPE"]    = news_cat or row.get("NEWS TYPE", "")

        print(f" score={score} → {tier}")

    # Remove timed-out/excluded stocks
    if rows_to_remove:
        df = df[~df["STOCK"].str.upper().str.strip().isin(rows_to_remove)].reset_index(drop=True)
        print(f"    Removed {len(rows_to_remove)} stocks from watchlist")

    print(f"\n  MDR Watchlist: {len(df)} stocks scored, {new_added} added today, {len(rows_to_remove)} removed")
    return df, rows_to_remove
