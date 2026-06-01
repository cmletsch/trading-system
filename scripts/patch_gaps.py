"""
patch_gaps.py — Backfill calculable missing fields in TOP Gainers Data:
  - DOW + WEEK# from DATE
  - G/L %/SHARE from ENTRY PRICE / EXIT PRICE
  - TRADE TIME from TIME IN / TIME OUT
  - MDR WATCHLIST Y/N from current MDR TRACKING
  - 200 MA via yfinance for rows missing it
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

import gspread
import json
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import pandas as pd

SCOPES = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]

def get_sheets():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_CREDENTIALS"]), scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])
    return sh.worksheet("TOP Gainers Data"), sh.worksheet("MDR TRACKING")

def parse_time(t):
    """Parse HH:MM or H:MM string to minutes since midnight."""
    t = str(t).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            dt = datetime.strptime(t, fmt)
            return dt.hour * 60 + dt.minute
        except: pass
    return None

def fmt_duration(mins):
    if mins is None or mins < 0: return ""
    h, m = divmod(int(mins), 60)
    return f"{h}:{m:02d}" if h > 0 else f"0:{m:02d}"

def fetch_200ma(ticker, date_str):
    """Fetch 200-day MA for ticker on a specific date via yfinance."""
    try:
        import yfinance as yf
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        start = (dt - timedelta(days=300)).strftime("%Y-%m-%d")
        end   = (dt + timedelta(days=2)).strftime("%Y-%m-%d")
        hist = yf.download(ticker, start=start, end=end, interval="1d",
                           progress=False, auto_adjust=True)
        if hist.empty or len(hist) < 2: return ""
        closes = hist["Close"].dropna()
        target_closes = closes[closes.index <= pd.Timestamp(dt)]
        if len(target_closes) < 50: return ""
        ma200 = round(float(target_closes.tail(200).mean()), 4)
        return str(ma200)
    except Exception as e:
        return ""

def main():
    print("=" * 55)
    print("  PATCH GAPS")
    print("=" * 55)

    ws_tg, ws_mdr = get_sheets()

    # ── Read TOP Gainers ──
    all_vals = ws_tg.get_all_values()
    headers  = [h.strip() for h in all_vals[0]]
    print(f"Sheet: {len(all_vals)-1} rows, {len(headers)} cols")

    def ci(name): return headers.index(name) if name in headers else None
    C = {h: ci(h) for h in headers}

    # ── Read MDR Watchlist tickers ──
    mdr_vals   = ws_mdr.get_all_values()
    mdr_hdrs   = [h.strip() for h in mdr_vals[0]]
    stk_ci     = mdr_hdrs.index("STOCK") if "STOCK" in mdr_hdrs else 0
    mdr_tickers = {str(r[stk_ci]).strip().upper() for r in mdr_vals[1:] if r and r[stk_ci]}
    print(f"MDR watchlist: {len(mdr_tickers)} stocks")

    updates = []
    ma200_needed = []  # (row_i, ticker, date_str)

    for row_i, row in enumerate(all_vals[1:], start=2):
        def get(col): return str(row[C[col]]).strip() if C[col] is not None and C[col] < len(row) else ""
        def set_cell(col, val):
            if C[col] is not None and val:
                updates.append({"range": gspread.utils.rowcol_to_a1(row_i, C[col]+1), "values": [[val]]})

        date_raw = get("DATE")
        stock    = get("STOCK").upper()
        if not date_raw or not stock: continue

        # Parse date
        dt = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try: dt = datetime.strptime(date_raw[:10], fmt); break
            except: pass
        if not dt: continue

        # DOW + WEEK#
        if not get("DOW"):
            set_cell("DOW", dt.strftime("%A"))
        if not get("WEEK#"):
            set_cell("WEEK#", str(dt.isocalendar()[1]))

        # TRADE TIME from TIME IN / TIME OUT
        if not get("TRADE TIME"):
            t_in  = parse_time(get("TIME IN"))
            t_out = parse_time(get("TIME OUT"))
            if t_in is not None and t_out is not None and t_out > t_in:
                set_cell("TRADE TIME", fmt_duration(t_out - t_in))

        # G/L %/SHARE from ENTRY PRICE / EXIT PRICE
        if not get("G/L %/SHARE"):
            try:
                ep = float(get("ENTRY PRICE"))
                xp = float(get("EXIT PRICE"))
                if ep > 0:
                    gl = round((xp - ep) / ep, 6)
                    set_cell("G/L %/SHARE", str(gl))
            except (ValueError, TypeError): pass

        # STATE and RANGE — calculated from 20MA and 200MA
        if not get("STATE") or not get("RANGE"):
            try:
                ma20_v  = float(str(get("20 MA")).replace("$","").replace(",","").strip())
                ma200_v = float(str(get("200 MA")).replace("$","").replace(",","").strip())
                if ma20_v > 0 and ma200_v > 0:
                    rng = abs(ma20_v - ma200_v) / max(ma20_v, ma200_v)
                    if not get("RANGE"):
                        set_cell("RANGE", str(round(rng, 4)))
                    if not get("STATE"):
                        state = "NARROW" if rng < 0.15 else ("MEDIUM" if rng < 0.30 else "WIDE")
                        set_cell("STATE", state)
                elif ma20_v > 0:  # no 200MA
                    if not get("STATE"):
                        set_cell("STATE", "NARROW")
            except (ValueError, TypeError):
                pass

        # MDR WATCHLIST
        if C.get("MDR WATCHLIST") is not None:
            mdr_val = get("MDR WATCHLIST")
            if not mdr_val:
                set_cell("MDR WATCHLIST", "Y" if stock in mdr_tickers else "N")

        # 200 MA — queue for API fetch
        if not get("200 MA"):
            ma200_needed.append((row_i, stock, dt.strftime("%Y-%m-%d")))

    # Write calculated updates first
    print(f"\nApplying {len(updates)} calculated field updates...")
    for i in range(0, len(updates), 500):
        ws_tg.batch_update(updates[i:i+500])
        print(f"  Written {min(i+500, len(updates))}/{len(updates)}")
        time.sleep(1)

    # Fetch 200 MA via yfinance
    if ma200_needed:
        print(f"\nFetching 200 MA for {len(ma200_needed)} rows...")
        ma_updates = []
        seen = {}  # cache (ticker, date) → ma200
        for idx, (row_i, ticker, date_str) in enumerate(ma200_needed):
            key = (ticker, date_str)
            if key not in seen:
                seen[key] = fetch_200ma(ticker, date_str)
                if idx % 10 == 0:
                    print(f"  {idx+1}/{len(ma200_needed)}: {ticker} {date_str} → {seen[key] or '(none)'}")
                time.sleep(0.3)
            if seen[key]:
                ma_updates.append({"range": gspread.utils.rowcol_to_a1(row_i, C["200 MA"]+1), "values": [[seen[key]]]})

        print(f"\nWriting {len(ma_updates)} 200 MA values...")
        for i in range(0, len(ma_updates), 500):
            ws_tg.batch_update(ma_updates[i:i+500])
            time.sleep(1)

    print("\n✓ Patch complete")

if __name__ == "__main__":
    main()
