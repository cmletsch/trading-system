"""
sync_data.py — reads TOP Gainers Data + MDR TRACKING from Google Sheets
Outputs: data/gainers.json, data/mdr.json, data/news.json
Runs via GitHub Actions after market close (8:30 PM ET weekdays)
"""

import os, json, datetime, re, time
import urllib.request, urllib.error
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
    return str(v).strip() if v not in (None, '') else ''

def fmt_date(v):
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
    s = clean(v)
    if not s: return ''
    m = re.search(r'(\d{1,2}):(\d{2})', s)
    if m: return f"{int(m.group(1)):02d}:{m.group(2)}"
    return s

def find_header_row(rows, key='STOCK'):
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
                'ma200':   cell(row, c_ma200),
                'gainD':   cell(row, c_gainD),
                'gainPct': cell(row, c_gainPct),
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

# ── Fetch News from Yahoo Finance ─────────────────────────────────────────────
print("\nFetching news headlines...")

def fetch_news(symbol, retries=2):
    """Fetch top news headlines for a ticker from Yahoo Finance."""
    url = (
        f'https://query1.finance.yahoo.com/v1/finance/search'
        f'?q={symbol}&newsCount=5&quotesCount=0&enableFuzzyQuery=false'
    )
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json',
    }
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            items = data.get('news', [])
            results = []
            for item in items[:5]:
                title = item.get('title', '')
                pub   = item.get('publisher', '')
                ts    = item.get('providerPublishTime', 0)
                link  = item.get('link', '')
                if title:
                    results.append({
                        'title': title,
                        'publisher': pub,
                        'date': datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d') if ts else '',
                        'url': link,
                    })
            return results
        except Exception as e:
            if attempt < retries:
                time.sleep(1)
            else:
                print(f"    ⚠ {symbol}: {e}")
    return []

# Get unique tickers — only those that appeared in last 90 days (keep it focused)
cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
recent_tickers = sorted(set(r['stock'] for r in gainers if r.get('date', '') >= cutoff))
print(f"  Fetching news for {len(recent_tickers)} tickers from last 90 days...")

news_data = {}
for i, sym in enumerate(recent_tickers):
    headlines = fetch_news(sym)
    if headlines:
        news_data[sym] = headlines
    if (i + 1) % 10 == 0:
        print(f"  ... {i+1}/{len(recent_tickers)} done")
    time.sleep(0.3)  # polite rate limiting

print(f"  ✓ News fetched for {len(news_data)} of {len(recent_tickers)} tickers")

# ── Write JSON files ──────────────────────────────────────────────────────────
os.makedirs('data', exist_ok=True)

with open('data/gainers.json', 'w') as f:
    json.dump({'updated': now_utc, 'count': len(gainers), 'records': gainers}, f)

with open('data/mdr.json', 'w') as f:
    json.dump({'updated': now_utc, 'count': len(mdr_records), 'records': mdr_records}, f)

with open('data/news.json', 'w') as f:
    json.dump({'updated': now_utc, 'tickers': len(news_data), 'data': news_data}, f)

print(f"\n✅ Done — {len(gainers)} gainers + {len(mdr_records)} MDR + {len(news_data)} tickers with news")
