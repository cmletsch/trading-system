"""
cleanup_sheets.py — One-time fix for Google Sheets data issues:
1. Delete 198 bad May 27 automated rows (ENTRY TYPE = Y/N)
2. Normalize GAIN %/SHARE to decimal format throughout
Run once via: python scripts/cleanup_sheets.py
"""
import sys
import pandas as pd
from sheets_client import get_sheet, TOP_GAINERS_HEADERS
from config import SHEET_TOP_GAINERS
from config import SHEET_TOP_GAINERS

def run_cleanup():
    print("=" * 60)
    print("  GOOGLE SHEETS CLEANUP")
    print("=" * 60)

    ws = get_sheet(SHEET_TOP_GAINERS)
    print("\nReading all rows...")
    all_values = ws.get_all_values()
    
    if not all_values:
        print("Sheet is empty!")
        return

    headers = [h.strip() for h in all_values[0]]
    print(f"Sheet has {len(all_values)-1} data rows, {len(headers)} columns")

    # Find ENTRY TYPE and GAIN %/SHARE column indices
    def col_idx(name):
        try: return headers.index(name)
        except ValueError: return -1

    et_col   = col_idx("ENTRY TYPE")
    gain_col = col_idx("GAIN %/SHARE")
    date_col = col_idx("DATE")

    print(f"ENTRY TYPE col: {et_col}, GAIN %/SHARE col: {gain_col}")

    # ── Step 1: Identify bad rows (ENTRY TYPE = Y or N) ──────────────────────
    bad_row_indices = []  # 1-based sheet row indices (header = row 1)
    for i, row in enumerate(all_values[1:], start=2):  # row 2 = first data row
        if et_col >= 0 and len(row) > et_col:
            et = str(row[et_col]).strip().upper()
            if et in ('Y', 'N'):
                bad_row_indices.append(i)

    print(f"\nStep 1: Found {len(bad_row_indices)} bad rows (ENTRY TYPE=Y/N)")
    if bad_row_indices:
        print(f"  Rows: {bad_row_indices[0]} to {bad_row_indices[-1]}")
        
        # Delete in reverse order to preserve row indices
        print("  Deleting bad rows...")
        # Batch delete by finding contiguous ranges
        if bad_row_indices:
            # All bad rows are contiguous (1204-1401 in 1-indexed data = rows 1205-1402 in sheet)
            start_row = bad_row_indices[0]
            end_row   = bad_row_indices[-1]
            ws.delete_rows(start_row, end_row)
            print(f"  Deleted sheet rows {start_row} to {end_row} ({end_row - start_row + 1} rows)")

    # ── Step 2: Re-read and normalize GAIN %/SHARE ────────────────────────────
    print("\nStep 2: Normalizing GAIN %/SHARE format...")
    all_values = ws.get_all_values()  # re-read after deletion
    headers = [h.strip() for h in all_values[0]]
    gain_col = col_idx("GAIN %/SHARE")

    updates = []  # list of (row_idx, col_idx, new_value) — 1-based
    fixed_count = 0
    
    for i, row in enumerate(all_values[1:], start=2):
        if gain_col < 0 or len(row) <= gain_col:
            continue
        val = str(row[gain_col]).strip().replace('%', '')
        if not val:
            continue
        try:
            v = float(val)
            # If >= 2, it's already a percentage — convert to decimal
            if v >= 2:
                new_val = round(v / 100, 6)
                updates.append((i, gain_col + 1, new_val))  # col is 1-based for update
                fixed_count += 1
        except ValueError:
            continue

    if updates:
        print(f"  Normalizing {fixed_count} rows from percent to decimal...")
        # Batch update in chunks of 100
        for chunk_start in range(0, len(updates), 100):
            chunk = updates[chunk_start:chunk_start + 100]
            for row_i, col_i, val in chunk:
                ws.update_cell(row_i, col_i, val)
            print(f"  Updated {min(chunk_start + 100, len(updates))}/{len(updates)}")
    else:
        print("  All GAIN %/SHARE values already in decimal format ✓")


    # ── Step 3: Delete unwanted columns ──────────────────────────────────────────
    print("\nStep 3: Removing unwanted columns from TOP Gainers Data...")
    COLS_TO_DELETE = ["Column1", "Column2", "ON ORACLE?", "DID I TRADE STOCK?"]

    ws_tg = get_sheet(SHEET_TOP_GAINERS)
    headers = [h.strip() for h in ws_tg.row_values(1)]
    
    # Find column indices (1-based) in reverse order so deletion doesn't shift indices
    col_indices = sorted(
        [headers.index(c) + 1 for c in COLS_TO_DELETE if c in headers],
        reverse=True
    )
    
    if col_indices:
        for col_idx in col_indices:
            col_name = headers[col_idx - 1]
            ws_tg.delete_columns(col_idx)
            print(f"  Deleted column: {col_name}")
    else:
        print("  Columns already removed ✓")

    print("\n" + "=" * 60)
    print("  CLEANUP COMPLETE")
    print("=" * 60)
    print("\nNext step: Run the EOD workflow to re-append the 33 correct May 27 rows")

if __name__ == "__main__":
    run_cleanup()
