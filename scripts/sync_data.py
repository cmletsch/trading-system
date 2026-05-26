"""
sync_data.py — reads TOP Gainers Data + MDR TRACKING from Google Sheets
Outputs: data/gainers.json, data/mdr.json
Runs via GitHub Actions after market close (8:30 PM ET weekdays)
"""

import os, json, datetime, re
import gspread
from google.oauth2.service_account import Credentials

# ── Auth ──────────────────────────────────────────────────────────────────────
creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS'])
creds = Credentials.from_service_account_info(
    creds_json,
    scopes=[
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly'
    ]
)
gc = gspread.authorize(creds)
sh = gc.open_by_key(os.environ['SPREADSHEET_ID'])
now_utc = datetime.datetime.utcnow().isoformat() + 'Z'

# ── Helpers ───────────────────────────────────────────────────────────────────
def clean(v):
    """Return stripped string or empty string."""
    return str(v).strip() if v not in (None, '') else ''

def fmt_date(v):
    """Normalize date to YYYY-MM-DD."""
    s = clean(v)
    if not s: return ''
    if re.match(r'^\d{4}-\d{2}-\d{2}', s): return s[:10]
    try:
        for fmt in ('%m/%d/%Y', '%m/%d/%y', '%d/%m/%Y', '%B %d, %Y'):
            try: return datetime.datetime.strptime(s, fmt).strftime('%Y-%m-%d')
            except: pass
    except: pass
    return s

def fmt_time(v):
    """Normalize time to HH:MM."""
    s = clean(v)
    if not s: return ''
    m = re.search(r'(\d{1,2}):(\d{2})', s)
    if m: return f"{int(m.group(1)):02d}:{m.group(2)}"
    return s

def find_header_row(rows, key='STOCK'):
    """Find the row index where the actual column headers live."""
    for i, row in enumerate(rows[:6]):
        if any(str(c).strip().upper() == key for c in row):
            return i
    return -1

# ── Read TOP Gainers Data ─────────────────────────────────────────────────────
print("Reading TOP Gainers Data...")
try:
    ws_g = sh.worksheet('TOP Gainers Data')
except gspread.WorksheetNotFound:
    print("  ⚠ Sheet 'TOP Gainers Data' not found")
    ws_g = None

gainers = []
if ws_g:
    raw_g = ws_g.get_all_values()
    hrow = find_header_row(raw_g)
    if hrow < 0:
        print("  ⚠ Could not find header row in TOP Gainers Data")
    else:
        headers = [str(h).strip() for h in raw_g[hrow]]
        # Build lookup: lower-case header → index
        hmap = {h.lower(): i for i, h in enumerate(headers) if h}

        def gc_col(*names):
            for n in names:
                if n.lower() in hmap: return hmap[n.lower()]
            return -1

        c_date  = gc_col('date')
        c_stock = gc_col('stock')
        c_float = gc_col('float')
        c_tod   = gc_col('tod')
        c_ti    = gc_col('time in')
        c_to    = gc_col('time out')
        c_et    = gc_col('entry type')
        c_ep    = gc_col('entry price')
        c_xp    = gc_col('exit price')
        c_hp    = gc_col('high price intra (max gain)', 'high price intra')
        c_legs  = gc_col('# legs')
        c_aplus = gc_col('a+ opp?', 'a+ opp', 'aplus')
        c_runs  = gc_col('# of runs on cal day', '# runs cal day')
        c_state = gc_col('type of state', 'state')
        c_range = gc_col('range')
        c_pos   = gc_col('position')
        c_ma20  = gc_col('20 ma')
        c_ma200 = gc_col('200 ma')
        c_gainD = gc_col('gain $/share', 'gain $ / share')
        c_gainPct = gc_col('gain %/share', 'gain % / share')
        c_trd   = gc_col('did i trade stock?', 'traded')
        c_opp   = gc_col('did i trade this opp?')
        c_mdr   = gc_col('mdr watchlist', 'on mdr wl?', 'mdr wl?', 'mdr?')
        c_notes = gc_col('notes')

        def cell(row, idx):
            if idx < 0 or idx >= len(row): return ''
            return clean(row[idx])

        for row in raw_g[hrow + 1:]:
            if not any(row): continue
            stock = cell(row, c_stock).upper()
            date  = fmt_date(cell(row, c_date))
            if not stock or not date: continue
            # Only keep valid date rows
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', date): continue

            gainers.append({
                'date':    date,
                'stock':   stock,
                'float':   cell(row, c_float),
                'tod':     cell(row, c_tod),
                'ti':      fmt_time(cell(row, c_ti)),
                'to':      fmt_time(cell(row, c_to)),
                'et':      cell(row, c_et) or 'FGE',
                'ep':      cell(row, c_ep),
                'xp':      cell(row, c_xp),
                'hp':      cell(row, c_hp),
                'legs':    cell(row, c_legs),
                'aplus':   cell(row, c_aplus) or 'N',
                'runs':    cell(row, c_runs),
                'state':   cell(row, c_state),
                'range':   cell(row, c_range),
                'pos':     cell(row, c_pos),
                'ma20':    cell(row, c_ma20),
                'gainD':   cell(row, c_gainD),
                'gainPct': cell(row, c_gainPct),
                'gainPct': cell(row, c_gain_),
                'traded':  cell(row, c_trd),
                'ts':      cell(row, c_opp),
                'mdrWl':   'Y' if cell(row, c_mdr).upper() == 'Y' else '',
                'notes':   cell(row, c_notes),
            })
    print(f"  ✓ {len(gainers)} gainer records")

# ── Read MDR TRACKING ─────────────────────────────────────────────────────────
print("Reading MDR TRACKING...")
try:
    ws_m = sh.worksheet('MDR TRACKING')
except gspread.WorksheetNotFound:
    print("  ⚠ Sheet 'MDR TRACKING' not found")
    ws_m = None

mdr_records = []
if ws_m:
    raw_m = ws_m.get_all_values()
    hrow_m = find_header_row(raw_m)
    if hrow_m < 0:
        print("  ⚠ Could not find header row in MDR TRACKING")
    else:
        hdrs_m = [str(h).strip() for h in raw_m[hrow_m]]
        for row in raw_m[hrow_m + 1:]:
            if not any(row): continue
            rec = {hdrs_m[i]: clean(row[i]) for i in range(min(len(hdrs_m), len(row))) if hdrs_m[i]}
            stock = rec.get('STOCK', '').upper()
            if not stock: continue
            mdr_records.append({
                'stock':    stock,
                'float':    rec.get('Float', rec.get('FLOAT', '')),
                'listDate': fmt_date(rec.get('MDR List Date', rec.get('MDR LIST DATE', ''))),
                'boDate':   fmt_date(rec.get('Initial BO Date', rec.get('INITIAL BO DATE', ''))),
                'didRun':   rec.get('Did It Run?', ''),
                'et':       rec.get('Entry Type', rec.get('ENTRY TYPE', 'FGE')),
                'ti':       fmt_time(rec.get('Entry Time', rec.get('TIME IN', ''))),
                'to':       fmt_time(rec.get('Exit Time', rec.get('TIME OUT', ''))),
                'ep':       rec.get('Entry Price', rec.get('ENTRY PRICE', '')),
                'xp':       rec.get('Exit Price', rec.get('EXIT PRICE', '')),
                'legs':     rec.get('# Legs', rec.get('# LEGS', '')),
                'ma20':     rec.get('20 MA', ''),
                'ma200':    rec.get('200 MA', ''),
                'state':    rec.get('State', rec.get('STATE', '')),
                'range':    rec.get('Range', rec.get('RANGE', '')),
                'pos':      rec.get('Position', rec.get('POSITION', '')),
                'gainD':    rec.get('Gain $/Share', ''),
                'gainPct':  rec.get('Gain %/Share', ''),
                'score':    rec.get('MDR SCORE', ''),
                'tod':      rec.get('TOD', ''),
            })
    print(f"  ✓ {len(mdr_records)} MDR records")

# ── Write JSON files ──────────────────────────────────────────────────────────
os.makedirs('data', exist_ok=True)

with open('data/gainers.json', 'w') as f:
    json.dump({'updated': now_utc, 'count': len(gainers), 'records': gainers}, f)

with open('data/mdr.json', 'w') as f:
    json.dump({'updated': now_utc, 'count': len(mdr_records), 'records': mdr_records}, f)

print(f"\n✅ Done — {len(gainers)} gainers + {len(mdr_records)} MDR records written to data/")
