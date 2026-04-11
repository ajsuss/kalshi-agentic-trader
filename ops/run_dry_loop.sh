#!/bin/zsh
set -euo pipefail

cd /Users/Apple/kalshi-agentic-trader
source .venv/bin/activate

python scripts/step31_multi_event_loop.py --iterations 1 --sleep-seconds 1 >> logs/step32_launchd_runner.log 2>&1
