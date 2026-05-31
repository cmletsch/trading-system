"""
migrate_columns.py — Fix Google Sheets TOP Gainers column structure:
- Delete blank/empty column header (was Unnamed:22)
- Strip leading/trailing spaces from all headers
- Add NEWS Y/N and NEWS CATEGORY before NOTES
"""
import os, sys, time, json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]

def get_ws():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_CREDENTIALS"]), scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])
    return sh.worksheet("TOP Gainers Data")

def col_letter(n):
    return gspread.utils.rowcol_to_a1(1, n)[:-1]

def main():
    print("=" * 50)
    print("  COLUMN MIGRATION v2")
    print("=" * 50)
    ws = get_ws()
    headers = ws.row_values(1)
    print(f"Current headers ({len(headers)}): {headers}")

    # ── Step 1: Delete any columns with blank/empty headers
    to_delete = [i+1 for i, h in enumerate(headers) if h.strip() == ""]
    for idx in sorted(to_delete, reverse=True):
        print(f"  Deleting blank column {idx}")
        ws.delete_columns(idx)
        time.sleep(1)

    # ── Step 2: Strip spaces from all headers
    headers = ws.row_values(1)
    stripped = [h.strip() for h in headers]
    if headers != stripped:
        print(f"  Stripping spaces from headers...")
        ws.update([stripped], f"1:1")
        time.sleep(1)

    # ── Step 3: Add NEWS Y/N and NEWS CATEGORY before NOTES (if not already there)
    headers = ws.row_values(1)
    stripped_hdrs = [h.strip() for h in headers]
    if "NEWS Y/N" not in stripped_hdrs:
        notes_idx = next((i+1 for i, h in enumerate(stripped_hdrs) if h.strip() == "NOTES"), None)
        if notes_idx:
            ws.insert_cols([[]], col=notes_idx)
            ws.insert_cols([[]], col=notes_idx)
            ws.update_cell(1, notes_idx,   "NEWS Y/N")
            ws.update_cell(1, notes_idx+1, "NEWS CATEGORY")
            print(f"  Added NEWS Y/N + NEWS CATEGORY before NOTES at col {notes_idx}")
            time.sleep(1)

    final = ws.row_values(1)
    print(f"\nFinal headers ({len(final)}): {final}")
    print("✓ Migration complete")

if __name__ == "__main__":
    main()
