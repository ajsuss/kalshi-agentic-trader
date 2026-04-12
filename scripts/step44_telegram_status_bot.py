#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"
STATE_PATH = REPO_ROOT / "logs" / "step44" / "telegram_status_bot_state.json"
STEP43_PATH = REPO_ROOT / "scripts" / "step43_repo_state_snapshot.py"
STEP45_PATH = REPO_ROOT / "scripts" / "step45_team_status_snapshot.py"
STEP46_PATH = REPO_ROOT / "scripts" / "step46_control_plane_digest.py"
STEP47_PATH = REPO_ROOT / "scripts" / "step47_deliberation_cycle.py"
STEP48_LOG_PATH = REPO_ROOT / "logs" / "step48" / "periodic_brain_loop.jsonl"
STEP49_PATH = REPO_ROOT / "scripts" / "step49_performance_snapshot.py"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_secret_from_env_or_file(env_name: str, file_env_name: str) -> str:
    direct = os.getenv(env_name, "").strip()
    if direct:
        return direct

    file_path = os.getenv(file_env_name, "").strip()
    if file_path and Path(file_path).exists():
        return Path(file_path).read_text(encoding="utf-8").strip()

    raise RuntimeError(f"Missing {env_name} or {file_env_name}")


def load_offset() -> int | None:
    if not STATE_PATH.exists():
        return None
    payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    value = payload.get("next_update_offset")
    return int(value) if value is not None else None


def save_offset(offset: int) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "ts": utc_now_iso(),
                "next_update_offset": offset,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def fetch_updates(base_url: str, offset: int | None, timeout_seconds: int) -> dict:
    params: dict[str, int] = {"timeout": timeout_seconds}
    if offset is not None:
        params["offset"] = offset
    response = requests.get(f"{base_url}/getUpdates", params=params, timeout=timeout_seconds + 10)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok", False):
        raise RuntimeError(f"Telegram getUpdates failed: {payload}")
    return payload


def send_message(base_url: str, chat_id: str, text: str) -> None:
    response = requests.post(
        f"{base_url}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok", False):
        raise RuntimeError(f"Telegram sendMessage failed: {payload}")


def load_snapshot_json() -> dict:
    completed = subprocess.run(
        ["python3", str(STEP43_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"step43 snapshot command failed with code {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def load_team_status_json() -> dict:
    completed = subprocess.run(
        ["python3", str(STEP45_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"step45 team status command failed with code {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def load_digest_json() -> dict:
    completed = subprocess.run(
        ["python3", str(STEP46_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"step46 digest command failed with code {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def run_deliberation_cycle_json() -> dict:
    completed = subprocess.run(
        ["python3", str(STEP47_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"step47 cycle command failed with code {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def load_latest_brain_iteration() -> dict | None:
    if not STEP48_LOG_PATH.exists():
        return None
    latest = None
    with STEP48_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == "step48_periodic_brain_loop_iteration":
                latest = record
    return latest


def load_performance_json() -> dict:
    completed = subprocess.run(
        ["python3", str(STEP49_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"step49 performance command failed with code {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def format_bool(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    return str(value)


def parse_iso_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def format_status(snapshot: dict) -> str:
    blocked_by = snapshot.get("guarded_live_path_blocked_by", []) or []
    blocked_text = ", ".join(blocked_by) if blocked_by else "none"
    return "\n".join(
        [
            "Kalshi Agent Status",
            f"Source: {snapshot.get('state_source')}",
            f"Active candidates: {snapshot.get('active_candidate_count')}",
            f"Retired candidates: {snapshot.get('retired_candidate_count')}",
            f"Executor actionable now: {format_bool(snapshot.get('executor_actionable_now'))}",
            f"retired_candidate_market_ticker: {snapshot.get('retired_candidate_market_ticker')}",
            f"Guarded live path blocked by: {blocked_text}",
            f"Execution mode: {snapshot.get('execution_mode')}",
            f"Snapshot ts: {snapshot.get('snapshot_ts')}",
        ]
    )


def format_queue(snapshot: dict) -> str:
    return "\n".join(
        [
            "Kalshi Queue",
            f"Active candidates: {snapshot.get('active_candidate_count')}",
            f"Retired candidates: {snapshot.get('retired_candidate_count')}",
            f"Top retired ticker: {snapshot.get('retired_candidate_market_ticker')}",
            f"Executor actionable now: {format_bool(snapshot.get('executor_actionable_now'))}",
            f"Snapshot source: {snapshot.get('state_source')}",
        ]
    )


def format_health(snapshot: dict) -> str:
    now = datetime.now(timezone.utc)
    snapshot_ts = parse_iso_utc(snapshot.get("snapshot_ts"))
    age_seconds = None
    if snapshot_ts is not None:
        age_seconds = round((now - snapshot_ts).total_seconds(), 1)

    return "\n".join(
        [
            "Kalshi Bot Health",
            "Bot process: up",
            f"Snapshot source: {snapshot.get('state_source')}",
            f"Snapshot age seconds: {age_seconds}",
            f"Execution mode: {snapshot.get('execution_mode')}",
            f"Checked at: {now.isoformat()}",
        ]
    )


def format_teams(team_snapshot: dict) -> str:
    teams = team_snapshot.get("teams", {})
    lines = ["Kalshi Team Status"]
    ordered = ["algorithms", "information_media", "deliberators", "executor", "budget_distributor"]
    for name in ordered:
        item = teams.get(name, {})
        lines.append(f"- {name}: {item.get('status')} | {item.get('summary')}")
    lines.append(f"Snapshot source: {team_snapshot.get('state_source')}")
    lines.append(f"Snapshot ts: {team_snapshot.get('snapshot_ts')}")
    return "\n".join(lines)


def format_progress(team_snapshot: dict) -> str:
    progress = team_snapshot.get("progress", {})
    milestones = progress.get("milestones", []) or []
    milestone_text = ", ".join(milestones) if milestones else "none"
    return "\n".join(
        [
            "Kalshi Progress",
            f"Phase: {progress.get('phase')}",
            f"Summary: {progress.get('summary')}",
            f"Milestones: {milestone_text}",
            f"Snapshot ts: {team_snapshot.get('snapshot_ts')}",
        ]
    )


def format_next_trade(team_snapshot: dict) -> str:
    trade = team_snapshot.get("next_best_trade", {})
    return "\n".join(
        [
            "Kalshi Next Trade",
            f"Available: {format_bool(trade.get('available'))}",
            f"Reason: {trade.get('reason')}",
            f"Market ticker: {trade.get('market_ticker')}",
            f"Confidence: {trade.get('confidence')}",
        ]
    )


def format_digest(digest: dict) -> str:
    d = digest.get("digest", {})
    return "\n".join(
        [
            "Kalshi Control Digest",
            f"Source: {d.get('source')}",
            f"Execution mode: {d.get('execution_mode')}",
            f"Queue active/retired: {d.get('active_candidate_count')}/{d.get('retired_candidate_count')}",
            f"Executor actionable now: {format_bool(d.get('executor_actionable_now'))}",
            f"Guarded path blocked by: {d.get('guarded_path_blocked_by_text')}",
            f"Next trade available: {format_bool(d.get('next_best_trade_available'))}",
            f"Next trade ticker: {d.get('next_best_trade_market_ticker')}",
            f"Next trade reason: {d.get('next_best_trade_reason')}",
            f"Phase: {d.get('phase')}",
            f"Digest ts: {digest.get('ts')}",
        ]
    )


def format_cycle(cycle: dict) -> str:
    d = cycle.get("deliberation", {})
    i = cycle.get("inputs", {})
    return "\n".join(
        [
            "Kalshi Deliberation Cycle",
            f"Priority: {d.get('priority')}",
            f"Recommended next step: {d.get('recommended_next_step')}",
            f"Rationale: {d.get('rationale')}",
            f"Active/retired queue: {i.get('active_candidate_count')}/{i.get('retired_candidate_count')}",
            f"Executor actionable now: {format_bool(i.get('executor_actionable_now'))}",
            f"Blocked by: {', '.join(i.get('blocked_by', [])) or 'none'}",
            f"Cycle ts: {cycle.get('ts')}",
        ]
    )


def format_brain_status(record: dict | None) -> str:
    if record is None:
        return "\n".join(
            [
                "Kalshi Brain Loop",
                "No brain loop iterations found yet.",
                "Run: ./ops/run_brain_loop.sh --iterations 1",
            ]
        )

    cycle = record.get("cycle", {}).get("deliberation", {})
    digest = record.get("digest", {}).get("digest", {})
    return "\n".join(
        [
            "Kalshi Brain Loop",
            f"Latest iteration: {record.get('iteration')}",
            f"Priority: {cycle.get('priority')}",
            f"Recommended step: {cycle.get('recommended_next_step')}",
            f"Queue active/retired: {digest.get('active_candidate_count')}/{digest.get('retired_candidate_count')}",
            f"Executor actionable now: {format_bool(digest.get('executor_actionable_now'))}",
            f"Blocked by: {digest.get('guarded_path_blocked_by_text')}",
            f"Logged at: {record.get('ts')}",
        ]
    )


def format_performance(snapshot: dict) -> str:
    p = snapshot.get("performance", {})
    c = snapshot.get("control_plane", {})
    b = snapshot.get("brain_loop_stats", {})

    return "\n".join(
        [
            "Kalshi Performance",
            f"Starting bankroll: ${p.get('starting_bankroll_usd')}",
            f"Current bankroll: ${p.get('current_bankroll_usd')}",
            f"Realized PnL: ${p.get('realized_pnl_usd')}",
            f"Unrealized PnL: ${p.get('unrealized_pnl_usd')}",
            f"Win rate: {p.get('win_rate')}",
            f"Max drawdown %: {p.get('max_drawdown_pct')}",
            f"Brain iterations: {b.get('iterations_count')}",
            f"Priority counts: {b.get('priority_counts')}",
            f"Recommended-step counts: {b.get('recommended_next_step_counts')}",
            f"Control source: {c.get('state_source')}",
            f"Execution mode: {c.get('execution_mode')}",
            f"Snapshot ts: {snapshot.get('ts')}",
        ]
    )


def extract_message(update: dict) -> tuple[int | None, str | None, int | None]:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None, None, None
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text")
    update_id = update.get("update_id")
    return int(chat_id) if chat_id is not None else None, text, int(update_id) if update_id is not None else None


def handle_updates(base_url: str, configured_chat_id: str | None, updates: list[dict]) -> int | None:
    newest_id = None
    for update in updates:
        chat_id, text, update_id = extract_message(update)
        if update_id is not None:
            newest_id = update_id if newest_id is None else max(newest_id, update_id)

        if chat_id is None or not text:
            continue

        if configured_chat_id and str(chat_id) != configured_chat_id:
            continue

        normalized = text.strip().split()[0].lower()
        if normalized not in {"/status", "/state", "/health", "/queue", "/teams", "/progress", "/nexttrade", "/digest", "/cycle", "/brain", "/performance"}:
            continue

        if normalized in {"/status", "/state"}:
            snapshot = load_snapshot_json()
            response_text = format_status(snapshot)
        elif normalized == "/queue":
            snapshot = load_snapshot_json()
            response_text = format_queue(snapshot)
        elif normalized == "/health":
            snapshot = load_snapshot_json()
            response_text = format_health(snapshot)
        elif normalized == "/teams":
            team_snapshot = load_team_status_json()
            response_text = format_teams(team_snapshot)
        elif normalized == "/progress":
            team_snapshot = load_team_status_json()
            response_text = format_progress(team_snapshot)
        elif normalized == "/digest":
            digest = load_digest_json()
            response_text = format_digest(digest)
        elif normalized == "/cycle":
            cycle = run_deliberation_cycle_json()
            response_text = format_cycle(cycle)
        elif normalized == "/brain":
            response_text = format_brain_status(load_latest_brain_iteration())
        elif normalized == "/performance":
            response_text = format_performance(load_performance_json())
        else:
            team_snapshot = load_team_status_json()
            response_text = format_next_trade(team_snapshot)

        send_message(base_url, str(chat_id), response_text)

    return newest_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram /status responder backed by step43 snapshot")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--long-poll-timeout", type=int, default=15)
    parser.add_argument("--run-once", action="store_true")
    return parser.parse_args()


def main() -> None:
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)

    args = parse_args()

    token = read_secret_from_env_or_file("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_FILE")
    configured_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip() or None
    base_url = f"https://api.telegram.org/bot{token}"

    while True:
        try:
            offset = load_offset()
            payload = fetch_updates(base_url, offset, args.long_poll_timeout)
            updates = payload.get("result", [])
            newest_update_id = handle_updates(base_url, configured_chat_id, updates)
            if newest_update_id is not None:
                save_offset(newest_update_id + 1)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(json.dumps({"ts": utc_now_iso(), "error": str(e)}))

        if args.run_once:
            return

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
