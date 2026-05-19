#!/usr/bin/env python3
from http.server import SimpleHTTPRequestHandler, HTTPServer
import json, os
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(__file__)
STATE_DIR = os.path.join(ROOT, '..', 'state')
FOLLOW_FILE = os.path.join(STATE_DIR, 'safety-followups.json')

os.makedirs(STATE_DIR, exist_ok=True)
if not os.path.exists(FOLLOW_FILE):
    with open(FOLLOW_FILE, 'w') as f:
        json.dump({}, f)

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # serve files from cg-dashboard directory
        rel = path.lstrip('/')
        full = os.path.join(ROOT, rel)
        if os.path.isdir(full):
            return full
        return full

    def do_POST(self):
        if self.path.startswith('/followup'):
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            try:
                data = json.loads(body)
                sid = data.get('id')
                val = bool(data.get('value'))
                with open(FOLLOW_FILE, 'r') as f:
                    store = json.load(f)
                store[sid] = val
                with open(FOLLOW_FILE, 'w') as f:
                    json.dump(store, f)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    os.chdir(ROOT)
    port = 8000
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"Serving on 0.0.0.0:{port}")
    server.serve_forever()
