"""
Generates the MDR Watchlist dashboard HTML.
Shows scored MDR stocks with tier badges and today's runs.
"""

import pandas as pd
import json
from datetime import datetime, date


def generate_mdr_dashboard(mdr_df: pd.DataFrame,
                            today_runs: list[dict],
                            output_path: str):
    """Generate MDR watchlist dashboard."""
    print(f"  Generating MDR dashboard → {output_path}")

    # Build stock cards data
    stocks = []
    if not mdr_df.empty:
        for _, row in mdr_df.iterrows():
            ticker = str(row.get("STOCK", "")).strip()
            if not ticker:
                continue
            score  = int(float(str(row.get("MDR SCORE", 0) or 0)))
            tier   = str(row.get("TIER", "Watch"))
            stocks.append({
                "ticker":     ticker,
                "score":      score,
                "tier":       tier,
                "days":       str(row.get("DAYS ON LIST", "")),
                "state":      str(row.get("STATE", "")),
                "position":   str(row.get("POSITION", "")),
                "entry":      str(row.get("ENTRY PRICE", "")),
                "exit":       str(row.get("EXIT PRICE", "")),
                "legs":       str(row.get("# LEGS", "")),
                "ma20":       str(row.get("20 MA", "")),
                "ma200":      str(row.get("200 MA", "")),
                "list_date":  str(row.get("MDR LIST DATE", ""))[:10],
                "last_run":   str(row.get("LAST RUN DATE", ""))[:10],
                "news_type":  str(row.get("NEWS TYPE", "")),
                "did_run":    str(row.get("DID IT RUN?", "")),
            })

    # Sort: Strong first, then Watch, then Weakening; within each by score desc
    tier_order = {"Strong Setup": 0, "Watch": 1, "Weakening": 2}
    stocks.sort(key=lambda x: (tier_order.get(x["tier"], 3), -x["score"]))

    # Today's runs summary
    runs_today = []
    for r in today_runs:
        runs_today.append({
            "ticker":  r.get("ticker", ""),
            "pattern": r.get("pattern", ""),
            "gain_p":  r.get("pct_gain", ""),
            "legs":    r.get("legs", ""),
            "aplus":   r.get("aplus", ""),
            "tod":     r.get("tod", ""),
            "entry":   r.get("price_entry", ""),
            "exit":    r.get("price_exit", ""),
            "state":   r.get("state", ""),
        })

    strong = [s for s in stocks if s["tier"] == "Strong Setup"]
    watch  = [s for s in stocks if s["tier"] == "Watch"]
    weak   = [s for s in stocks if s["tier"] == "Weakening"]

    stocks_json   = json.dumps(stocks)
    runs_json     = json.dumps(runs_today)
    updated       = datetime.now().strftime("%B %d, %Y at %I:%M %p ET")
    today_str     = date.today().isoformat()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MDR Watchlist</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0d1117;color:#e6edf3;font-family:Consolas,monospace;font-size:13px}}
  .header{{background:#161b22;padding:18px 24px;border-bottom:1px solid #21262d;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}}
  .header h1{{color:#58a6ff;font-size:18px;font-weight:700}}
  .updated{{color:#8b949e;font-size:11px;margin-top:2px}}
  .nav{{display:flex;gap:8px}}
  .nav a{{color:#8b949e;text-decoration:none;padding:6px 12px;border:1px solid #30363d;border-radius:4px;font-size:12px}}
  .nav a:hover{{color:#e6edf3;border-color:#58a6ff}}
  .download-btn{{background:#238636;color:#fff;border:none;padding:7px 14px;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600}}
  .summary-bar{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;padding:16px 24px;background:#0d1117}}
  .sum-card{{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:12px;text-align:center}}
  .sum-val{{font-size:20px;font-weight:700}}
  .sum-lbl{{font-size:10px;color:#8b949e;margin-top:3px;text-transform:uppercase}}
  .section{{padding:0 24px 24px}}
  .section-title{{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:1px;padding:16px 0 10px;border-bottom:1px solid #21262d;margin-bottom:12px}}
  .section-title span{{font-weight:700;font-size:13px}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}}
  .card{{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:14px;position:relative}}
  .card-strong{{border-color:#3fb950;border-left:3px solid #3fb950}}
  .card-watch{{border-color:#e3b341;border-left:3px solid #e3b341}}
  .card-weak{{border-color:#8b949e;border-left:3px solid #8b949e;opacity:.8}}
  .card-top{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px}}
  .ticker{{font-size:18px;font-weight:700;color:#e6edf3}}
  .score-badge{{font-size:20px;font-weight:700;color:#58a6ff}}
  .tier-badge{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:3px;margin-top:3px;display:inline-block}}
  .tier-strong{{background:#0a2010;color:#3fb950;border:1px solid #3fb950}}
  .tier-watch{{background:#1e1600;color:#e3b341;border:1px solid #e3b341}}
  .tier-weak{{background:#1a1a1a;color:#8b949e;border:1px solid #8b949e}}
  .card-grid{{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;font-size:11px}}
  .card-lbl{{color:#8b949e}}
  .card-val{{color:#e6edf3}}
  .news-pill{{margin-top:8px;font-size:10px;padding:2px 6px;border-radius:3px;display:inline-block}}
  .news-pos{{background:#0a2010;color:#3fb950}}
  .news-neg{{background:#2d1010;color:#f85149}}
  .news-neu{{background:#1a1a1a;color:#8b949e}}
  .runs-table{{width:100%;border-collapse:collapse}}
  .runs-table th{{background:#161b22;color:#e3b341;padding:8px;font-size:11px;border:1px solid #21262d;text-align:center}}
  .runs-table td{{padding:7px 8px;border:1px solid #21262d;text-align:center;font-size:12px}}
  .runs-table tr:hover td{{background:#1c2128}}
  .pat-fge{{color:#58a6ff;font-weight:700}}
  .pat-blast{{color:#3fb950;font-weight:700}}
  .aplus{{color:#e3b341;font-weight:700}}
  .state-n{{color:#3fb950}}
  .state-m{{color:#e3b341}}
  .state-w{{color:#f85149}}
  .empty{{text-align:center;color:#8b949e;padding:40px;font-size:12px}}
  footer{{padding:20px 24px;color:#8b949e;font-size:11px;text-align:center;border-top:1px solid #21262d}}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>📈 MDR Watchlist</h1>
    <div class="updated">Auto-updated · {updated}</div>
  </div>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <div class="nav">
      <a href="fge.html">⚡ FGE Dashboard</a>
    </div>
    <button class="download-btn" onclick="window.location.href='trading_data_{today_str}.xlsx'">⬇ Download Backup</button>
  </div>
</div>

<div class="summary-bar">
  <div class="sum-card"><div class="sum-val" style="color:#3fb950">{len(strong)}</div><div class="sum-lbl">Strong Setup</div></div>
  <div class="sum-card"><div class="sum-val" style="color:#e3b341">{len(watch)}</div><div class="sum-lbl">Watch</div></div>
  <div class="sum-card"><div class="sum-val" style="color:#8b949e">{len(weak)}</div><div class="sum-lbl">Weakening</div></div>
  <div class="sum-card"><div class="sum-val" style="color:#ffa657">{len(runs_today)}</div><div class="sum-lbl">Runs Today</div></div>
  <div class="sum-card"><div class="sum-val" style="color:#58a6ff">{len(stocks)}</div><div class="sum-lbl">Total Watchlist</div></div>
</div>

<!-- Today's Runs -->
<div class="section">
  <div class="section-title">📊 <span>Today's Runs</span> — {today_str}</div>
  {'<table class="runs-table"><thead><tr><th>Ticker</th><th>Pattern</th><th>Gain%</th><th>Legs</th><th>A+</th><th>TOD</th><th>Entry</th><th>Exit</th><th>State</th></tr></thead><tbody id="runsBody"></tbody></table>' if runs_today else '<div class="empty">No qualifying runs detected today</div>'}
</div>

<!-- Strong Setup -->
<div class="section">
  <div class="section-title">🟢 <span>Strong Setup</span> ({len(strong)} stocks)</div>
  <div class="cards" id="strongCards"></div>
  {'<div class="empty">No Strong Setup stocks</div>' if not strong else ''}
</div>

<!-- Watch -->
<div class="section">
  <div class="section-title">🟡 <span>Watch</span> ({len(watch)} stocks)</div>
  <div class="cards" id="watchCards"></div>
  {'<div class="empty">No Watch stocks</div>' if not watch else ''}
</div>

<!-- Weakening -->
<div class="section">
  <div class="section-title">⚪ <span>Weakening</span> ({len(weak)} stocks)</div>
  <div class="cards" id="weakCards"></div>
  {'<div class="empty">No Weakening stocks</div>' if not weak else ''}
</div>

<footer>MDR Watchlist · Auto-updated daily at 8pm ET · {updated}</footer>

<script>
const STOCKS = {stocks_json};
const RUNS   = {runs_json};

function newsClass(t){{
  const pos=['FDA/CLINICAL','EARNINGS','CONTRACT/DEAL','M&A'];
  const neg=['OFFERING/DILUTION','REGULATORY/LEGAL'];
  if(pos.includes(t)) return 'news-pos';
  if(neg.includes(t)) return 'news-neg';
  return t?'news-neu':'';
}}
function stateClass(s){{return s==='NARROW'?'state-n':s==='MEDIUM'?'state-m':'state-w'}}
function tierClass(t){{return t==='Strong Setup'?'card-strong':t==='Watch'?'card-watch':'card-weak'}}
function tierBadgeClass(t){{return t==='Strong Setup'?'tier-strong':t==='Watch'?'tier-watch':'tier-weak'}}

function renderCard(s){{
  return `<div class="card ${{tierClass(s.tier)}}">
    <div class="card-top">
      <div>
        <div class="ticker">${{s.ticker}}</div>
        <div class="tier-badge ${{tierBadgeClass(s.tier)}}">${{s.tier}}</div>
      </div>
      <div style="text-align:right">
        <div class="score-badge">${{s.score}}</div>
        <div style="font-size:10px;color:#8b949e">MDR Score</div>
      </div>
    </div>
    <div class="card-grid">
      <span class="card-lbl">Days on list</span><span class="card-val">${{s.days}}</span>
      <span class="card-lbl">State</span><span class="card-val ${{stateClass(s.state)}}">${{s.state}}</span>
      <span class="card-lbl">Position</span><span class="card-val">${{s.position}}</span>
      <span class="card-lbl">Legs</span><span class="card-val">${{s.legs}}</span>
      <span class="card-lbl">Entry</span><span class="card-val">${{s.entry}}</span>
      <span class="card-lbl">Exit</span><span class="card-val">${{s.exit}}</span>
      <span class="card-lbl">MA20</span><span class="card-val" style="color:#e3b341">${{s.ma20}}</span>
      <span class="card-lbl">MA200</span><span class="card-val" style="color:#e3b341">${{s.ma200}}</span>
      <span class="card-lbl">List date</span><span class="card-val">${{s.list_date}}</span>
      <span class="card-lbl">Last run</span><span class="card-val">${{s.last_run}}</span>
    </div>
    ${{s.news_type?`<div class="news-pill ${{newsClass(s.news_type)}}">${{s.news_type}}</div>`:''}}
  </div>`;
}}

document.getElementById('strongCards').innerHTML = STOCKS.filter(s=>s.tier==='Strong Setup').map(renderCard).join('');
document.getElementById('watchCards').innerHTML  = STOCKS.filter(s=>s.tier==='Watch').map(renderCard).join('');
document.getElementById('weakCards').innerHTML   = STOCKS.filter(s=>s.tier==='Weakening').map(renderCard).join('');

const runsBody = document.getElementById('runsBody');
if(runsBody){{
  runsBody.innerHTML = RUNS.map(r=>`<tr>
    <td style="font-weight:700">${{r.ticker}}</td>
    <td class="${{r.pattern==='FGE'?'pat-fge':'pat-blast'}}">${{r.pattern}}</td>
    <td style="font-weight:700;color:${{parseFloat(r.gain_p)>=40?'#f85149':parseFloat(r.gain_p)>=20?'#e3b341':'#3fb950'}}">${{r.gain_p}}%</td>
    <td>${{r.legs}}</td>
    <td class="${{r.aplus==='Y'?'aplus':''}}">${{r.aplus}}</td>
    <td style="color:${{r.tod==='PM'?'#d2a8ff':r.tod==='AH'?'#ffa657':'#3fb950'}}">${{r.tod}}</td>
    <td>${{r.entry}}</td>
    <td>${{r.exit}}</td>
    <td class="${{stateClass(r.state)}}">${{r.state}}</td>
  </tr>`).join('');
}}
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  MDR dashboard: {len(stocks)} watchlist stocks, {len(runs_today)} runs today")
