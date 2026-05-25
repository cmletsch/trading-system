"""
Google Sheets API wrapper.
Handles all reads/writes to the trading data spreadsheet.
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
import pandas as pd

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# ── Connection ────────────────────────────────────────────────────────────────

def get_client():
    """Authenticate and return a gspread client."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        raise RuntimeError("GOOGLE_CREDENTIALS environment variable not set")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def get_sheet(tab_name: str):
    """Open a specific tab in the trading spreadsheet."""
    client = get_client()
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("SPREADSHEET_ID environment variable not set")
    wb = client.open_by_key(spreadsheet_id)
    try:
        return wb.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        # Auto-create missing tabs
        return wb.add_worksheet(title=tab_name, rows=5000, cols=50)


# ── TOP GAINERS DATA ──────────────────────────────────────────────────────────

TOP_GAINERS_HEADERS = [
    "DATE", "DAY OF WEEK", "STOCK", "FLOAT", "TOD",
    "TIME IN", "TIME OUT", "RUN TIME",
    "ENTRY TYPE", "# LEGS", "A+ OPP?", "# OF RUNS ON CAL DAY",
    "TYPE OF STATE", "RANGE", "POSITION",
    "ENTRY PRICE", "EXIT PRICE", "HIGH PRICE INTRA",
    "20 MA", "200 MA",
    "GAIN $/SHARE", "GAIN %/SHARE",
    "NEWS", "NEWS TYPE",
    "NOTES",
]

def read_top_gainers(days_back: int = 90) -> pd.DataFrame:
    """Read TOP Gainers Data sheet into a DataFrame."""
    from config import SHEET_TOP_GAINERS
    ws = get_sheet(SHEET_TOP_GAINERS)
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame(columns=TOP_GAINERS_HEADERS)
    df = pd.DataFrame(data)
    if "DATE" in df.columns:
        df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=days_back)
        df = df[df["DATE"] >= cutoff]
    return df


def append_top_gainers_rows(rows: list[dict]):
    """Append new rows to TOP Gainers Data. Skips duplicates (same DATE+STOCK+TIME IN)."""
    from config import SHEET_TOP_GAINERS
    ws = get_sheet(SHEET_TOP_GAINERS)
    existing = ws.get_all_records()

    # Build a set of existing keys
    existing_keys = set()
    for r in existing:
        key = (str(r.get("DATE", "")), str(r.get("STOCK", "")), str(r.get("TIME IN", "")))
        existing_keys.add(key)

    # Ensure header row exists
    if not existing:
        ws.append_row(TOP_GAINERS_HEADERS)

    added = 0
    for row in rows:
        key = (str(row.get("DATE", "")), str(row.get("STOCK", "")), str(row.get("TIME IN", "")))
        if key in existing_keys:
            continue
        ordered = [row.get(h, "") for h in TOP_GAINERS_HEADERS]
        ws.append_row(ordered, value_input_option="USER_ENTERED")
        existing_keys.add(key)
        added += 1

    print(f"  Appended {added} new rows to {SHEET_TOP_GAINERS}")
    return added


# ── MDR TRACKING ──────────────────────────────────────────────────────────────

MDR_HEADERS = [
    "STOCK", "INITIAL BO DATE", "MDR LIST DATE",
    "ENTRY TYPE", "ENTRY TIME", "EXIT TIME", "TRADE TIME",
    "FLOAT",
    "ENTRY PRICE", "EXIT PRICE",
    "# LEGS", "20 MA", "200 MA",
    "STATE", "RANGE", "POSITION",
    "GAIN $/SHARE", "GAIN %/SHARE",
    "MDR SCORE",
    "DID IT RUN?",
    "TIER", "DAYS ON LIST", "LAST RUN DATE",
    "NEWS TYPE", "NOTES",
]

def read_mdr_tracking() -> pd.DataFrame:
    """Read MDR TRACKING sheet."""
    from config import SHEET_MDR_TRACKING
    ws = get_sheet(SHEET_MDR_TRACKING)
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame(columns=MDR_HEADERS)
    return pd.DataFrame(data)


def write_mdr_tracking(df: pd.DataFrame):
    """Overwrite MDR TRACKING sheet with updated DataFrame."""
    from config import SHEET_MDR_TRACKING
    ws = get_sheet(SHEET_MDR_TRACKING)
    ws.clear()
    # Write headers
    ws.append_row(MDR_HEADERS)
    # Write data
    for _, row in df.iterrows():
        ordered = [str(row.get(h, "")) if pd.notna(row.get(h, "")) else "" for h in MDR_HEADERS]
        ws.append_row(ordered, value_input_option="USER_ENTERED")
    print(f"  MDR TRACKING updated: {len(df)} rows")


def upsert_mdr_stock(stock_data: dict):
    """Add or update a stock in the MDR TRACKING sheet."""
    df = read_mdr_tracking()
    ticker = stock_data.get("STOCK", "")
    if ticker in df["STOCK"].values:
        idx = df.index[df["STOCK"] == ticker][0]
        for k, v in stock_data.items():
            if k in df.columns:
                df.at[idx, k] = v
    else:
        new_row = {h: stock_data.get(h, "") for h in MDR_HEADERS}
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    write_mdr_tracking(df)


# ── SCAN LOG ──────────────────────────────────────────────────────────────────

SCAN_LOG_HEADERS = ["DATE", "TICKER", "SOURCE", "TIMESTAMP", "GAIN_PCT", "PRICE"]

def log_tickers(tickers: list[dict], source: str):
    """Write ticker discoveries to SCAN LOG."""
    from config import SHEET_SCAN_LOG
    ws = get_sheet(SHEET_SCAN_LOG)
    existing = ws.get_all_records()
    if not existing:
        ws.append_row(SCAN_LOG_HEADERS)

    today = date.today().isoformat()
    ts = datetime.now().strftime("%H:%M")
    for t in tickers:
        row = [
            today,
            t.get("ticker", ""),
            source,
            ts,
            t.get("gain_pct", ""),
            t.get("price", ""),
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")


def read_today_scan_log() -> list[str]:
    """Return unique tickers logged today."""
    from config import SHEET_SCAN_LOG
    ws = get_sheet(SHEET_SCAN_LOG)
    data = ws.get_all_records()
    if not data:
        return []
    today = date.today().isoformat()
    tickers = list({
        r["TICKER"] for r in data
        if r.get("DATE") == today and r.get("TICKER")
    })
    return tickers


# ── EXPORT ────────────────────────────────────────────────────────────────────

def export_all_to_excel(output_path: str):
    """Export all sheets to a single Excel file for download."""
    from config import SHEET_TOP_GAINERS, SHEET_MDR_TRACKING, SHEET_SCAN_LOG
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default sheet

    BG_HDR = "0D1117"
    TXT_GLD = "E3B341"

    for tab_name in [SHEET_TOP_GAINERS, SHEET_MDR_TRACKING, SHEET_SCAN_LOG]:
        try:
            ws_src = get_sheet(tab_name)
            data = ws_src.get_all_values()
            ws = wb.create_sheet(title=tab_name)
            for r_idx, row in enumerate(data, 1):
                for c_idx, val in enumerate(row, 1):
                    cell = ws.cell(row=r_idx, column=c_idx, value=val)
                    if r_idx == 1:
                        cell.font = Font(color=TXT_GLD, bold=True, name="Arial", size=10)
                        cell.fill = PatternFill("solid", fgColor=BG_HDR)
                        cell.alignment = Alignment(horizontal="center")
        except Exception as e:
            print(f"  Warning: could not export {tab_name}: {e}")

    wb.save(output_path)
    print(f"  Exported all data → {output_path}")
