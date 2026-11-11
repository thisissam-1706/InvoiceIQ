#!/usr/bin/env bash
# One-time setup: Python venv + deps, frontend build, sample invoices, reference data.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"' \
  || { echo "Python 3.10+ is required (found $("$PYTHON" --version 2>&1))"; exit 1; }
command -v npm >/dev/null || { echo "Node.js 18+ (npm) is required"; exit 1; }

echo "==> Creating virtual environment (.venv)"
[ -d .venv ] || "$PYTHON" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing Python dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "==> Installing and building the web UI"
(cd frontend && npm install --no-audit --no-fund && npm run build)

echo "==> Generating sample invoices"
python backend/scripts/generate_samples.py

echo "==> Loading reference data"
python backend/scripts/seed.py

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Created .env from .env.example"
fi

cat <<'EOF'

Setup complete.

  Start the app:        ./run.sh            → http://localhost:8000
  Run the tests:        source .venv/bin/activate && pytest
  Batch all samples:    python backend/scripts/run_batch.py --provider offline

To use Gemini, put your key in .env (GEMINI_API_KEY=...). Without a key the app
runs with the offline extractor and says so in the sidebar.
EOF
