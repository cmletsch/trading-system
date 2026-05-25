"""
Generates the FGE Top Gainers Opps dashboard HTML.
Reads from TOP Gainers Data (FGE entries only, Sheet 1).
"""

import pandas as pd
import numpy as np
from datetime import datetime, date
import json


def generate_fge_dashboard(df: pd.DataFrame, output_path: str):
    """Generate FGE_Top_Gainer_Opps style dashboard from TOP Gainers Data."""
    print(f"  Generating FGE dashboard → {output_path}")

    # Filter FGE only, Sheet 1 data
    if df.empty:
        fge_df = pd.DataFrame()
    else:
        fge_mask = df["ENTRY TYPE"].astype(str).str.upper().str.contains("FGE", na=False)
        fge_df = df[fge_mask].copy()

    # Prepare stats
    total_opps   = len(fge_df)
    avg_gain     = round(pd.to_numeric(fge_df["GAIN %/SHARE"], errors="coerce").mean(), 1) if total_opps > 0 else 0
    median_gain  = round(pd.to_numeric(fge_df["GAIN %/SHARE"], errors="coerce").median(), 1) if total_opps > 0 else 0
    peak_gain    = round(pd.to_numeric(fge_df["GAIN %/SHARE"], errors="coerce").max(), 1) if total_opps > 0 else 0
    aplus_opps   = int((fge_df["A+ OPP?"].astype(str).str.upper() == "Y").sum()) if total_opps > 0 else 0
    traded       = int((fge_df["DID I TRADE STOCK?"].astype(str).str.upper() == "Y").sum()) if total_opps > 0 else 0
    traded_rate  = round(traded / total_opps * 100, 1) if total_opps > 0 else 0

    # Serialize table data
    table_rows = []
    if not fge_df.empty:
        for _, row in fge_df.iterrows():
            table_rows.append({
                "date":   str(row.get("DATE", ""))[:10],
                "stock":  str(row.get("STOCK", "")),
                "tod":    str(row.get("TOD", "")),
                "legs":   str(row.get("# LEGS", "")),
                "aplus":  str(row.get("A+ OPP?", "")),
                "state":  str(row.get("TYPE OF STATE", "")),
                "pos":    str(row.get("POSITION", "")),
                "entry":  str(row.get("ENTRY PRICE", "")),
                "exit":   str(row.get("EXIT PRICE", "")),
                "gain_p": str(row.get("GAIN %/SHARE", "")),
                "gain_d": str(row.get("GAIN $/SHARE", "")),
                "ma20":   str(row.get("20 MA", "")),
                "ma200":  str(row.get("200 MA", "")),
                "runs":   str(row.get("# OF RUNS ON CAL DAY", "")),
                "news_t": str(row.get("NEWS TYPE", "")),
            })

    table_json = json.dumps(table_rows)
    updated    = datetime.now().strftime("%B %d, %Y at %I:%M %p ET")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FGE Top Gainer Opps</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0d1117;color:#e6edf3;font-family:Consolas,monospace;font-size:13px}}
  .header{{background:#161b22;padding:20px 24px;border-bottom:1px solid #21262d;display:flex;align-items:center;justify-content:space-between}}
  .header h1{{color:#58a6ff;font-size:18px;font-weight:700}}
  .updated{{color:#8b949e;font-size:11px}}
  .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;padding:20px 24px}}
  .stat{{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:14px;text-align:center}}
  .stat-val{{font-size:22px;font-weight:700;color:#58a6ff}}
  .stat-lbl{{font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;letter-spacing:.5px}}
  .filters{{padding:0 24px 16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
  .filters select,.filters input{{background:#161b22;border:1px solid #30363d;color:#e6edf3;padding:6px 10px;border-radius:4px;font-size:12px}}
  .filters label{{color:#8b949e;font-size:11px}}
  .download-btn{{background:#238636;color:#fff;border:none;padding:7px 14px;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600}}
  .download-btn:hover{{background:#2ea043}}
  table{{width:100%;border-collapse:collapse;margin:0 24px;width:calc(100% - 48px)}}
  th{{background:#161b22;color:#e3b341;padding:10px 8px;text-align:center;font-size:11px;border:1px solid #21262d;cursor:pointer;user-select:none;white-space:nowrap}}
  th:hover{{background:#1c2128}}
  td{{padding:8px;text-align:center;border:1px solid #21262d;white-space:nowrap}}
  tr:hover td{{background:#1c2128}}
  .pat-fge{{color:#58a6ff;font-weight:700}}
  .pat-blast{{color:#3fb950;font-weight:700}}
  .aplus{{color:#e3b341;font-weight:700}}
  .state-narrow{{color:#3fb950}}
  .state-medium{{color:#e3b341}}
  .state-wide{{color:#f85149}}
  .pos-1{{color:#3fb950}}
  .pos-2{{color:#e3b341}}
  .pos-3{{color:#f85149}}
  .traded-y{{color:#3fb950}}
  .gain-high{{color:#f85149}}
  .gain-mid{{color:#e3b341}}
  .gain-low{{color:#3fb950}}
  .tod-pm{{color:#d2a8ff}}
  .tod-ah{{color:#ffa657}}
  .tod-id{{color:#3fb950}}
  .no-data{{text-align:center;padding:60px;color:#8b949e}}
  footer{{padding:20px 24px;color:#8b949e;font-size:11px;text-align:center}}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>⚡ FGE Top Gainer Opps</h1>
    <div class="updated">Auto-updated · Last run: {updated}</div>
  </div>
  <button class="download-btn" onclick="downloadExcel()">⬇ Download Backup</button>
</div>

<div class="stats">
  <div class="stat"><div class="stat-val">{total_opps}</div><div class="stat-lbl">Total Opps</div></div>
  <div class="stat"><div class="stat-val" style="color:#3fb950">{avg_gain}%</div><div class="stat-lbl">Avg Gain</div></div>
  <div class="stat"><div class="stat-val" style="color:#79c0ff">{median_gain}%</div><div class="stat-lbl">Median Gain</div></div>
  <div class="stat"><div class="stat-val" style="color:#f85149">{peak_gain}%</div><div class="stat-lbl">Peak Gain</div></div>
  <div class="stat"><div class="stat-val" style="color:#e3b341">{aplus_opps}</div><div class="stat-lbl">A+ Opps</div></div>
  <div class="stat"><div class="stat-val" style="color:#ffa657">{traded_rate}%</div><div class="stat-lbl">Traded Rate</div></div>
</div>

<div class="filters">
  <label>Month:</label>
  <select id="fMonth" onchange="applyFilters()"><option value="">All</option></select>
  <label>TOD:</label>
  <select id="fTod" onchange="applyFilters()">
    <option value="">All</option><option>PM</option><option>ID</option><option>AH</option>
  </select>
  <label>State:</label>
  <select id="fState" onchange="applyFilters()">
    <option value="">All</option><option>NARROW</option><option>MEDIUM</option><option>WIDE</option>
  </select>
  <label>A+:</label>
  <select id="fAplus" onchange="applyFilters()">
    <option value="">All</option><option value="Y">A+ Only</option>
  </select>
  <label>Min Gain%:</label>
  <input type="number" id="fMinGain" placeholder="0" style="width:70px" oninput="applyFilters()">
  <label>Ticker:</label>
  <input type="text" id="fTicker" placeholder="AAPL" style="width:80px" oninput="applyFilters()">
</div>

<table id="mainTable">
  <thead>
    <tr>
      <th onclick="sortTable(0)">Date ↕</th>
      <th onclick="sortTable(1)">Ticker ↕</th>
      <th onclick="sortTable(2)">TOD ↕</th>
      <th onclick="sortTable(3)">Legs ↕</th>
      <th onclick="sortTable(4)">A+ ↕</th>
      <th onclick="sortTable(5)">State ↕</th>
      <th onclick="sortTable(6)">Pos ↕</th>
      <th onclick="sortTable(7)">Entry ↕</th>
      <th onclick="sortTable(8)">Exit ↕</th>
      <th onclick="sortTable(9)">Gain% ↕</th>
      <th onclick="sortTable(10)">Gain$ ↕</th>
      <th onclick="sortTable(11)">MA20 ↕</th>
      <th onclick="sortTable(12)">MA200 ↕</th>
      <th onclick="sortTable(13)">Runs ↕</th>
      <th onclick="sortTable(14)">News Type ↕</th>
    </tr>
  </thead>
  <tbody id="tableBody"></tbody>
</table>
<div id="noData" class="no-data" style="display:none">No data matches current filters</div>

<footer>FGE Top Gainer Opps · Auto-updated daily at 8pm ET · {updated}</footer>

<script>
const RAW = {table_json};
let sortCol=-1, sortDir=1;

function gainClass(g){{
  const v=parseFloat(g)||0;
  return v>=40?'gain-high':v>=20?'gain-mid':'gain-low';
}}
function todClass(t){{return t==='PM'?'tod-pm':t==='AH'?'tod-ah':'tod-id'}}
function stateClass(s){{return s==='NARROW'?'state-narrow':s==='MEDIUM'?'state-medium':'state-wide'}}
function posClass(p){{return p=='1'?'pos-1':p=='2'?'pos-2':'pos-3'}}

function renderTable(data){{
  const tbody=document.getElementById('tableBody');
  const noData=document.getElementById('noData');
  if(!data.length){{tbody.innerHTML='';noData.style.display='block';return}}
  noData.style.display='none';
  tbody.innerHTML=data.map(r=>`
    <tr>
      <td>${{r.date}}</td>
      <td style="font-weight:700;color:#e6edf3">${{r.stock}}</td>
      <td class="${{todClass(r.tod)}}">${{r.tod}}</td>
      <td>${{r.legs}}</td>
      <td class="${{r.aplus==='Y'?'aplus':''}}">${{r.aplus}}</td>
      <td class="${{stateClass(r.state)}}">${{r.state}}</td>
      <td class="${{posClass(r.pos)}}">${{r.pos}}</td>
      <td>${{r.entry}}</td>
      <td>${{r.exit}}</td>
      <td class="${{gainClass(r.gain_p)}}" style="font-weight:700">${{r.gain_p}}%</td>
      <td>${{r.gain_d}}</td>
      <td style="color:#e3b341">${{r.ma20}}</td>
      <td style="color:#e3b341">${{r.ma200}}</td>
      <td>${{r.runs}}</td>
      <td style="color:#8b949e;font-size:11px">${{r.news_t}}</td>
    </tr>`).join('');
}}

function applyFilters(){{
  const month=document.getElementById('fMonth').value;
  const tod=document.getElementById('fTod').value;
  const state=document.getElementById('fState').value;
  const aplus=document.getElementById('fAplus').value;
  const minGain=parseFloat(document.getElementById('fMinGain').value)||0;
  const ticker=document.getElementById('fTicker').value.toUpperCase().trim();

  let data=RAW.filter(r=>{{
    if(month && !r.date.startsWith(month)) return false;
    if(tod && r.tod!==tod) return false;
    if(state && r.state!==state) return false;
    if(aplus && r.aplus!==aplus) return false;
    if(minGain && (parseFloat(r.gain_p)||0)<minGain) return false;
    if(ticker && !r.stock.includes(ticker)) return false;
    return true;
  }});
  renderTable(data);
}}

function sortTable(col){{
  if(sortCol===col) sortDir*=-1; else{{sortCol=col;sortDir=1;}}
  const keys=['date','stock','tod','legs','aplus','state','pos','entry','exit','gain_p','gain_d','ma20','ma200','runs','news_t'];
  RAW.sort((a,b)=>{{
    const av=a[keys[col]]||'', bv=b[keys[col]]||'';
    const an=parseFloat(av), bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn)) return(an-bn)*sortDir;
    return av.localeCompare(bv)*sortDir;
  }});
  applyFilters();
}}

// Populate month filter
const months=[...new Set(RAW.map(r=>r.date.slice(0,7)))].sort().reverse();
const sel=document.getElementById('fMonth');
months.forEach(m=>{{const o=document.createElement('option');o.value=m;o.text=m;sel.appendChild(o);}});

renderTable(RAW);

function downloadExcel(){{
  window.location.href='trading_data_{date.today().isoformat()}.xlsx';
}}
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  FGE dashboard: {total_opps} FGE records")
"""
Generates the FGE Top Gainers Opps dashboard HTML.
Reads from TOP Gainers Data (FGE entries only, Sheet 1).
"""

import pandas as pd
import numpy as np
from datetime import datetime, date
import json


def generate_fge_dashboard(df: pd.DataFrame, output_path: str):
    """Generate FGE_Top_Gainer_Opps style dashboard from TOP Gainers Data."""
    print(f"  Generating FGE dashboard → {output_path}")

    # Filter FGE only, Sheet 1 data
    if df.empty:
        fge_df = pd.DataFrame()
    else:
        fge_mask = df["ENTRY TYPE"].astype(str).str.upper().str.contains("FGE", na=False)
        fge_df = df[fge_mask].copy()

    # Prepare stats
    total_opps   = len(fge_df)
    avg_gain     = round(pd.to_numeric(fge_df["GAIN %/SHARE"], errors="coerce").mean(), 1) if total_opps > 0 else 0
    median_gain  = round(pd.to_numeric(fge_df["GAIN %/SHARE"], errors="coerce").median(), 1) if total_opps > 0 else 0
    peak_gain    = round(pd.to_numeric(fge_df["GAIN %/SHARE"], errors="coerce").max(), 1) if total_opps > 0 else 0
    aplus_opps   = int((fge_df["A+ OPP?"].astype(str).str.upper() == "Y").sum()) if total_opps > 0 else 0
    traded       = int((fge_df["DID I TRADE STOCK?"].astype(str).str.upper() == "Y").sum()) if total_opps > 0 else 0
    traded_rate  = round(traded / total_opps * 100, 1) if total_opps > 0 else 0

    # Serialize table data
    table_rows = []
    if not fge_df.empty:
        for _, row in fge_df.iterrows():
            table_rows.append({
                "date":   str(row.get("DATE", ""))[:10],
                "stock":  str(row.get("STOCK", "")),
                "tod":    str(row.get("TOD", "")),
                "legs":   str(row.get("# LEGS", "")),
                "aplus":  str(row.get("A+ OPP?", "")),
                "state":  str(row.get("TYPE OF STATE", "")),
                "pos":    str(row.get("POSITION", "")),
                "entry":  str(row.get("ENTRY PRICE", "")),
                "exit":   str(row.get("EXIT PRICE", "")),
                "gain_p": str(row.get("GAIN %/SHARE", "")),
                "gain_d": str(row.get("GAIN $/SHARE", "")),
                "ma20":   str(row.get("20 MA", "")),
                "ma200":  str(row.get("200 MA", "")),
                "runs":   str(row.get("# OF RUNS ON CAL DAY", "")),
                "traded": str(row.get("DID I TRADE STOCK?", "")),
                "news_t": str(row.get("NEWS TYPE", "")),
            })

    table_json = json.dumps(table_rows)
    updated    = datetime.now().strftime("%B %d, %Y at %I:%M %p ET")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FGE Top Gainer Opps</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0d1117;color:#e6edf3;font-family:Consolas,monospace;font-size:13px}}
  .header{{background:#161b22;padding:20px 24px;border-bottom:1px solid #21262d;display:flex;align-items:center;justify-content:space-between}}
  .header h1{{color:#58a6ff;font-size:18px;font-weight:700}}
  .updated{{color:#8b949e;font-size:11px}}
  .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;padding:20px 24px}}
  .stat{{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:14px;text-align:center}}
  .stat-val{{font-size:22px;font-weight:700;color:#58a6ff}}
  .stat-lbl{{font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;letter-spacing:.5px}}
  .filters{{padding:0 24px 16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
  .filters select,.filters input{{background:#161b22;border:1px solid #30363d;color:#e6edf3;padding:6px 10px;border-radius:4px;font-size:12px}}
  .filters label{{color:#8b949e;font-size:11px}}
  .download-btn{{background:#238636;color:#fff;border:none;padding:7px 14px;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600}}
  .download-btn:hover{{background:#2ea043}}
  table{{width:100%;border-collapse:collapse;margin:0 24px;width:calc(100% - 48px)}}
  th{{background:#161b22;color:#e3b341;padding:10px 8px;text-align:center;font-size:11px;border:1px solid #21262d;cursor:pointer;user-select:none;white-space:nowrap}}
  th:hover{{background:#1c2128}}
  td{{padding:8px;text-align:center;border:1px solid #21262d;white-space:nowrap}}
  tr:hover td{{background:#1c2128}}
  .pat-fge{{color:#58a6ff;font-weight:700}}
  .pat-blast{{color:#3fb950;font-weight:700}}
  .aplus{{color:#e3b341;font-weight:700}}
  .state-narrow{{color:#3fb950}}
  .state-medium{{color:#e3b341}}
  .state-wide{{color:#f85149}}
  .pos-1{{color:#3fb950}}
  .pos-2{{color:#e3b341}}
  .pos-3{{color:#f85149}}
  .traded-y{{color:#3fb950}}
  .gain-high{{color:#f85149}}
  .gain-mid{{color:#e3b341}}
  .gain-low{{color:#3fb950}}
  .tod-pm{{color:#d2a8ff}}
  .tod-ah{{color:#ffa657}}
  .tod-id{{color:#3fb950}}
  .no-data{{text-align:center;padding:60px;color:#8b949e}}
  footer{{padding:20px 24px;color:#8b949e;font-size:11px;text-align:center}}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>⚡ FGE Top Gainer Opps</h1>
    <div class="updated">Auto-updated · Last run: {updated}</div>
  </div>
  <button class="download-btn" onclick="downloadExcel()">⬇ Download Backup</button>
</div>

<div class="stats">
  <div class="stat"><div class="stat-val">{total_opps}</div><div class="stat-lbl">Total Opps</div></div>
  <div class="stat"><div class="stat-val" style="color:#3fb950">{avg_gain}%</div><div class="stat-lbl">Avg Gain</div></div>
  <div class="stat"><div class="stat-val" style="color:#79c0ff">{median_gain}%</div><div class="stat-lbl">Median Gain</div></div>
  <div class="stat"><div class="stat-val" style="color:#f85149">{peak_gain}%</div><div class="stat-lbl">Peak Gain</div></div>
  <div class="stat"><div class="stat-val" style="color:#e3b341">{aplus_opps}</div><div class="stat-lbl">A+ Opps</div></div>
  <div class="stat"><div class="stat-val" style="color:#ffa657">{traded_rate}%</div><div class="stat-lbl">Traded Rate</div></div>
</div>

<div class="filters">
  <label>Month:</label>
  <select id="fMonth" onchange="applyFilters()"><option value="">All</option></select>
  <label>TOD:</label>
  <select id="fTod" onchange="applyFilters()">
    <option value="">All</option><option>PM</option><option>ID</option><option>AH</option>
  </select>
  <label>State:</label>
  <select id="fState" onchange="applyFilters()">
    <option value="">All</option><option>NARROW</option><option>MEDIUM</option><option>WIDE</option>
  </select>
  <label>A+:</label>
  <select id="fAplus" onchange="applyFilters()">
    <option value="">All</option><option value="Y">A+ Only</option>
  </select>
  <label>Min Gain%:</label>
  <input type="number" id="fMinGain" placeholder="0" style="width:70px" oninput="applyFilters()">
  <label>Ticker:</label>
  <input type="text" id="fTicker" placeholder="AAPL" style="width:80px" oninput="applyFilters()">
</div>

<table id="mainTable">
  <thead>
    <tr>
      <th onclick="sortTable(0)">Date ↕</th>
      <th onclick="sortTable(1)">Ticker ↕</th>
      <th onclick="sortTable(2)">TOD ↕</th>
      <th onclick="sortTable(3)">Legs ↕</th>
      <th onclick="sortTable(4)">A+ ↕</th>
      <th onclick="sortTable(5)">State ↕</th>
      <th onclick="sortTable(6)">Pos ↕</th>
      <th onclick="sortTable(7)">Entry ↕</th>
      <th onclick="sortTable(8)">Exit ↕</th>
      <th onclick="sortTable(9)">Gain% ↕</th>
      <th onclick="sortTable(10)">Gain$ ↕</th>
      <th onclick="sortTable(11)">MA20 ↕</th>
      <th onclick="sortTable(12)">MA200 ↕</th>
      <th onclick="sortTable(13)">Runs ↕</th>
      <th onclick="sortTable(14)">Traded ↕</th>
      <th onclick="sortTable(15)">News Type ↕</th>
    </tr>
  </thead>
  <tbody id="tableBody"></tbody>
</table>
<div id="noData" class="no-data" style="display:none">No data matches current filters</div>

<footer>FGE Top Gainer Opps · Auto-updated daily at 8pm ET · {updated}</footer>

<script>
const RAW = {table_json};
let sortCol=-1, sortDir=1;

function gainClass(g){{
  const v=parseFloat(g)||0;
  return v>=40?'gain-high':v>=20?'gain-mid':'gain-low';
}}
function todClass(t){{return t==='PM'?'tod-pm':t==='AH'?'tod-ah':'tod-id'}}
function stateClass(s){{return s==='NARROW'?'state-narrow':s==='MEDIUM'?'state-medium':'state-wide'}}
function posClass(p){{return p=='1'?'pos-1':p=='2'?'pos-2':'pos-3'}}

function renderTable(data){{
  const tbody=document.getElementById('tableBody');
  const noData=document.getElementById('noData');
  if(!data.length){{tbody.innerHTML='';noData.style.display='block';return}}
  noData.style.display='none';
  tbody.innerHTML=data.map(r=>`
    <tr>
      <td>${{r.date}}</td>
      <td style="font-weight:700;color:#e6edf3">${{r.stock}}</td>
      <td class="${{todClass(r.tod)}}">${{r.tod}}</td>
      <td>${{r.legs}}</td>
      <td class="${{r.aplus==='Y'?'aplus':''}}">${{r.aplus}}</td>
      <td class="${{stateClass(r.state)}}">${{r.state}}</td>
      <td class="${{posClass(r.pos)}}">${{r.pos}}</td>
      <td>${{r.entry}}</td>
      <td>${{r.exit}}</td>
      <td class="${{gainClass(r.gain_p)}}" style="font-weight:700">${{r.gain_p}}%</td>
      <td>${{r.gain_d}}</td>
      <td style="color:#e3b341">${{r.ma20}}</td>
      <td style="color:#e3b341">${{r.ma200}}</td>
      <td>${{r.runs}}</td>
      <td class="${{r.traded==='Y'?'traded-y':''}}">${{r.traded}}</td>
      <td style="color:#8b949e;font-size:11px">${{r.news_t}}</td>
    </tr>`).join('');
}}

function applyFilters(){{
  const month=document.getElementById('fMonth').value;
  const tod=document.getElementById('fTod').value;
  const state=document.getElementById('fState').value;
  const aplus=document.getElementById('fAplus').value;
  const minGain=parseFloat(document.getElementById('fMinGain').value)||0;
  const ticker=document.getElementById('fTicker').value.toUpperCase().trim();

  let data=RAW.filter(r=>{{
    if(month && !r.date.startsWith(month)) return false;
    if(tod && r.tod!==tod) return false;
    if(state && r.state!==state) return false;
    if(aplus && r.aplus!==aplus) return false;
    if(minGain && (parseFloat(r.gain_p)||0)<minGain) return false;
    if(ticker && !r.stock.includes(ticker)) return false;
    return true;
  }});
  renderTable(data);
}}

function sortTable(col){{
  if(sortCol===col) sortDir*=-1; else{{sortCol=col;sortDir=1;}}
  const keys=['date','stock','tod','legs','aplus','state','pos','entry','exit','gain_p','gain_d','ma20','ma200','runs','traded','news_t'];
  RAW.sort((a,b)=>{{
    const av=a[keys[col]]||'', bv=b[keys[col]]||'';
    const an=parseFloat(av), bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn)) return(an-bn)*sortDir;
    return av.localeCompare(bv)*sortDir;
  }});
  applyFilters();
}}

// Populate month filter
const months=[...new Set(RAW.map(r=>r.date.slice(0,7)))].sort().reverse();
const sel=document.getElementById('fMonth');
months.forEach(m=>{{const o=document.createElement('option');o.value=m;o.text=m;sel.appendChild(o);}});

renderTable(RAW);

function downloadExcel(){{
  window.location.href='trading_data_{date.today().isoformat()}.xlsx';
}}
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  FGE dashboard: {total_opps} FGE records")
