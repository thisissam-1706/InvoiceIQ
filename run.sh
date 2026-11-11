#!/usr/bin/env bash
# Start InvoiceIQ on http://localhost:8000 (rebuilds the UI if its sources changed).
set -euo pipefail
cd "$(dirname "$0")"

[ -d .venv ] || { echo "No .venv found. Run ./setup.sh first."; exit 1; }
# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html -print -quit)" ]; then
  echo "==> Building web UI"
  (cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build)
fi

[ -f backend/data/samples/manifest.json ] || python backend/scripts/generate_samples.py

PORT="${PORT:-8000}"
echo "==> InvoiceIQ running at http://localhost:${PORT}  (Ctrl+C to stop)"
exec uvicorn backend.app.main:app --host 127.0.0.1 --port "$PORT"
