#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STEP46_PATH = REPO_ROOT / "scripts" / "step46_control_plane_digest.py"
STEP47_PATH = REPO_ROOT / "scripts" / "step47_deliberation_cycle.py"
LOG_PATH = REPO_ROOT / "logs" / "step48" / "periodic_brain_loop.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_script(path: Path) -> dict:
    completed = subprocess.run(
        ["python3", str(path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{path.name} failed with code {completed.returncode}: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_secret_from_env_or_file(env_name: str, file_env_name: str) -> str:
    direct = os.getenv(env_name, "").strip()
    if direct:
        return direct

    file_path = os.getenv(file_env_name, "").strip()
    if file_path and Path(file_path).exists():
        return Path(file_path).read_text(encoding="utf-8").strip()

    raise RuntimeError(f"Missing {env_name} or {file_env_name}")


def send_telegram(text: str) -> None:
    import requests

    token = read_secret_from_env_or_file("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_FILE")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise RuntimeError("Missing TELEGRAM_CHAT_ID")

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()


def format_push_message(iteration: int, cycle: dict, digest: dict) -> str:
    d = digest.get("digest", {})
    c = cycle.get("deliberation", {})
    return "\n".join(
        [
            f"Kalshi Brain Loop Iteration #{iteration}",
            f"Priority: {c.get('priority')}",
            f"Recommended step: {c.get('recommended_next_step')}",
            f"Queue active/retired: {d.get('active_candidate_count')}/{d.get('retired_candidate_count')}",
            f"Executor actionable now: {d.get('executor_actionable_now')}",
            f"Blocked by: {d.get('guarded_path_blocked_by_text')}",
            f"Next trade available: {d.get('next_best_trade_available')}",
            f"Digest source: {d.get('source')}",
            f"ts: {utc_now_iso()}",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--sleep-seconds", type=float, default=60.0)
    parser.add_argument("--push-telegram", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    for i in range(1, args.iterations + 1):
        cycle = run_script(STEP47_PATH)
        digest = run_script(STEP46_PATH)

        record = {
            "ts": utc_now_iso(),
            "kind": "step48_periodic_brain_loop_iteration",
            "iteration": i,
            "cycle": cycle,
            "digest": digest,
            "push_telegram_enabled": args.push_telegram,
        }
        append_jsonl(LOG_PATH, record)

        if args.push_telegram:
            send_telegram(format_push_message(i, cycle, digest))

        if i < args.iterations:
            time.sleep(args.sleep_seconds)

    summary = {
        "ts": utc_now_iso(),
        "kind": "step48_periodic_brain_loop_summary",
        "iterations": args.iterations,
        "sleep_seconds": args.sleep_seconds,
        "push_telegram_enabled": args.push_telegram,
        "overall_ok": True,
    }
    append_jsonl(LOG_PATH, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
