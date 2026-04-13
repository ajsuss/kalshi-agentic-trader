#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

pass() { echo "[PASS] $1"; }
fail() { echo "[FAIL] $1"; }
warn() { echo "[WARN] $1"; }

if [[ ! -d ".venv" ]]; then
  echo "Creating .venv"
  python3 -m venv .venv
fi
pass ".venv exists"

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements-step2-min.txt >/dev/null
python -m pip install pytest >/dev/null
pass "Dependencies installed"

if [[ -f ".env" ]]; then
  pass ".env present"
else
  fail ".env missing"
fi

set +u
source .env 2>/dev/null || true
set -u

check_secret() {
  local direct_var="$1"
  local file_var="$2"
  local label="$3"

  local direct_val="${!direct_var:-}"
  local file_val="${!file_var:-}"

  if [[ -n "$direct_val" ]]; then
    pass "$label configured via $direct_var"
    return
  fi

  if [[ -n "$file_val" ]]; then
    if [[ -f "$file_val" ]]; then
      pass "$label configured via $file_var"
    else
      fail "$label file missing at $file_val"
    fi
    return
  fi

  fail "$label missing ($direct_var or $file_var)"
}

check_secret "TELEGRAM_BOT_TOKEN" "TELEGRAM_BOT_TOKEN_FILE" "Telegram bot token"

if [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  pass "TELEGRAM_CHAT_ID configured"
else
  fail "TELEGRAM_CHAT_ID missing"
fi

check_secret "KALSHI_API_KEY_ID" "KALSHI_API_KEY_ID_FILE" "Kalshi API key"

if [[ -n "${KALSHI_PRIVATE_KEY_PATH:-}" ]]; then
  if [[ -f "${KALSHI_PRIVATE_KEY_PATH}" ]]; then
    pass "KALSHI_PRIVATE_KEY_PATH exists"
  else
    fail "KALSHI_PRIVATE_KEY_PATH missing file (${KALSHI_PRIVATE_KEY_PATH})"
  fi
else
  fail "KALSHI_PRIVATE_KEY_PATH missing"
fi

python -m app.interfaces.telegram.main --self-check && pass "Telegram app self-check"

if [[ "${EXECUTION_MODE:-dry_run}" != "dry_run" ]]; then
  warn "EXECUTION_MODE is ${EXECUTION_MODE}; expected dry_run for local safety"
else
  pass "EXECUTION_MODE default is dry_run"
fi

if [[ "${KALSHI_LIVE_TRADING_ARMED:-0}" == "1" ]]; then
  warn "KALSHI_LIVE_TRADING_ARMED=1 (live arming set)."
else
  pass "KALSHI_LIVE_TRADING_ARMED is not armed"
fi

echo "Bootstrap checklist complete."
