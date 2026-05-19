#!/bin/bash
# Regenerate CG dashboard and push to GitHub (called by OpenClaw cron)
set -e
cd /Users/aiagent/.openclaw/workspace/cg-dashboard
git pull origin main --quiet 2>/dev/null || true
python3 generate.py
git add index.html
git commit -m "Auto-refresh $(date '+%Y-%m-%d %H:%M')" 2>/dev/null || true
git push origin main
echo "✅ Dashboard refreshed $(date)"