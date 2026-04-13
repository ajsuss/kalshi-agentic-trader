#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ARCHIVE=false
if [[ "${1:-}" == "--archive-logs" ]]; then
  ARCHIVE=true
fi

stamp="$(date -u +"%Y%m%dT%H%M%SZ")"
archive_dir="logs/archive/$stamp"

kill_pid_file() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "Stopping PID $pid from $pid_file"
      kill "$pid" 2>/dev/null || true
      sleep 0.2
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi
}

kill_by_pattern() {
  local pattern="$1"
  if pgrep -f "$pattern" >/dev/null 2>&1; then
    echo "Stopping processes matching: $pattern"
    pkill -f "$pattern" || true
    sleep 0.2
    pkill -9 -f "$pattern" || true
  fi
}

# Stop known operator paths (new + legacy).
kill_by_pattern "app.interfaces.telegram.main"
kill_by_pattern "scripts/step44_telegram_status_bot.py"
kill_by_pattern "scripts/step48_periodic_brain_loop.py"
kill_by_pattern "scripts/step50_refresh_and_decide.py"

# Kill any PID-file managed background jobs.
kill_pid_file "logs/step50/refresh_command.pid"
kill_pid_file "logs/telegram_app/telegram_app.pid"

runtime_files=(
  "logs/step44/telegram_status_bot_state.json"
  "logs/telegram_app/offset_state.json"
  "logs/step50/refresh_command.out"
)

runtime_dirs=(
  "logs/telegram_app/tmp"
)

if [[ "$ARCHIVE" == true ]]; then
  mkdir -p "$archive_dir"
  echo "Archiving runtime files into $archive_dir"
  for f in "${runtime_files[@]}"; do
    if [[ -f "$f" ]]; then
      mkdir -p "$archive_dir/$(dirname "$f")"
      mv "$f" "$archive_dir/$f"
    fi
  done
  if [[ -f "logs/telegram_app/events.jsonl" ]]; then
    mkdir -p "$archive_dir/logs/telegram_app"
    mv "logs/telegram_app/events.jsonl" "$archive_dir/logs/telegram_app/events.jsonl"
  fi
else
  for f in "${runtime_files[@]}"; do
    rm -f "$f"
  done
  rm -f "logs/telegram_app/events.jsonl"
fi

for d in "${runtime_dirs[@]}"; do
  rm -rf "$d"
done

cat <<'MSG'
Local runtime reset complete.
Preserved:
- .env and secret files
- tracked state files in state/
- dry-run safety defaults (no live arming set by this script)
MSG
