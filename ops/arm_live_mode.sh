#!/bin/zsh
set -euo pipefail

ENV_FILE="/Users/Apple/kalshi-agentic-trader/.env"
ACK_VALUE="I_UNDERSTAND_LIVE_TRADING_IS_ENABLED"

python - <<'PY'
from pathlib import Path

env_path = Path("/Users/Apple/kalshi-agentic-trader/.env")
text = env_path.read_text(encoding="utf-8")

updates = {
    "EXECUTION_MODE": "live",
    "LIVE_TRADING_ENABLED": "true",
    "LIVE_TRADING_ACK": "I_UNDERSTAND_LIVE_TRADING_IS_ENABLED",
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

echo "Live mode env values written."
echo "Run this next to verify:"
echo "python scripts/step19_execution_gate.py"
