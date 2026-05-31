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

    tickets = []
    skip = 0
    while True:
        url = f"https://cloud-api.youraspire.com/WorkTickets?$filter={urllib.parse.quote(flt)}&$top=1000&$skip={skip}"
        page = aspire_api(url)
        tickets.extend(page)
        if len(page) < 1000:
            break
        skip += 1000

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
    """Return unreviewed safety items.
    Prefer the scanner output because it includes the original incident summary,
    email type, and manager. Fall back to the local queue if scanning fails.
    """
    try:
        result = subprocess.run(
            ['node', str(Path.home() / '.openclaw/workspace/scripts/scan-safety-emails.js')],
            capture_output=True, text=True, timeout=30
        )
        if result.stdout.strip():
            return json.loads(result.stdout.strip())
    except Exception as e:
        print(f'Safety scan error: {e}')

    queue_path = Path.home() / '.openclaw' / 'workspace' / 'state' / 'safety-queue.json'
    try:
        if queue_path.exists():
            with open(queue_path, 'r') as f:
                q = json.load(f)
            # return items with status == 'unreviewed'
            out = []
            # only include items that look like true safety incidents
            safety_kw = ['accident','injur','fall','sprain','fractur','ambulance','hospital','first aid','osha','near miss','near-miss','spill','vehicle incident','hazard','cut','lacerat','broken','sprained','sprain','ankle']
            for it in q:
                if it.get('status') != 'unreviewed':
                    continue
                subj = (it.get('subject') or '').lower()
                desc = (it.get('description') or '').lower()
                blob = subj + ' ' + desc
                if any(k in blob for k in safety_kw):
                    out.append({
                        'id': it.get('id'),
                        'subject': it.get('subject'),
                        'from': it.get('from'),
                        'date': it.get('received'),
                        'description': it.get('description'),
                        'manager': it.get('manager') or '',
                        'emailType': it.get('emailType') or '',
                        'summary': it.get('summary') or it.get('description') or ''
                    })
            return out
    except Exception as e:
        print(f'Failed to read safety queue: {e}')
    return []

def _fetch_all_invoice_revenues(fetcher, filter_expr):
    out = []
    skip = 0
    while True:
        url = (
            'https://cloud-api.youraspire.com/InvoiceRevenues?'
            + urllib.parse.urlencode({
                '$filter': filter_expr,
                '$top': '1000',
                '$skip': str(skip),
            })
        )
        page = fetcher(url)
        out.extend(page)
        if len(page) < 1000:
            break
        skip += 1000
    return out

def _annual_invoice_goal(today=None, fetcher=None):
    today = today or datetime.date.today()
    fetcher = fetcher or aspire_api
    year_start = f'{today.year - 1}-01-01'
    year_end = f'{today.year - 1}-12-31'
    prior_items = _fetch_all_invoice_revenues(fetcher, f'InvoiceDate ge {year_start} and InvoiceDate le {year_end}')
    prior_total = sum((i.get('Amount', 0) or 0) for i in prior_items)
    annual_goal = prior_total * 1.15
    return annual_goal

def get_monthly_invoice_progress(today=None, fetcher=None):
    """Current month invoiced versus the monthly pace target from last year +15%."""
    today = today or datetime.date.today()
    fetcher = fetcher or aspire_api
    month_start = today.replace(day=1)
    annual_goal = _annual_invoice_goal(today=today, fetcher=fetcher)

    current_items = _fetch_all_invoice_revenues(fetcher, f'InvoiceDate ge {month_start.isoformat()} and InvoiceDate le {today.isoformat()}')

    invoiced = sum((i.get('Amount', 0) or 0) for i in current_items)
    goal = annual_goal / 12.0
    pct = round(invoiced / goal * 100) if goal > 0 else 0
    fill = max(0, min(100, pct))

    return {
        'invoiced': invoiced,
        'goal': goal,
        'annual_goal': annual_goal,
        'pct': pct,
        'fill': fill,
        'month_label': today.strftime('%B %Y'),
    }

def get_ytd_invoice_progress(today=None, fetcher=None):
    """Year-to-date invoiced versus the year-to-date pace target from last year +15%."""
    today = today or datetime.date.today()
    fetcher = fetcher or aspire_api
    year_start = today.replace(month=1, day=1)
    annual_goal = _annual_invoice_goal(today=today, fetcher=fetcher)
    current_items = _fetch_all_invoice_revenues(fetcher, f'InvoiceDate ge {year_start.isoformat()} and InvoiceDate le {today.isoformat()}')

    invoiced = sum((i.get('Amount', 0) or 0) for i in current_items)
    year_days = (datetime.date(today.year, 12, 31) - year_start).days + 1
    elapsed_days = (today - year_start).days + 1
    goal = annual_goal * elapsed_days / year_days if year_days > 0 else annual_goal
    pct = round(invoiced / goal * 100) if goal > 0 else 0
    fill = max(0, min(100, pct))

    return {
        'invoiced': invoiced,
        'goal': goal,
        'annual_goal': annual_goal,
        'pct': pct,
        'fill': fill,
        'period_label': f'YTD through {today.strftime("%b %d, %Y")}',
    }

def build_progress_html(actual, goal, period_label='This month', kicker='Monthly Invoiced vs Goal', value_label='invoiced', goal_label='goal'):
    pct = round(actual / goal * 100) if goal > 0 else 0
    fill = max(0, min(100, pct))
    return f'''
      <div class="month-progress-card">
        <div class="month-progress-header">
          <div>
            <div class="month-progress-kicker">{kicker}</div>
            <div class="month-progress-title">{period_label}</div>
          </div>
          <div class="month-progress-pct">{pct}%</div>
        </div>
        <div class="month-progress-bar"><div class="month-progress-fill" style="width:{fill}%;"></div></div>
        <div class="month-progress-meta">${actual:,.0f} {value_label} of ${goal:,.0f} {goal_label}</div>
      </div>'''

def build_month_progress_html(actual, goal, month_label='This month'):
    return build_progress_html(actual, goal, month_label, kicker='Monthly Invoiced vs Goal', value_label='invoiced', goal_label='goal')

def build_ytd_progress_html(actual, goal, period_label='YTD'):
    return build_progress_html(actual, goal, period_label, kicker='YTD Invoiced vs Goal', value_label='invoiced', goal_label='YTD goal')

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
            date_str = ''
            if 'T' in t:
                d = datetime.datetime.strptime(t.split('T')[0], '%Y-%m-%d')
                date_str = d.strftime('%b %d, %Y')  # e.g. "May 20, 2026"
            time_str = t.split('T')[1][:5] if 'T' in t else 'TBD'
            loc  = esc(e.get('location',{}).get('displayName',''))
            subj = esc(e.get('subject','No title'))
            eid  = f'sched-{i}'
            sched_rows += f'''
        <div class="item" id="{eid}">
            <div class="item-title">{date_str} {time_str} — {subj} <span class="chevron">▸</span></div>
            <div class="item-meta">📍 {loc}</div>
        </div>'''
    else:
        sched_rows = '<div class="item"><div class="item-title">No events scheduled</div></div>'

    # ── Ops Health
    h   = stats
    hcl = '#00d4aa' if h['health']=='green' else '#f59e0b' if h['health']=='yellow' else '#ef4444'
    hbg = '#00d4aa18' if h['health']=='green' else '#f59e0b18' if h['health']=='yellow' else '#ef444418'
    month_progress = get_monthly_invoice_progress()
    month_progress_html = build_month_progress_html(
        month_progress['invoiced'],
        month_progress['goal'],
        month_progress['month_label']
    )
    ytd_progress = get_ytd_invoice_progress()
    ytd_progress_html = build_ytd_progress_html(
        ytd_progress['invoiced'],
        ytd_progress['goal'],
        ytd_progress['period_label']
    )
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
            raw_id = inc.get('itemId') or inc.get('id') or f'safety-{idx}'
            sid = esc(raw_id).replace('\\', '\\\\').replace("'", "\\'")
            subj = esc(inc.get('subject','')[:80])
            frm = esc(inc.get('from','Unknown'))
            date = inc.get('date','')
            manager = esc(inc.get('manager') or '')
            email_type = inc.get('emailType','')
            summary = esc(inc.get('summary') or '')
            body_plain = esc((inc.get('description') or '').replace('\n', '<br>'))
            type_badge = '🔄 Forwarded' if email_type == 'forwarded' else ('↩️ Reply' if email_type == 'reply' else '📩 Original')
            manager_line = f'<div style="margin-bottom:6px;font-size:0.8rem;color:#00d4aa;">👔 Manager: {manager}</div>' if manager else ''
            summary_line = f'<div style="margin-bottom:8px;padding:10px 12px;background:#0f2035;border:1px solid rgba(46,230,166,.18);border-radius:8px;color:var(--text);font-size:0.85rem;"><strong>Brief description:</strong> {summary}</div>' if summary else ''
            safety_rows += f'''
        <div class="item urgent" data-id="{sid}" data-subject="{subj}" data-from="{frm}" data-date="{date}" data-summary="{summary}" data-manager="{manager}" data-email-type="{esc(email_type)}" data-description="{body_plain}" data-link="{esc(inc.get('link',''))}">
            <div class="item-title" onclick="toggleSafetyDetail(this)">⚠️ {subj} <span class="chevron">▸</span></div>
            <div class="item-meta">{type_badge} · {frm} · {date} <span class="safety-state-badge" style="display:none;margin-left:8px;padding:2px 8px;border-radius:999px;font-size:.7rem;font-weight:800;background:#243b5b;color:var(--accent);">🩼 Modified Duty</span></div>
            <div class="safety-detail" style="display:none;margin-top:10px;padding:12px;background:#0a1929;border-radius:8px;font-size:0.85rem;line-height:1.6;">
                {manager_line}
                {summary_line}
                <div style="margin-bottom:10px;">{body_plain or 'No additional details available.'}</div>
                <div style="display:flex;flex-wrap:wrap;gap:8px;">
                  <button class="safety-action-btn" onclick="setSafetyState(this,'{sid}','modified_duty')" style="background:#0d6efd;color:#fff;border:none;padding:7px 14px;border-radius:6px;font-weight:600;cursor:pointer;font-size:0.82rem;">🩼 Mark Modified Duty</button>
                  <button class="safety-action-btn" onclick="setSafetyState(this,'{sid}','open')" style="background:#35506f;color:#fff;border:none;padding:7px 14px;border-radius:6px;font-weight:600;cursor:pointer;font-size:0.82rem;">↩️ Clear Modified Duty</button>
                  <button class="review-btn" onclick="setSafetyState(this,'{sid}','closed')" style="background:#00d4aa;color:#0a1929;border:none;padding:7px 16px;border-radius:6px;font-weight:600;cursor:pointer;font-size:0.85rem;">✅ Close Incident</button>
                </div>
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
:root{{
  --bg0:#07111d;
  --bg1:#0b1727;
  --panel:rgba(17,34,64,.78);
  --panel-strong:#112240;
  --line:rgba(99,146,191,.18);
  --text:#e7eef8;
  --muted:#8ea3b8;
  --accent:#2ee6a6;
  --accent-soft:rgba(46,230,166,.15);
  --shadow:0 18px 50px rgba(1,8,18,.35);
}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
     background:radial-gradient(circle at top, #112744 0, var(--bg0) 38%, var(--bg1) 100%);
     color:var(--text);min-height:100vh;padding:24px;line-height:1.45;-webkit-font-smoothing:antialiased}}
.container{{max-width:1240px;margin:0 auto;display:flex;flex-direction:column;min-height:100vh}}
header{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;padding:18px 0 22px;border-bottom:1px solid var(--line);margin-bottom:24px}}
h1{{display:flex;align-items:center;gap:14px;color:var(--text);font-size:2rem;letter-spacing:-.02em;margin:0}}
  .brand-logo{{width:54px;height:54px;flex:0 0 54px;object-fit:contain;border-radius:14px;background:rgba(255,255,255,.06);padding:4px;box-shadow:0 10px 24px rgba(0,0,0,.18)}}
  .subtitle{{color:var(--muted);margin-top:6px;font-size:.95rem}}

.refresh-btn:hover{{filter:brightness(1.05);transform:translateY(-1px)}}
.refresh-btn.loading{{opacity:0.6;pointer-events:none;transform:none}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}}
.card{{background:var(--panel);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:20px;padding:20px;border:1px solid var(--line);box-shadow:var(--shadow)}}
.card h2{{color:var(--text);font-size:1rem;margin-bottom:16px;display:flex;align-items:center;gap:10px;letter-spacing:.01em}}
.card h2 .emoji{{font-size:1.15rem}}
.item{{padding:14px 0;border-bottom:1px solid var(--line)}}
.item:last-child{{border-bottom:none}}
.item-title{{font-weight:600;display:flex;align-items:center;gap:8px}}
.item-meta{{color:var(--muted);font-size:.82rem;margin-top:6px}}
.chevron{{margin-left:auto;color:var(--muted);font-size:.8rem}}
.health-card{{border-radius:16px;padding:18px;text-align:center;border:1px solid {hcl};background:{hbg};margin-bottom:16px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.03)}}
.health-status{{font-size:1rem;font-weight:800;color:{hcl};text-transform:uppercase;letter-spacing:.08em}}
.health-rate{{font-size:2rem;font-weight:800;color:{hcl};margin:8px 0 6px}}
.health-meta{{color:var(--muted);font-size:.82rem}}
.month-progress-card{{border-radius:16px;padding:18px;border:1px solid rgba(99,146,191,.22);background:linear-gradient(180deg,rgba(10,23,39,.95),rgba(10,23,39,.75));margin:0 0 16px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.03)}}
.month-progress-header{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}}
.month-progress-kicker{{font-size:.72rem;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:4px}}
.month-progress-title{{font-size:1rem;font-weight:800;color:var(--text)}}
.month-progress-pct{{font-size:1.6rem;font-weight:900;color:var(--accent);line-height:1}}
.month-progress-bar{{height:12px;background:#15243c;border-radius:999px;overflow:hidden}}
.month-progress-fill{{height:100%;border-radius:999px;background:linear-gradient(90deg,#2ee6a6,#1abf8a);box-shadow:0 0 0 1px rgba(255,255,255,.05) inset}}
.month-progress-meta{{margin-top:10px;color:var(--muted);font-size:.86rem}}
.stats-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.stat-item{{background:#0b1727;border-radius:14px;padding:14px;text-align:center;border:1px solid rgba(255,255,255,.04)}}
.stat-value{{font-size:1.5rem;font-weight:800;color:var(--accent);line-height:1}}
.stat-label{{color:var(--muted);font-size:.75rem;margin-top:6px;letter-spacing:.02em;text-transform:uppercase}}
.stat-revenue{{margin-top:12px;color:var(--text);font-size:.95rem;text-align:center}}
.branch-row{{display:flex;align-items:center;gap:10px;padding:7px 0}}
.branch-name{{min-width:96px;font-size:.84rem;color:var(--text)}}
.branch-bar-wrap{{flex:1;height:9px;background:#15243c;border-radius:999px;overflow:hidden}}
.branch-bar{{height:100%;border-radius:999px}}
.branch-pct{{min-width:64px;text-align:right;font-size:.8rem;color:var(--muted)}}
.footer{{text-align:center;padding:20px;color:var(--muted);font-size:.8rem;margin-top:30px}}
@media(max-width:600px){{body{{padding:14px}} header{{padding:10px 0 18px}} h1{{font-size:1.6rem}} .grid{{grid-template-columns:1fr}} .stats-grid{{grid-template-columns:repeat(2,1fr)}} .card{{padding:16px}}}}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1><img class="brand-logo" src="cg-logo.png" alt="CG Landscape logo"> CG Landscape — Daily Ops</h1>
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
      <h2><span class="emoji">💵</span> Monthly Invoiced vs Goal</h2>
      {month_progress_html}
    </div>

    <div class="card">
      <h2><span class="emoji">📈</span> YTD Invoiced vs Goal</h2>
      {ytd_progress_html}
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

  // Safety: write state to backend tracker; open/modified duty items stay visible,
  // closed items are hidden.
  function setSafetyState(btn, id, action) {{
    btn.textContent = '⏳ Saving...';
    btn.disabled = true;
    var item = btn.closest('.item');
    var payload = {{id: id, action: action}};
    if (item) {{
      payload.subject = item.dataset.subject || '';
      payload.from = item.dataset.from || '';
      payload.date = item.dataset.date || '';
      payload.summary = item.dataset.summary || '';
      payload.description = item.dataset.description || '';
      payload.manager = item.dataset.manager || '';
      payload.emailType = item.dataset.emailType || '';
      payload.link = item.dataset.link || '';
    }}
    if (action === 'modified_duty' && item) {{
      var badge = item.querySelector('.safety-state-badge');
      if (badge) badge.style.display = 'inline-flex';
    }}
    if (action === 'open' && item) {{
      var badge = item.querySelector('.safety-state-badge');
      if (badge) badge.style.display = 'none';
    }}
    if (action === 'closed') {{
      try {{
        var reviewed = JSON.parse(localStorage.getItem('cg_reviewed') || '[]');
        if (!reviewed.includes(id)) reviewed.push(id);
        localStorage.setItem('cg_reviewed', JSON.stringify(reviewed));
      }} catch(e) {{}}
    }}
    fetch('/api/incident/review', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload)
    }}).then(function(res) {{
      if (!res.ok) throw new Error('backend save failed');
      return res.json();
    }}).then(function(data) {{
      if (!data || !data.success) throw new Error('backend save failed');
      if (action === 'closed' && item) item.remove();
      if (item && action !== 'closed') {{
        btn.textContent = action === 'modified_duty' ? '🩼 Modified Duty Saved' : '↩️ Modified Duty Cleared';
      }}
    }}).catch(function() {{
      if (action === 'closed' && item) item.remove();
      if (item && action !== 'closed') {{
        btn.textContent = action === 'modified_duty' ? '🩼 Modified Duty Saved' : '↩️ Modified Duty Cleared';
      }}
    }});
  }}

  // On load: hide any previously closed incidents (backend first, then localStorage)
  (function() {{
    function hideClosed(ids) {{
      ids.forEach(function(id) {{
        var el = document.querySelector('[data-id="' + id + '"]');
        if (el) el.remove();
      }});
    }}
    function applyModifiedDuty(ids) {{
      ids.forEach(function(id) {{
        var el = document.querySelector('[data-id="' + id + '"]');
        if (el) {{
          var badge = el.querySelector('.safety-state-badge');
          if (badge) badge.style.display = 'inline-flex';
        }}
      }});
    }}
    function mergeClosed(ids) {{
      try {{
        var reviewed = JSON.parse(localStorage.getItem('cg_reviewed') || '[]');
        ids.forEach(function(id) {{ if (!reviewed.includes(id)) reviewed.push(id); }});
        localStorage.setItem('cg_reviewed', JSON.stringify(reviewed));
      }} catch(e) {{}}
    }}
    try {{
      var reviewed = JSON.parse(localStorage.getItem('cg_reviewed') || '[]');
      hideClosed(reviewed);
    }} catch(e) {{}}
    fetch('/api/incident/reviews')
      .then(function(res) {{ if (!res.ok) throw new Error('tracker unavailable'); return res.json(); }})
      .then(function(data) {{
        var items = (data && data.success && Array.isArray(data.items)) ? data.items : [];
        var closedIds = items.filter(function(it) {{ return (it.status || 'closed') === 'closed'; }}).map(function(it) {{ return it.id; }}).filter(Boolean);
        var dutyIds = items.filter(function(it) {{ return it.status === 'modified_duty'; }}).map(function(it) {{ return it.id; }}).filter(Boolean);
        if (closedIds.length) {{
          hideClosed(closedIds);
          mergeClosed(closedIds);
        }}
        if (dutyIds.length) applyModifiedDuty(dutyIds);
      }})
      .catch(function() {{}});
  }})();

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