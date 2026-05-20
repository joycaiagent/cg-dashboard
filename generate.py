#!/usr/bin/env python3
"""
Generate static CG Landscape ops dashboard HTML.
Run daily via cron to refresh the static page.
"""
import json, os, sys, datetime, urllib.parse, subprocess
from pathlib import Path

DASHBOARD_DIR = Path(__file__).parent
TOKEN_PATH    = Path.home() / ".openclaw/workspace/scripts/aspire-token.json"
OUTLOOK_TOKEN = Path.home() / ".openclaw/workspace/scripts/outlook-token.json"

JOSE_CALENDAR_ID = 'AAMkADIzN2NjZGY2LTNkOGItNDk3Yy1hZWQ4LTgwNWU1NTdmZTJiNABGAAAAAABJrZ9QYFESQKtRz5yUKko2BwAFOLnegfVcRpFAwXSqdmvNAAAAAAEGAAAFOLnegfVcRpFAwXSqdmvNAAAAAE3GAAA='

# ── helpers ──────────────────────────────────────────────────────────────────

def get_token():
    try:
        with open(TOKEN_PATH) as f:
            t = json.load(f)
        return t.get('access_token') or t.get('Token')
    except:
        return None

def get_outlook_token():
    try:
        with open(OUTLOOK_TOKEN) as f:
            t = json.load(f)
        return t.get('access_token')
    except:
        return None

def aspire_api(url):
    token = get_token()
    if not token:
        return []
    r = subprocess.run(
        ['curl', '-s', url, '-H', f'Authorization: Bearer {token}',
         '-H', 'Accept: application/json'],
        capture_output=True, text=True, timeout=30
    )
    try:
        d = json.loads(r.stdout)
        if isinstance(d, list):
            return d
        return d.get('items') or d.get('value') or []
    except:
        return []

def outlook_api(url):
    token = get_outlook_token()
    if not token:
        return []
    r = subprocess.run(
        ['curl', '-s', url, '-H', f'Authorization: Bearer {token}',
         '-H', 'Prefer: outlook.timezone="Pacific Standard Time"'],
        capture_output=True, text=True, timeout=30
    )
    try:
        return json.loads(r.stdout).get('value', [])
    except:
        return []

# ── data fetchers ─────────────────────────────────────────────────────────────

def get_calendar():
    """Next 3 days of Jose's calendar events."""
    try:
        start = datetime.datetime.utcnow()
        end   = start + datetime.timedelta(days=3)
        params = {
            'startDateTime': start.isoformat() + 'Z',
            'endDateTime':   end.isoformat()   + 'Z',
            '$top': '25', '$orderby': 'start/dateTime',
            '$select': 'subject,organizer,start,end,location,isAllDay'
        }
        url = (f'https://graph.microsoft.com/v1.0/me/calendars/{JOSE_CALENDAR_ID}/calendarView'
               + '?' + urllib.parse.urlencode(params))
        return outlook_api(url)[:8]
    except Exception as e:
        print(f'Calendar error: {e}')
    return []

def get_ops_health():
    """This week's work ticket stats by branch."""
    today   = datetime.date.today()
    monday  = today - datetime.timedelta(days=today.weekday())
    sunday  = monday + datetime.timedelta(days=6)  # full week Mon→Sun
    start, end = monday.isoformat(), sunday.isoformat()
    flt = f"ScheduledStartDate ge {start} and ScheduledStartDate le {end}"
    url = f"https://cloud-api.youraspire.com/WorkTickets?$filter={urllib.parse.quote(flt)}&$top=1000&$skip=0"
    tickets = aspire_api(url)
    sched   = [w for w in tickets if w.get('WorkTicketStatusName') == 'Scheduled']
    done    = [w for w in tickets if w.get('WorkTicketStatusName') == 'Complete']
    canc    = [w for w in tickets if w.get('WorkTicketStatusName') == 'Canceled']
    open_wt = [w for w in tickets if w.get('WorkTicketStatusName') == 'Open']
    total   = len(tickets)
    rate    = round(len(done) / total * 100) if total > 0 else 0
    complaints = aspire_api(
        f"https://cloud-api.youraspire.com/ClientComplaints?$filter=Status%20eq%20%27Open%27&$top=5"
    )
    h = 'green' if rate >= 70 and not complaints else 'yellow' if rate >= 50 else 'red'
    hlabel = 'Healthy' if h == 'green' else 'Watch' if h == 'yellow' else 'Alert'
    by_branch = {}
    for w in tickets:
        b = w.get('BranchName')
        if not b:
            continue
        if b not in by_branch:
            by_branch[b] = {'total': 0, 'complete': 0, 'open': 0, 'canceled': 0}
        by_branch[b]['total'] += 1
        s = w.get('WorkTicketStatusName')
        if s == 'Complete':  by_branch[b]['complete'] += 1
        elif s == 'Open':    by_branch[b]['open']     += 1
        elif s == 'Canceled':by_branch[b]['canceled'] += 1
    return {
        'health': h, 'health_label': hlabel,
        'complete': len(done), 'canceled': len(canc),
        'open': len(open_wt), 'scheduled': len(sched),
        'total': total, 'rate': rate,
        'sched_revenue': sum(w.get('Revenue', 0) or 0 for w in sched),
        'total_revenue': sum(w.get('Revenue', 0) or 0 for w in tickets),
        'complaints': complaints,
        'by_branch': by_branch,
        'week_start': start, 'week_end': end,
    }

def get_safety():
    """Scan inbox for safety-related emails."""
    try:
        result = subprocess.run(
            ['node', str(Path.home() / '.openclaw/workspace/scripts/scan-safety-emails.js')],
            capture_output=True, text=True, timeout=30
        )
        if result.stdout.strip():
            return json.loads(result.stdout.strip())
    except Exception as e:
        print(f'Safety scan error: {e}')
    return []

# ── escape ────────────────────────────────────────────────────────────────────

def esc(s):
    return str(s or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

# ── HTML builder ───────────────────────────────────────────────────────────────

def build_html(events, stats, safety_incidents):
    today = datetime.date.today().strftime('%A, %B %d, %Y')

    # ── Schedule
    sched_rows = ''
    if events:
        for i, e in enumerate(events):
            t = e.get('start',{}).get('dateTime','')
            time = t.split('T')[1][:5] if 'T' in t else 'TBD'
            loc  = esc(e.get('location',{}).get('displayName',''))
            subj = esc(e.get('subject','No title'))
            eid  = f'sched-{i}'
            sched_rows += f'''
        <div class="item" id="{eid}">
            <div class="item-title">{time} — {subj} <span class="chevron">▸</span></div>
            <div class="item-meta">📍 {loc}</div>
        </div>'''
    else:
        sched_rows = '<div class="item"><div class="item-title">No events scheduled</div></div>'

    # ── Ops Health
    h   = stats
    hcl = '#00d4aa' if h['health']=='green' else '#f59e0b' if h['health']=='yellow' else '#ef4444'
    hbg = '#00d4aa18' if h['health']=='green' else '#f59e0b18' if h['health']=='yellow' else '#ef444418'
    branch_rows = ''
    for branch, d in sorted(h['by_branch'].items(), key=lambda x: -x[1]['total']):
        pct = round(d['complete']/d['total']*100) if d['total']>0 else 0
        branch_rows += f'''
            <div class="branch-row">
                <div class="branch-name">{esc(branch)}</div>
                <div class="branch-bar-wrap"><div class="branch-bar" style="width:{pct}%;background:{hcl};"></div></div>
                <div class="branch-pct">{pct}% ({d['complete']}/{d['total']})</div>
            </div>'''

    # ── Safety
    safety_rows = ''
    if safety_incidents:
        for idx, inc in enumerate(safety_incidents):
            # JS-safe: escape for HTML attribute AND JavaScript string literal
            raw_id = inc.get('id') or f'safety-{idx}'
            sid = esc(raw_id).replace('\\', '\\\\').replace("'", "\\'")
            subj = esc(inc.get('subject',''))[:80]
            frm = esc(inc.get('from','Unknown'))
            date = inc.get('date','')
            body_plain = esc(inc.get('body','')).replace('\n','<br>')
            safety_rows += f'''
        <div class="item urgent" data-id="{sid}">
            <div class="item-title" onclick="toggleSafetyDetail(this)">⚠️ {subj} <span class="chevron">▸</span></div>
            <div class="item-meta">{frm} · {date}</div>
            <div class="safety-detail" style="display:none;margin-top:10px;padding:12px;background:#0a1929;border-radius:8px;font-size:0.85rem;line-height:1.6;">
                <div style="margin-bottom:10px;">{body_plain or 'No additional details available.'}</div>
                <button class="review-btn" onclick="reviewIncident(this,'{sid}')" style="background:#00d4aa;color:#0a1929;border:none;padding:7px 16px;border-radius:6px;font-weight:600;cursor:pointer;font-size:0.85rem;">✅ Review &amp; Close</button>
            </div>
        </div>'''
    else:
        safety_rows = '<div class="item"><div class="item-title">✅ No safety incidents</div></div>'

    # ── Complaints
    complaint_rows = ''
    if h['complaints']:
        for c in h['complaints']:
            complaint_rows += f'''
        <div class="item urgent">
            <div class="item-title">⚠️ {esc(c.get('ClientName','Unknown'))} <span class="chevron">▸</span></div>
            <div class="item-meta">{esc(c.get('Description','')[:60])}</div>
        </div>'''
    else:
        complaint_rows = '<div class="item"><div class="item-title">✅ No active complaints</div></div>'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CG Landscape — Daily Ops</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       background:#0a1929;color:#e0e6ed;min-height:100vh;padding:20px}}
  .container{{max-width:1100px;margin:0 auto;display:flex;flex-direction:column;min-height:100vh}}
  header{{display:flex;justify-content:space-between;align-items:center;padding:20px 0;border-bottom:1px solid #1e3a5f;margin-bottom:30px}}
  h1{{color:#00d4aa;font-size:1.8rem;margin:0}} .subtitle{{color:#7a8c9e;margin-top:4px}}
  .refresh-btn{{background:#00d4aa;color:#0a1929;border:none;padding:10px 20px;border-radius:8px;font-weight:600;font-size:0.85rem;cursor:pointer;white-space:nowrap}}
  .refresh-btn:hover{{background:#00eebb}}
  .refresh-btn.loading{{opacity:0.6;pointer-events:none}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}}
  .card{{background:#112240;border-radius:12px;padding:20px;border:1px solid #1e3a5f}}
  .card h2{{color:#00d4aa;font-size:1rem;margin-bottom:15px;display:flex;align-items:center;gap:8px}}
  .card h2 .emoji{{font-size:1.2rem}}
  .item{{padding:12px 0;border-bottom:1px solid #1e3a5f}}
  .item:last-child{{border-bottom:none}}
  .item-title{{font-weight:500;display:flex;align-items:center;gap:6px}}
  .item-meta{{color:#7a8c9e;font-size:0.8rem;margin-top:4px}}
  .chevron{{margin-left:auto;color:#7a8c9e;font-size:0.8rem}}
  .health-card{{border-radius:10px;padding:16px;text-align:center;
               border:1px solid {hcl};background:{hbg};margin-bottom:16px}}
  .health-status{{font-size:1.2rem;font-weight:700;color:{hcl}}}
  .health-rate{{font-size:1.5rem;font-weight:700;color:{hcl};margin:6px 0}}
  .health-meta{{color:#7a8c9e;font-size:0.8rem}}
  .stats-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
  .stat-item{{background:#0a1929;border-radius:8px;padding:12px;text-align:center}}
  .stat-value{{font-size:1.4rem;font-weight:700;color:#00d4aa}}
  .stat-label{{color:#7a8c9e;font-size:0.75rem}}
  .stat-revenue{{margin-top:10px;color:#e0e6ed;font-size:0.9rem;text-align:center}}
  .branch-row{{display:flex;align-items:center;gap:10px;padding:6px 0}}
  .branch-name{{min-width:90px;font-size:0.85rem;color:#e0e6ed}}
  .branch-bar-wrap{{flex:1;height:8px;background:#1e3a5f;border-radius:4px;overflow:hidden}}
  .branch-bar{{height:100%;border-radius:4px}}
  .branch-pct{{min-width:55px;text-align:right;font-size:0.8rem;color:#7a8c9e}}
  .footer{{text-align:center;padding:20px;color:#7a8c9e;font-size:0.8rem;margin-top:30px}}
  @media(max-width:600px){{.stats-grid{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>🌿 CG Landscape — Daily Ops</h1>
      <div class="subtitle">{today}</div>
    </div>
    <button class="refresh-btn" id="refreshBtn" onclick="hardRefresh()">🔄 Refresh</button>
  </header>

  <div class="grid">
    <div class="card">
      <h2><span class="emoji">📅</span> Next 3 Days</h2>
      {sched_rows}
    </div>

    <div class="card">
      <h2><span class="emoji">📊</span> This Week Ops Health</h2>
      <div class="health-card">
        <div class="health-status">{h['health_label']}</div>
        <div class="health-rate">{h['rate']}%</div>
        <div class="health-meta">Week of {h['week_start']} → {h['week_end']}</div>
      </div>
      <div class="stats-grid">
        <div class="stat-item"><div class="stat-value">{h['complete']}</div><div class="stat-label">Done</div></div>
        <div class="stat-item"><div class="stat-value">{h['canceled']}</div><div class="stat-label">Canceled</div></div>
        <div class="stat-item"><div class="stat-value">{h['open']}</div><div class="stat-label">Open</div></div>
        <div class="stat-item"><div class="stat-value">{h['total']}</div><div class="stat-label">Total</div></div>
      </div>
      <div class="stat-revenue">Scheduled: <strong>${h['sched_revenue']:,.0f}</strong></div>
      <h3 style="color:#00d4aa;font-size:0.85rem;margin:12px 0 6px;">By Branch</h3>
      {branch_rows or '<div class="item"><div class="item-title">No branch data</div></div>'}
    </div>

    <div class="card">
      <h2><span class="emoji">🛡️</span> Safety</h2>
      {safety_rows}
    </div>

    <div class="card">
      <h2><span class="emoji">⚠️</span> Client Complaints</h2>
      {complaint_rows}
    </div>
  </div>

  <div class="footer" id="footer">
    Refreshed {datetime.datetime.now().strftime('%b %d %Y %I:%M %p PT')}
  </div>
</div>
<script>
  function hardRefresh() {{
    var btn = document.getElementById('refreshBtn');
    btn.classList.add('loading');
    btn.textContent = '⏳ Refreshing...';
    fetch('/api/refresh', {{method:'POST'}}).catch(function() {{}}).finally(function() {{
      setTimeout(function() {{ window.location.reload(true); }}, 800);
    }});
  }}

  // expand items on click (compatible with Python f-strings)
  document.querySelectorAll('.item-title').forEach(function(el) {{
    el.addEventListener('click', function() {{
      var item = el.closest(''.concat('.','item'));
      item.classList.toggle('expanded');
    }});
  }});

  // Safety: toggle details open/closed
  function toggleSafetyDetail(el) {{
    var detail = el.parentElement.querySelector('.safety-detail');
    if (!detail) return;
    document.querySelectorAll('.safety-detail').forEach(function(d) {{ d.style.display = 'none'; }});
    detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
  }}

  // Safety: review & close incident
  function reviewIncident(btn, id) {{
    btn.textContent = '⏳ Saving...';
    btn.disabled = true;
    fetch('/api/incident/review', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
      body: 'id=' + encodeURIComponent(id)
    }}).then(function(res) {{ return res.json(); }})
      .then(function(data) {{
        if (data.success) {{
          var item = btn.closest('.item');
          if (item) item.remove();
        }} else {{
          btn.textContent = '✅ Review & Close';
          btn.disabled = false;
          alert('Failed: ' + (data.error || 'unknown'));
        }}
      }}).catch(function(e) {{
        btn.textContent = '✅ Review & Close';
        btn.disabled = false;
        alert('Error: ' + e.message);
      }});
  }}

  // Follow-up checkbox wiring
  document.querySelectorAll('.followup-checkbox').forEach(function(cb) {{
    cb.addEventListener('change', function(e) {{
      var id = cb.dataset.id;
      var val = cb.checked;
      try {{
        fetch('/followup', {{method:'POST', headers:{{'Content-Type':'application/json','Authorization':'Bearer…IJNg'}}, body: JSON.stringify({{id:id, action: val ? 'reviewed' : 'unreviewed'}})}});
      }} catch (err) {{
        alert('Failed to save follow-up');
        cb.checked = !val;
      }}
    }});
  }});
</script>
</body>
</html>'''

# ── main ─────────────────
def main():
    print('Fetching calendar…')
    events = get_calendar()
    print(f'  → {len(events)} events')

    print('Fetching ops health…')
    stats = get_ops_health()
    print(f"  → {stats['total']} tickets, {stats['rate']}% complete")

    print('Scanning safety emails…')
    safety = get_safety()
    print(f'  → {len(safety)} incidents')

    html = build_html(events, stats, safety)
    out = DASHBOARD_DIR / 'index.html'
    out.write_text(html)
    print(f'Written → {out} ({len(html):,} bytes)')

if __name__ == '__main__':
    main()