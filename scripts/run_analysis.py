"""
Calibrated 2-minute chart FGE/Blast run analysis.
Parameters tuned against 5/22/2026 template (84% match, 48/57 adjusted).
Runs on TODAY's date automatically.
"""

import yfinance as yf
import requests
import pandas as pd
import numpy as np
from datetime import date, datetime
import time
import warnings
warnings.filterwarnings("ignore")

from config import (
    MA_SHORT, MA_LONG, AVG_LOOKBACK,
    MIN_BODY_MULT, MAX_UPPER_RATIO, MAX_UPPER_RATIO_BLAST,
    LARGE_BODY_MULT, VERY_LARGE_MULT, ENTRY_FRACTION,
    MAX_ENTRY_WAIT, MIN_BODY_PCT, GRACE_BARS,
    VOL_REG, VOL_PM, VOL_AH, VOL_VERY_LARGE,
    MIN_RUN_PCT, APLUS_PCT, APLUS_FGE_LEGS,
    BLAST_MAX_LEGS, FGE_MIN_LEGS,
    PENNY_THRESHOLD, NARROW_MAX, MEDIUM_MAX,
    CONSOL_BARS, CONSOL_FACTOR,
)


# ── YF SESSION (cookie-based to avoid rate limits) ────────────────────────────

_SESSION = None

def get_yf_session():
    """Create a browser-like session to avoid Yahoo Finance rate limiting."""
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://finance.yahoo.com/',
        'DNT': '1',
    })
    try:
        s.get('https://fc.yahoo.com', timeout=8)
        time.sleep(0.5)
        s.get('https://finance.yahoo.com', timeout=8)
        time.sleep(0.5)
    except Exception:
        pass
    _SESSION = s
    return _SESSION


# ── SESSION HELPERS ───────────────────────────────────────────────────────────

def session_label(ts) -> str:
    t = ts.hour * 60 + ts.minute
    if   t <  9*60+30: return "PRE"
    elif t < 16*60:    return "REG"
    elif t < 20*60:    return "AH"
    else:              return "PM"

def tod_label(ts) -> str:
    t = ts.hour * 60 + ts.minute
    if   t <  9*60+30: return "PM"
    elif t < 16*60:    return "ID"
    elif t < 20*60:    return "AH"
    else:              return "PM"

def vol_threshold(ts, is_large: bool, is_very_large: bool) -> float:
    t = ts.hour * 60 + ts.minute
    if   t <  9*60+30: mult = VOL_PM
    elif t < 16*60:    mult = VOL_REG
    elif t < 20*60:    mult = VOL_AH
    else:              mult = VOL_PM
    if is_very_large:  return VOL_VERY_LARGE
    if is_large:       return mult * 0.5
    return mult


# ── EXIT PRICE ROUNDING ───────────────────────────────────────────────────────

def round_exit(price: float) -> float:
    step = 0.005 if price < PENNY_THRESHOLD else 0.05
    return round(np.floor(round(price / step, 6)) * step, 4)


# ── DERIVED FIELDS ────────────────────────────────────────────────────────────

def calc_range(ma20: float, ma200: float):
    if np.isnan(ma20) or np.isnan(ma200) or max(ma20, ma200) == 0:
        return None
    return abs(ma20 - ma200) / max(ma20, ma200)

def calc_state(rng) -> str:
    if rng is None:       return "N/A"
    if rng < NARROW_MAX:  return "NARROW"
    if rng < MEDIUM_MAX:  return "MEDIUM"
    return "WIDE"

def calc_position(entry_price: float, ma20: float):
    if np.isnan(ma20) or ma20 == 0: return "N/A"
    pct = (entry_price - ma20) / ma20
    if pct <= 0.10: return 1
    if pct <= 0.30: return 2
    return 3

def calc_ma_align(ma20: float, ma200: float) -> str:
    if np.isnan(ma20) or np.isnan(ma200): return "N/A"
    return "BULL" if ma20 > ma200 else "BEAR"


# ── LEG COUNTING ─────────────────────────────────────────────────────────────

def count_legs(opens: np.ndarray, closes: np.ndarray) -> int:
    if len(closes) == 0:
        return 0
    legs        = 1
    leg_peak    = 0.0
    in_pullback = False
    for i in range(len(closes)):
        is_green = closes[i] > opens[i]
        is_red   = closes[i] < opens[i]
        if is_green:
            if in_pullback and closes[i] > leg_peak:
                legs       += 1
                in_pullback = False
            if closes[i] > leg_peak:
                leg_peak = closes[i]
        elif is_red:
            in_pullback = True
    return legs


# ── CONSOLIDATION CHECK ───────────────────────────────────────────────────────

def passes_consolidation(closes: np.ndarray, entry_idx: int, fge_body: float) -> bool:
    start = max(0, entry_idx - CONSOL_BARS)
    if start >= entry_idx:
        return True
    prior = closes[start:entry_idx]
    if len(prior) == 0:
        return True
    return (prior.max() - prior.min()) < CONSOL_FACTOR * fge_body


# ── CORE: FIND ALL RUNS FOR ONE DAY ──────────────────────────────────────────

def find_all_runs(day_df: pd.DataFrame) -> list[dict]:
    n = len(day_df)
    if n < AVG_LOOKBACK + 5:
        return []

    opens  = day_df["Open"].values.astype(float)
    closes = day_df["Close"].values.astype(float)
    highs  = day_df["High"].values.astype(float)
    lows   = day_df["Low"].values.astype(float)
    vols   = day_df["Volume"].values.astype(float)
    ma20   = day_df["MA20"].values.astype(float)
    ma200  = day_df["MA200"].values.astype(float)
    times  = day_df.index

    runs         = []
    S_SCAN, S_FGE, S_RUN = 0, 1, 2
    state        = S_SCAN
    fge_idx      = None
    fge_close    = None
    fge_body     = None
    wait_count   = 0
    entry_idx    = None
    entry_price  = None
    run_hod      = None
    hod_idx      = None
    grace_count  = 0

    def rolling_avg(arr, i, window=AVG_LOOKBACK):
        s = max(0, i - window)
        v = arr[s:i]; v = v[v > 0]
        return float(np.mean(v)) if len(v) else 0.0

    def flush_run(fail_idx):
        nonlocal state, fge_idx, fge_close, fge_body, wait_count
        nonlocal entry_idx, entry_price, run_hod, hod_idx, grace_count
        if entry_idx is None or run_hod is None:
            state = S_SCAN; return
        ep  = entry_price
        xp  = round_exit(run_hod)
        if ep <= 0 or xp <= ep:
            state = S_SCAN; entry_idx = None; run_hod = None
            hod_idx = None; grace_count = 0; return
        gain = (xp - ep) / ep * 100
        if gain < MIN_RUN_PCT:
            state = S_SCAN; entry_idx = None; run_hod = None
            hod_idx = None; grace_count = 0; return
        hod_end = (hod_idx + 1) if hod_idx is not None else fail_idx
        seg_o   = opens[entry_idx:hod_end]
        seg_c   = closes[entry_idx:hod_end]
        legs    = count_legs(seg_o, seg_c)
        pattern = "Blast" if legs <= BLAST_MAX_LEGS else "FGE"
        aplus = "Y" if (
            (pattern == "Blast" and gain >= APLUS_PCT) or
            (pattern == "FGE"   and legs >= APLUS_FGE_LEGS and gain >= APLUS_PCT)
        ) else "N"
        ma20_e  = ma20[entry_idx]
        ma200_e = ma200[entry_idx]
        rng     = calc_range(ma20_e, ma200_e)
        runs.append({
            "entry_time":  times[entry_idx].strftime("%H:%M"),
            "exit_time":   times[hod_idx].strftime("%H:%M") if hod_idx else "",
            "fail_time":   times[fail_idx].strftime("%H:%M") if fail_idx < n else "Open",
            "tod":         tod_label(times[entry_idx]),
            "session":     session_label(times[entry_idx]),
            "price_entry": round(ep, 4),
            "price_exit":  xp,
            "price_hod":   round(run_hod, 4),
            "pct_gain":    round(gain, 2),
            "gain_dollar": round(xp - ep, 4),
            "pattern":     pattern,
            "legs":        legs,
            "aplus":       aplus,
            "ma20":        round(ma20_e, 4)  if not np.isnan(ma20_e)  else "N/A",
            "ma200":       round(ma200_e, 4) if not np.isnan(ma200_e) else "N/A",
            "ma_align":    calc_ma_align(ma20_e, ma200_e),
            "range":       round(rng, 4)     if rng is not None else "N/A",
            "state":       calc_state(rng),
            "position":    calc_position(ep, ma20_e),
        })
        state = S_SCAN; fge_idx = None; fge_body = None
        entry_idx = None; run_hod = None; hod_idx = None; grace_count = 0

    for i in range(n):
        ab = rolling_avg(np.abs(closes[:i] - opens[:i]), i)
        av = rolling_avg(vols, i)
        body       = closes[i] - opens[i]
        lower_tail = opens[i] - lows[i]
        upper_tail = highs[i] - closes[i]
        is_green      = closes[i] > opens[i]
        is_large      = ab > 0 and body >= LARGE_BODY_MULT * ab
        is_very_large = ab > 0 and body >= VERY_LARGE_MULT * ab

        if state == S_SCAN:
            if not is_green: continue
            if np.isnan(ma20[i]) or closes[i] <= ma20[i]: continue
            if not np.isnan(ma200[i]) and closes[i] <= ma200[i]: continue
            if ab == 0:
                if opens[i] <= 0 or body / opens[i] < MIN_BODY_PCT: continue
                is_large = body / opens[i] >= 0.05
                is_very_large = body / opens[i] >= 0.10
            else:
                large_body      = body >= MIN_BODY_MULT * ab
                large_with_tail = (body + lower_tail) >= MIN_BODY_MULT * ab
                if not (large_body or large_with_tail): continue
            tail_limit = MAX_UPPER_RATIO_BLAST if is_very_large else MAX_UPPER_RATIO
            if upper_tail > body * tail_limit: continue
            vt = vol_threshold(times[i], is_large, is_very_large)
            if av > 0 and vols[i] < vt * av: continue
            if vols[i] == 0: continue
            if ab > 0 and not passes_consolidation(closes, i, body): continue
            fge_close  = closes[i]
            fge_idx    = i
            fge_body   = body
            wait_count = 0
            if is_large:
                ep          = opens[i] + ENTRY_FRACTION * body
                state       = S_RUN
                entry_idx   = i
                entry_price = round(ep, 4)
                run_hod     = highs[i]
                hod_idx     = i
                grace_count = 0
            else:
                state = S_FGE

        elif state == S_FGE:
            wait_count += 1
            breaks_fge  = is_green and closes[i] > fge_close
            if is_green and (i == fge_idx + 1 or breaks_fge):
                state       = S_RUN
                entry_idx   = i
                entry_price = opens[i]
                run_hod     = highs[i]
                hod_idx     = i
                grace_count = 0
            elif wait_count >= MAX_ENTRY_WAIT:
                state = S_SCAN; fge_idx = None

        elif state == S_RUN:
            if highs[i] > run_hod:
                run_hod = highs[i]; hod_idx = i
            if not np.isnan(ma20[i]) and closes[i] < ma20[i]:
                grace_count += 1
                if grace_count >= GRACE_BARS:
                    flush_run(i)
            else:
                grace_count = 0

    if state == S_RUN and entry_idx is not None:
        flush_run(n)

    return runs


# ── FETCH ALL TICKERS IN ONE BATCH ───────────────────────────────────────────

def _fetch_batch(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """
    Download 2-min data for multiple tickers in a single API call.
    Returns dict of {ticker: DataFrame}. Much less likely to be rate-limited.
    """
    if not tickers:
        return {}
    session = get_yf_session()
    try:
        raw = yf.download(
            tickers=" ".join(tickers),
            period="10d",
            interval="2m",
            prepost=True,
            progress=False,
            auto_adjust=True,
            group_by="ticker",
            threads=False,
            session=session,
        )
        if raw.empty:
            return {}

        result = {}
        # Multi-ticker download returns MultiIndex columns
        if isinstance(raw.columns, pd.MultiIndex):
            for ticker in tickers:
                try:
                    df = raw[ticker].copy()
                    if not df.empty and "Close" in df.columns:
                        result[ticker] = df
                except (KeyError, Exception):
                    pass
        else:
            # Single ticker — yf collapses MultiIndex
            ticker = tickers[0]
            result[ticker] = raw.copy()

        return result
    except Exception as e:
        print(f"  Batch download failed: {str(e)[:100]}")
        return {}


def _prepare_df(raw: pd.DataFrame) -> pd.DataFrame:
    """Localize timestamps and add MAs."""
    raw.index = pd.to_datetime(raw.index)
    if raw.index.tz is None:
        raw.index = raw.index.tz_localize("UTC").tz_convert("America/New_York")
    else:
        raw.index = raw.index.tz_convert("America/New_York")
    raw["MA20"]  = raw["Close"].rolling(MA_SHORT).mean()
    raw["MA200"] = raw["Close"].rolling(MA_LONG).mean()
    return raw


# ── BATCH ANALYSIS ────────────────────────────────────────────────────────────

BATCH_SIZE = 20   # tickers per API call

def run_batch_analysis(tickers: list[str], target_date: date = None) -> list[dict]:
    if target_date is None:
        target_date = date.today()
    print(f"\n[STEP 2] Running 2-min analysis on {len(tickers)} tickers for {target_date}...")

    all_runs   = []
    total      = len(tickers)
    downloaded = {}

    # Download in batches
    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        print(f"  Downloading batch {i//BATCH_SIZE + 1}"
              f"/{(total + BATCH_SIZE - 1)//BATCH_SIZE} "
              f"({len(batch)} tickers)...", flush=True)
        batch_data = _fetch_batch(batch)
        downloaded.update(batch_data)
        if i + BATCH_SIZE < total:
            time.sleep(1.5)  # pause between batches

    print(f"  Downloaded data for {len(downloaded)}/{total} tickers")

    # Analyze each ticker
    for idx, ticker in enumerate(tickers, 1):
        print(f"  [{idx:03d}/{total}] {ticker:<8}", end="", flush=True)
        if ticker not in downloaded:
            print(f"  — no data")
            continue
        try:
            df = _prepare_df(downloaded[ticker])
            day_df = df[df.index.date == target_date].copy()
            if len(day_df) < 5:
                print(f"  — no bars today")
                continue
            runs = find_all_runs(day_df)
            if runs:
                for run in runs:
                    run["ticker"] = ticker
                    run["date"]   = target_date.isoformat()
                all_runs.extend(runs)
                print(f"  {len(runs)} run(s) — " + ", ".join(
                    f"{r['pct_gain']}% {r['pattern']}" for r in runs[:3]
                ))
            else:
                print(f"  — no qualifying run")
        except Exception as e:
            print(f"  — error: {str(e)[:60]}")

    qualifying = [r for r in all_runs if r["pct_gain"] >= MIN_RUN_PCT]
    print(f"\n  Analysis complete: {len(qualifying)} qualifying runs across "
          f"{len(set(r['ticker'] for r in qualifying))} tickers")
    return qualifying
