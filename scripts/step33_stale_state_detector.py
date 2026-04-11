#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path
from datetime import datetime, UTC

import requests
from dotenv import load_dotenv


SOURCE_PATH = "logs/step31/multi_event_loop.jsonl"
SOURCE_KIND = "step31_multi_event_loop_summary"
DEDUP_PATH = "logs/step33/stale_alert_keys.jsonl"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_secret_from_env_or_file(env_name: str, file_env_name: str) -> str:
    direct = os.getenv(env_name, "").strip()
    if direct:
        return direct

    file_path = os.getenv(file_env_name, "").strip()
    if file_path and Path(file_path).exists():
        return Path(file_path).read_text(encoding="utf-8").strip()

    raise RuntimeError(f"Missing {env_name} or {file_env_name}")


def load_latest_summary() -> dict:
    p = Path(SOURCE_PATH)
    if not p.exists():
        raise FileNotFoundError(f"Could not find log file: {SOURCE_PATH}")

    latest = None
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == SOURCE_KIND:
                latest = record

    if latest is None:
        raise RuntimeError("No step31_multi_event_loop_summary found.")

    return latest


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load_seen_keys(path: str) -> set[str]:
    p = Path(path)
    seen: set[str] = set()
    if not p.exists():
        return seen

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            key = record.get("dedupe_key")
            if key:
                seen.add(key)
    return seen


def record_seen_key(path: str, key: str, message: str) -> None:
    append_jsonl(
        path,
        {
            "ts": utc_now_iso(),
            "dedupe_key": key,
            "message_preview": message,
        },
    )


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> requests.Response:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()
    return response


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-seconds", type=float, default=180.0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step33/stale_state_detector.jsonl"

    latest = load_latest_summary()
    latest_ts = parse_iso(latest["ts"])
    age_seconds = (datetime.now(UTC) - latest_ts).total_seconds()
    stale = age_seconds > args.max_age_seconds

    message = "\n".join(
        [
            "STALE LOOP ALERT",
            f"Latest loop summary ts: {latest['ts']}",
            f"Age seconds: {round(age_seconds, 2)}",
            f"Threshold seconds: {args.max_age_seconds}",
            f"Run ID: {latest['run_id']}",
        ]
    )

    dedupe_key = hashlib.sha256(message.encode("utf-8")).hexdigest()
    seen = load_seen_keys(DEDUP_PATH)

    skipped_duplicate = False
    telegram_status = None
    telegram_ok = None

    if stale:
        if dedupe_key in seen and not args.force:
            skipped_duplicate = True
        else:
            bot_token = read_secret_from_env_or_file("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_FILE")
            chat_id = read_secret_from_env_or_file("TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_ID_FILE")
            response = send_telegram_message(bot_token, chat_id, message)
            payload = response.json()
            telegram_status = response.status_code
            telegram_ok = payload.get("ok")
            record_seen_key(DEDUP_PATH, dedupe_key, message)

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step33_stale_state_detector_summary",
        "checks": {
            "latest_loop_summary": {
                "ok": True,
                "details": {
                    "source_run_id": latest.get("run_id"),
                    "latest_ts": latest.get("ts"),
                    "age_seconds": round(age_seconds, 4),
                    "max_age_seconds": args.max_age_seconds,
                    "stale": stale,
                },
            },
            "notification": {
                "ok": True,
                "details": {
                    "dedupe_key": dedupe_key,
                    "already_seen": dedupe_key in seen,
                    "force": args.force,
                    "skipped_duplicate": skipped_duplicate,
                    "telegram_status": telegram_status,
                    "telegram_ok": telegram_ok,
                },
            },
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
