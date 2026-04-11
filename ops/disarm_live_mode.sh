#!/bin/zsh
set -euo pipefail

python - <<'PY'
from pathlib import Path

env_path = Path("/Users/Apple/kalshi-agentic-trader/.env")
text = env_path.read_text(encoding="utf-8")

updates = {
    "EXECUTION_MODE": "dry_run",
    "LIVE_TRADING_ENABLED": "false",
    "LIVE_TRADING_ACK": "",
}

lines = text.splitlines()
seen = set()
new_lines = []

for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0]
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
    new_lines.append(line)

for key, value in updates.items():
    if key not in seen:
        new_lines.append(f"{key}={value}")

env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
PY

echo "Live mode disarmed."
echo "Run this next to verify:"
echo "python scripts/step19_execution_gate.py"
