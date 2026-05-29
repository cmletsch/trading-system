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

    # ── Step 1: Identify bad rows ────────────────────────────────────────────
    # Bad rows = ENTRY TYPE is Y/N (old column-mapping bug) OR numeric (tonight's shift bug)
    import re as _re
    bad_row_indices = []
    for i, row in enumerate(all_values[1:], start=2):
        if et_col >= 0 and len(row) > et_col:
            et = str(row[et_col]).strip().upper()
            # Y/N from old bug, or numeric from tonight's column-shift bug
            if et in ('Y', 'N') or _re.match(r'^\d+\.?\d*$', et):
                bad_row_indices.append(i)

    print(f"\nStep 1: Found {len(bad_row_indices)} bad rows (Y/N or numeric ENTRY TYPE)")
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
        print(f"  Normalizing {fixed_count} rows from percent to decimal (batch update)...")
        # Use batch_update to avoid rate limits — single API call per chunk
        import time
        chunk_size = 500
        for chunk_start in range(0, len(updates), chunk_size):
            chunk = updates[chunk_start:chunk_start + chunk_size]
            cell_updates = []
            for row_i, col_i, val in chunk:
                col_letter = chr(ord("A") + col_i - 1)
                cell_updates.append({
                    "range":  f"{col_letter}{row_i}",
                    "values": [[val]],
                })
            ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
            print(f"  Updated {min(chunk_start + chunk_size, len(updates))}/{len(updates)}")
            time.sleep(2)  # Respect rate limits between chunks
    else:
        print("  All GAIN %/SHARE values already in decimal format ✓")


    # ── Step 2b: Delete all automated rows (May 27+) — wrong columns pre-cleanup
    print("\nStep 2b: Deleting all automated rows (DATE >= 2026-05-27)...")
    ws_tg_fresh = get_sheet(SHEET_TOP_GAINERS)
    all_vals_fresh = ws_tg_fresh.get_all_values()
    if all_vals_fresh:
        hdrs = [h.strip() for h in all_vals_fresh[0]]
        date_col = hdrs.index("DATE") if "DATE" in hdrs else 0
        bad_auto = []
        for i, row in enumerate(all_vals_fresh[1:], start=2):
            if len(row) > date_col:
                raw_d = str(row[date_col]).strip()[:10]
                if raw_d >= "2026-05-27":
                    bad_auto.append(i)
        if bad_auto:
            print(f"  Found {len(bad_auto)} automated rows to delete (rows {bad_auto[0]}-{bad_auto[-1]})")
            ws_tg_fresh.delete_rows(bad_auto[0], bad_auto[-1])
            print(f"  Deleted automated rows — workflow will re-add with correct columns")
        else:
            print("  No automated rows found (already clean)")

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
