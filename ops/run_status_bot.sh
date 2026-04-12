#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Ensure bot dependencies are present in the active interpreter.
if ! python3 -c "import requests, dotenv" >/dev/null 2>&1; then
  python3 -m pip install -r requirements-step2-min.txt >/dev/null
fi

mkdir -p logs/step44
exec python3 scripts/step44_telegram_status_bot.py "$@"
