"""
Runner capture: records every stock that ran RUNNER_MIN_PCT% or more in a session,
no matter how the chart looked (the FGE/Blast detector only catches clean patterns).

How a runner is measured (same method as the site's AH & PM list), from 5-minute
bars that include extended hours:
  PRE (4:00-9:30)    peak vs the PRIOR regular-session close
  REG (9:30-16:00)   peak vs the PRIOR regular-session close
  AH  (16:00-20:00)  peak vs TODAY's 4 PM close
A session counts when (peak - reference) / reference >= RUNNER_MIN_PCT.

Row written: entry = lowest low in the session before the peak, exit = the peak,
pct_gain = entry -> exit (same meaning as existing rows). The move vs the
reference price and the session volume go in NOTES.

Sources of tickers: Webull gainers (regular / pre / after), Polygon gainers,
MDR watchlist, scan log, plus anything passed in.
"""
import time
import requests
import pandas as pd
import pytz
from datetime import date

from config import RUNNER_MIN_PCT, RUNNER_MIN_VOL, YF_MIN_PRICE, YF_MAX_PRICE

ET = pytz.timezone("America/New_York")
WEBULL_URL = "https://quotes-gw.webullfintech.com/api/bgw/market/topGainers"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


# ── ticker sources ────────────────────────────────────────────────────────────

def webull_gainers(rank_type: str, min_pct: float) -> list:
    """rank_type: '1d' (regular day), 'preMarket' or 'afterMarket'."""
    out = []
    try:
        r = requests.get(WEBULL_URL, params={
            "regionId": 6, "rankType": rank_type, "pageIndex": 1, "pageSize": 100,
        }, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return out
        for it in (r.json() or {}).get("data", []) or []:
            sym = str((it.get("ticker") or {}).get("symbol", "")).upper()
            try:
                pct = float((it.get("values") or {}).get("changeRatio", 0)) * 100
            except Exception:
                pct = 0
            if sym and sym.isalpha() and len(sym) <= 6 and pct >= min_pct:
                out.append(sym)
    except Exception as e:
        print(f"  [Webull {rank_type} error: {str(e)[:60]}]")
    return out


def gather_candidates(extra=None) -> list:
    """Loose pre-filter (60% of the threshold); the bars decide who really qualifies."""
    loose = RUNNER_MIN_PCT * 0.6
    names = []
    for rank in ("1d", "preMarket", "afterMarket"):
        got = webull_gainers(rank, loose)
        print(f"  Webull {rank}: {len(got)} names")
        names += got
    try:
        from finnhub_client import fetch_top_gainers_polygon
        names += [g["ticker"] for g in fetch_top_gainers_polygon()]
    except Exception as e:
        print(f"  [Polygon gainers error: {str(e)[:60]}]")
    names += list(extra or [])
    seen, uniq = set(), []
    for t in names:
        t = str(t).upper().strip()
        if t and t.isalpha() and len(t) <= 6 and t not in seen:
            seen.add(t); uniq.append(t)
    return uniq


# ── bars ──────────────────────────────────────────────────────────────────────

def fetch_5m(ticker: str, days: int = 60) -> pd.DataFrame:
    """5-minute bars with pre/post market, ET index. Yahoo keeps ~60 days.
    Uses the same raw chart endpoint the rest of this project already uses
    (yfinance's cookie/crumb login is blocked on GitHub runners)."""
    rng = "60d" if days > 30 else f"{max(days, 5)}d"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    data = None
    for attempt in range(3):
        try:
            r = requests.get(url, params={"interval": "5m", "range": rng,
                                          "includePrePost": "true"},
                             headers=HEADERS, timeout=20)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1)); continue
            if r.status_code != 200:
                return pd.DataFrame()
            data = r.json(); break
        except Exception:
            time.sleep(1)
    try:
        res = ((data or {}).get("chart") or {}).get("result")
        if not res:
            return pd.DataFrame()
        r0 = res[0]
        ts = r0.get("timestamp") or []
        q = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
        df = pd.DataFrame({
            "Open": q.get("open"), "High": q.get("high"), "Low": q.get("low"),
            "Close": q.get("close"), "Volume": q.get("volume"),
        }, index=pd.to_datetime(ts, unit="s", utc=True))
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        df["Volume"] = df["Volume"].fillna(0)
        df.index = df.index.tz_convert(ET)
        return df
    except Exception:
        return pd.DataFrame()


# ── detection ─────────────────────────────────────────────────────────────────

SESSIONS = (("PRE", 240, 570, "PM"), ("REG", 570, 960, "ID"), ("AH", 960, 1200, "AH"))


def runners_from_bars(ticker: str, df: pd.DataFrame, min_pct: float = None,
                      only_date: date = None) -> list:
    """Return runner dicts (same keys the EOD rows use) for every qualifying
    ticker-day-session in df. only_date restricts to one trading day."""
    min_pct = RUNNER_MIN_PCT if min_pct is None else min_pct
    if df.empty:
        return []
    mins = df.index.hour * 60 + df.index.minute
    days = sorted(set(df.index.date))
    out, prev_close = [], None
    for d in days:
        day_df = df[df.index.date == d]
        dm = mins[df.index.date == d]
        reg = day_df[(dm >= 570) & (dm < 960)]
        reg_close = float(reg["Close"].iloc[-1]) if len(reg) else None
        if prev_close and prev_close > 0 and (only_date is None or d == only_date):
            for label, lo, hi, tod in SESSIONS:
                sess = day_df[(dm >= lo) & (dm < hi)]
                if sess.empty:
                    continue
                ref = reg_close if label == "AH" else prev_close
                if not ref or ref < YF_MIN_PRICE or ref > YF_MAX_PRICE:
                    continue
                hi_arr = sess["High"].values
                k = int(hi_arr.argmax())
                peak = float(hi_arr[k])
                move = (peak - ref) / ref * 100
                if move < min_pct:
                    continue
                upto = sess.iloc[:k + 1]
                low = float(upto["Low"].min())
                low_t = upto["Low"].idxmin()
                if low <= 0 or low >= peak:
                    continue
                vol = int(upto["Volume"].sum())
                if vol < RUNNER_MIN_VOL:
                    continue
                out.append({
                    "ticker": ticker, "date": d.isoformat(),
                    "entry_time": low_t.strftime("%H:%M"),
                    "exit_time": sess.index[k].strftime("%H:%M"),
                    "tod": tod, "session": label,
                    "price_entry": round(low, 4), "price_exit": round(peak, 4),
                    "price_hod": round(peak, 4),
                    "pct_gain": round((peak - low) / low * 100, 2),
                    "gain_dollar": round(peak - low, 4),
                    "pattern": "RUNNER", "legs": "", "aplus": "N",
                    "ma20": "", "ma200": "", "range": "N/A", "state": "", "position": "",
                    "move_pct": round(move, 1), "ref": round(ref, 4), "vol": vol,
                    "note": f"RUNNER {label}: +{move:.0f}% vs {'4PM close' if label=='AH' else 'prior close'} "
                            f"${ref:.3f}; vol {vol:,}",
                })
        if reg_close:
            prev_close = reg_close
    return out


def capture_runners(target_date: date, extra_tickers=None, existing_runs=None) -> list:
    """Nightly entry point: runners for target_date only."""
    print(f"\n[RUNNER CAPTURE] threshold +{RUNNER_MIN_PCT:.0f}% for {target_date}")
    names = gather_candidates(extra_tickers)
    print(f"  Checking {len(names)} candidates on 5m extended-hours bars...")
    have = {(r.get("ticker"), r.get("session")) for r in (existing_runs or [])}
    found = []
    for i, t in enumerate(names, 1):
        df = fetch_5m(t, days=10)
        for r in runners_from_bars(t, df, only_date=target_date):
            if (t, r["session"]) in have:
                continue  # a FGE/Blast row already covers this session
            found.append(r)
            print(f"  RUNNER {t:<6} {r['session']:<3} +{r['move_pct']:.0f}%  "
                  f"{r['entry_time']}->{r['exit_time']}  vol {r['vol']:,}")
        time.sleep(0.4)
    print(f"  Runner capture: {len(found)} runner rows")
    return found
