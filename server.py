#!/usr/bin/env python3
from http.server import SimpleHTTPRequestHandler, HTTPServer
import datetime
import json, os
from urllib.parse import parse_qs

ROOT = os.path.dirname(__file__)
STATE_DIR = os.path.join(ROOT, '..', 'state')
TRACKERS_DIR = os.path.join(STATE_DIR, 'trackers')
REVIEW_FILE = os.path.join(TRACKERS_DIR, 'reviewed-safety.json')
FOLLOW_FILE = os.path.join(STATE_DIR, 'safety-followups.json')

os.makedirs(TRACKERS_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)
if not os.path.exists(REVIEW_FILE):
    with open(REVIEW_FILE, 'w') as f:
        json.dump([], f)
if not os.path.exists(FOLLOW_FILE):
    with open(FOLLOW_FILE, 'w') as f:
        json.dump({}, f)


def load_reviewed_safety(tracker_path=REVIEW_FILE):
    try:
        with open(tracker_path, 'r') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _write_reviewed_safety(items, tracker_path=REVIEW_FILE):
    os.makedirs(os.path.dirname(tracker_path), exist_ok=True)
    with open(tracker_path, 'w') as f:
        json.dump(items, f, indent=2, sort_keys=False)


def _review_timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def _normalize_status(action):
    action = (action or 'closed').strip().lower()
    if action in ('modified_duty', 'modified-duty', 'modified duty'):
        return 'modified_duty'
    if action in ('clear_modified_duty', 'clear-modified-duty', 'remove_modified_duty', 'remove-modified-duty', 'open'):
        return 'open'
    return 'closed'


def record_safety_review(payload, tracker_path=REVIEW_FILE, source='dashboard-review', reviewed_at=None):
    """Persist a safety incident state to the backend tracker.

    The tracker stores one row per incident id and upserts on repeat actions.
    status values:
      - open
      - modified_duty
      - closed
    """
    if not isinstance(payload, dict):
        raise TypeError('payload must be a dict')

    incident_id = (payload.get('id') or payload.get('itemId') or '').strip()
    if not incident_id:
        raise ValueError('missing incident id')

    reviewed_at = reviewed_at or _review_timestamp()
    status = _normalize_status(payload.get('action') or payload.get('status'))
    ts_field = 'reviewed_at' if status == 'closed' else ('modified_duty_at' if status == 'modified_duty' else 'updated_at')
    entry = {
        'id': incident_id,
        'status': status,
        ts_field: reviewed_at,
        'source': source,
    }
    if status == 'closed':
        entry['closed_at'] = reviewed_at
    if status == 'modified_duty':
        duty = payload.get('modified_duty') or payload.get('duty') or payload.get('restriction') or payload.get('notes')
        if duty not in (None, ''):
            entry['modified_duty'] = duty
    for key in ('subject', 'from', 'date', 'description', 'summary', 'manager', 'emailType', 'link'):
        value = payload.get(key)
        if value not in (None, ''):
            entry[key] = value

    items = load_reviewed_safety(tracker_path)
    updated = False
    for idx, existing in enumerate(items):
        if existing.get('id') == incident_id:
            merged = dict(existing)
            merged.update(entry)
            # preserve prior modified duty note when clearing/opening/closing unless explicitly replaced
            if 'modified_duty' not in merged and existing.get('modified_duty'):
                merged['modified_duty'] = existing['modified_duty']
            items[idx] = merged
            entry = merged
            updated = True
            break
    if not updated:
        items.append(entry)
    _write_reviewed_safety(items, tracker_path)
    return entry


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # serve files from cg-dashboard directory
        rel = path.lstrip('/')
        full = os.path.join(ROOT, rel)
        if os.path.isdir(full):
            return full
        return full

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length).decode('utf-8') if length else ''

    def _json_response(self, status, payload):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def do_GET(self):
        if self.path.startswith('/api/incident/reviews'):
            self._json_response(200, {'success': True, 'items': load_reviewed_safety()})
            return
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/incident/review'):
            body = self._read_body()
            try:
                if body.strip().startswith('{'):
                    data = json.loads(body)
                else:
                    parsed = parse_qs(body)
                    data = {k: v[0] for k, v in parsed.items()}
                entry = record_safety_review(data)
                self._json_response(200, {'success': True, 'item': entry, 'items': load_reviewed_safety(), 'count': len(load_reviewed_safety())})
            except Exception as e:
                self._json_response(400, {'success': False, 'error': str(e)})
            return
        if self.path.startswith('/followup'):
            try:
                data = json.loads(self._read_body())
                sid = data.get('id')
                val = bool(data.get('value'))
                with open(FOLLOW_FILE, 'r') as f:
                    store = json.load(f)
                store[sid] = val
                with open(FOLLOW_FILE, 'w') as f:
                    json.dump(store, f)
                self._json_response(200, {'ok': True})
            except Exception as e:
                self._json_response(400, {'ok': False, 'error': str(e)})
            return
        self.send_response(404)
        self.end_headers()

if __name__ == '__main__':
    os.chdir(ROOT)
    port = 8000
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"Serving on 0.0.0.0:{port}")
    server.serve_forever()
