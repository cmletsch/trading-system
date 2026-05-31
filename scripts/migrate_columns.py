"""
migrate_columns.py
- Deletes HIGH PRICE INTRA column from Google Sheets
- Renames NEWS → NEWS Y/N (converts headline to Y/N)
- Renames NEWS TYPE → NEWS CATEGORY
- Removes any Unnamed/DID I TRADE STOCK? columns if present
"""
import os, time
import gspread
from google.oauth2.service_account import Credentials
import json

SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

def get_ws():
    creds_json = os.environ["GOOGLE_CREDENTIALS"]
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])
    return sh.worksheet("TOP Gainers Data")

def main():
    print("=" * 50)
    print("  COLUMN MIGRATION")
    print("=" * 50)
    ws = get_ws()
    headers = ws.row_values(1)
    print(f"Current headers ({len(headers)}): {headers}")

    # ── Step 1: Delete unwanted columns (right to left to preserve indices)
    DELETE_COLS = ["HIGH PRICE INTRA", "Unnamed: 22", "DID I TRADE STOCK?"]
    to_delete = []
    for col_name in DELETE_COLS:
        stripped = [h.strip() for h in headers]
        if col_name.strip() in stripped:
            idx = stripped.index(col_name.strip()) + 1  # 1-indexed
            to_delete.append((idx, col_name))

    for idx, name in sorted(to_delete, reverse=True):
        print(f"  Deleting column {idx}: {name!r}")
        ws.delete_columns(idx)
        time.sleep(1)

    # Refresh headers
    headers = ws.row_values(1)
    print(f"\nAfter deletes ({len(headers)}): {headers}")

    # ── Step 2: Rename NEWS → NEWS Y/N, NEWS TYPE → NEWS CATEGORY
    stripped = [h.strip() for h in headers]
    renames = {"NEWS": "NEWS Y/N", "NEWS TYPE": "NEWS CATEGORY"}
    for old, new in renames.items():
        if old in stripped:
            col_idx = stripped.index(old) + 1
            ws.update_cell(1, col_idx, new)
            print(f"  Renamed col {col_idx}: {old!r} → {new!r}")
            time.sleep(0.5)

    # ── Step 3: Convert NEWS Y/N values (news headline text → Y/N)
    headers = ws.row_values(1)
    stripped = [h.strip() for h in headers]
    if "NEWS Y/N" in stripped:
        col_idx = stripped.index("NEWS Y/N") + 1
        all_vals = ws.col_values(col_idx)[1:]  # skip header
        updates = []
        for row_i, val in enumerate(all_vals, start=2):
            v = str(val).strip()
            if v and v not in ("Y", "N", ""):
                # It's a news headline — convert to Y
                updates.append({"range": f"{gspread.utils.rowcol_to_a1(row_i, col_idx)}", "values": [["Y"]]})
            elif not v:
                updates.append({"range": f"{gspread.utils.rowcol_to_a1(row_i, col_idx)}", "values": [["N"]]})
        if updates:
            # Batch in chunks of 500
            for i in range(0, len(updates), 500):
                batch = updates[i:i+500]
                ws.batch_update(batch)
                print(f"  Converted {min(i+500, len(updates))}/{len(updates)} NEWS Y/N cells")
                time.sleep(1)

    print(f"\nFinal headers ({len(headers)}): {ws.row_values(1)}")
    print("✓ Migration complete")

if __name__ == "__main__":
    main()
