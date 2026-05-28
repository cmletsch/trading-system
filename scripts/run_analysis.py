"""
Calibrated 2-minute chart FGE/Blast run analysis.
Uses Polygon.io for candle data (1-min resampled to 2-min).
Parameters tuned against 5/22/2026 template (84% match).
"""

import pandas as pd
import numpy as np
from datetime import date
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
    BLAST_MAX_LEGS,
    PENNY_THRESHOLD, NARROW_MAX, MEDIUM_MAX,
    CONSOL_BARS, CONSOL_FACTOR,
)
from finnhub_client import fetch_candles_polygon_2min, POLY_DELAY


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

def vol_threshold(ts, is_large, is_very_large) -> float:
    t = ts.hour * 60 + ts.minute
    if   t <  9*60+30: mult = VOL_PM
    elif t < 16*60:    mult = VOL_REG
    elif t < 20*60:    mult = VOL_AH
    else:              mult = VOL_PM
    if is_very_large:  return VOL_VERY_LARGE
    if is_large:       return mult * 0.5
    return mult

def round_exit(price: float) -> float:
    step = 0.005 if price < PENNY_THRESHOLD else 0.05
    return round(np.floor(round(price / step, 6)) * step, 4)

def calc_range(ma20, ma200):
    if np.isnan(ma20) or np.isnan(ma200) or max(ma20, ma200) == 0:
        return None
    return abs(ma20 - ma200) / max(ma20, ma200)

def calc_state(rng) -> str:
    if rng is None:       return "N/A"
    if rng < NARROW_MAX:  return "NARROW"
    if rng < MEDIUM_MAX:  return "MEDIUM"
    return "WIDE"

def calc_position(entry_price, ma20):
    if np.isnan(ma20) or ma20 == 0: return "N/A"
    pct = (entry_price - ma20) / ma20
    if pct <= 0.10: return 1
    if pct <= 0.30: return 2
    return 3

def calc_ma_align(ma20, ma200) -> str:
    if np.isnan(ma20) or np.isnan(ma200): return "N/A"
    return "BULL" if ma20 > ma200 else "BEAR"


# ── LEG COUNTING ─────────────────────────────────────────────────────────────

def count_legs(opens, closes) -> int:
    if len(closes) == 0: return 0
    legs = 1; leg_peak = 0.0; in_pullback = False
    for i in range(len(closes)):
        is_green = closes[i] > opens[i]
        is_red   = closes[i] < opens[i]
        if is_green:
            if in_pullback and closes[i] > leg_peak:
                legs += 1; in_pullback = False
            if closes[i] > leg_peak: leg_peak = closes[i]
        elif is_red:
            in_pullback = True
    return legs

def passes_consolidation(closes, entry_idx, fge_body) -> bool:
    start = max(0, entry_idx - CONSOL_BARS)
    prior = closes[start:entry_idx]
    if len(prior) == 0: return True
    return (prior.max() - prior.min()) < CONSOL_FACTOR * fge_body


# ── CORE: FIND ALL RUNS ───────────────────────────────────────────────────────

def find_all_runs(day_df: pd.DataFrame) -> list[dict]:
    n = len(day_df)
    if n < AVG_LOOKBACK + 5: return []

    opens  = day_df["Open"].values.astype(float)
    closes = day_df["Close"].values.astype(float)
    highs  = day_df["High"].values.astype(float)
    lows   = day_df["Low"].values.astype(float)
    vols   = day_df["Volume"].values.astype(float)
    ma20   = day_df["MA20"].values.astype(float)
    ma200  = day_df["MA200"].values.astype(float)
    times  = day_df.index

    runs = []
    S_SCAN, S_FGE, S_RUN = 0, 1, 2
    state = S_SCAN
    fge_idx = fge_close = fge_body = None
    wait_count = 0
    entry_idx = entry_price = run_hod = hod_idx = None
    grace_count = 0

    def rolling_avg(arr, i, window=AVG_LOOKBACK):
        s = max(0, i - window)
        v = arr[s:i]; v = v[v > 0]
        return float(np.mean(v)) if len(v) else 0.0

    def flush_run(fail_idx):
        nonlocal state, fge_idx, fge_body, entry_idx, entry_price
        nonlocal run_hod, hod_idx, grace_count
        if entry_idx is None or run_hod is None:
            state = S_SCAN; return
        ep = entry_price
        xp = round_exit(run_hod)
        if ep <= 0 or xp <= ep:
            state = S_SCAN; entry_idx = run_hod = hod_idx = None; grace_count = 0; return
        gain = (xp - ep) / ep * 100
        if gain < MIN_RUN_PCT:
            state = S_SCAN; entry_idx = run_hod = hod_idx = None; grace_count = 0; return
        hod_end = (hod_idx + 1) if hod_idx is not None else fail_idx
        legs    = count_legs(opens[entry_idx:hod_end], closes[entry_idx:hod_end])
        pattern = "Blast" if legs <= BLAST_MAX_LEGS else "FGE"
        aplus   = "Y" if (
            (pattern == "Blast" and gain >= APLUS_PCT) or
            (pattern == "FGE" and legs >= APLUS_FGE_LEGS and gain >= APLUS_PCT)
        ) else "N"
        ma20_e = ma20[entry_idx]; ma200_e = ma200[entry_idx]
        rng    = calc_range(ma20_e, ma200_e)
        runs.append({
            "entry_time":  times[entry_idx].strftime("%H:%M"),
            "exit_time":   times[hod_idx].strftime("%H:%M") if hod_idx else "",
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
            "range":       round(rng, 4) if rng is not None else "N/A",
            "state":       calc_state(rng),
            "position":    calc_position(ep, ma20_e),
        })
        state = S_SCAN; fge_idx = fge_body = None
        entry_idx = run_hod = hod_idx = None; grace_count = 0

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
                is_large      = body / opens[i] >= 0.05
                is_very_large = body / opens[i] >= 0.10
            else:
                if not (body >= MIN_BODY_MULT * ab or
                        (body + lower_tail) >= MIN_BODY_MULT * ab): continue
            tail_limit = MAX_UPPER_RATIO_BLAST if is_very_large else MAX_UPPER_RATIO
            if upper_tail > body * tail_limit: continue
            vt = vol_threshold(times[i], is_large, is_very_large)
            if av > 0 and vols[i] < vt * av: continue
            if vols[i] == 0: continue
            if ab > 0 and not passes_consolidation(closes, i, body): continue
            fge_close = closes[i]; fge_idx = i; fge_body = body; wait_count = 0
            if is_large:
                state = S_RUN; entry_idx = i
                entry_price = round(opens[i] + ENTRY_FRACTION * body, 4)
                run_hod = highs[i]; hod_idx = i; grace_count = 0
            else:
                state = S_FGE

        elif state == S_FGE:
            wait_count += 1
            if is_green and (i == fge_idx + 1 or closes[i] > fge_close):
                state = S_RUN; entry_idx = i; entry_price = opens[i]
                run_hod = highs[i]; hod_idx = i; grace_count = 0
            elif wait_count >= MAX_ENTRY_WAIT:
                state = S_SCAN; fge_idx = None

        elif state == S_RUN:
            if highs[i] > run_hod: run_hod = highs[i]; hod_idx = i
            if not np.isnan(ma20[i]) and closes[i] < ma20[i]:
                grace_count += 1
                if grace_count >= GRACE_BARS: flush_run(i)
            else:
                grace_count = 0

    if state == S_RUN and entry_idx is not None:
        flush_run(n)
    return runs


# ── BATCH ANALYSIS ────────────────────────────────────────────────────────────

def run_batch_analysis(tickers: list[str], target_date: date = None) -> list[dict]:
    if target_date is None:
        target_date = date.today()

    print(f"\n[STEP 2] Running 2-min analysis on {len(tickers)} tickers "
          f"for {target_date} via Polygon.io...")
    print(f"  (Rate limit: 5 calls/min → ~{len(tickers) * POLY_DELAY / 60:.0f} min total)")

    all_runs = []
    for idx, ticker in enumerate(tickers, 1):
        print(f"  [{idx:03d}/{len(tickers)}] {ticker:<8}", end="", flush=True)
        try:
            df = fetch_candles_polygon_2min(ticker, target_date)
            if df.empty:
                print(f"  — no data")
            else:
                runs = find_all_runs(df)
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

        # Respect Polygon free tier: 5 calls/min
        if idx < len(tickers):
            time.sleep(POLY_DELAY)

    qualifying = [r for r in all_runs if r["pct_gain"] >= MIN_RUN_PCT]
    print(f"\n  Analysis complete: {len(qualifying)} qualifying runs across "
          f"{len(set(r['ticker'] for r in qualifying))} tickers")
    return qualifying
