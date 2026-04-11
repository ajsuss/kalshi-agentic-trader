#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from datetime import datetime, UTC

import requests
from dotenv import load_dotenv


EVENT_SOURCES = {
    "step14": {
        "path": "logs/step14/review_decisions.jsonl",
        "kind": "step14_review_decision_record",
    },
    "step16": {
        "path": "logs/step16/executor_decisions.jsonl",
        "kind": "step16_executor_decision_record",
    },
    "step18": {
        "path": "logs/step18/simulated_submission.jsonl",
        "kind": "step18_simulated_submission_record",
    },
    "step26": {
        "path": "logs/step26/guarded_live_order_path.jsonl",
        "kind": "step37_guarded_live_order_path_fresh_summary",
    },
}


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


def load_latest_record(event_name: str) -> dict:
    meta = EVENT_SOURCES[event_name]
    path = Path(meta["path"])
    if not path.exists():
        raise FileNotFoundError(f"Could not find log file: {path}")

    latest = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == meta["kind"]:
                latest = record

    if latest is None:
        raise RuntimeError(f"No matching record found for {event_name}")

    return latest


def format_step14(record: dict) -> str:
    d = record["decision_record"]
    p = d["proposal_snapshot"]
    return "\n".join(
        [
            "REVIEW DECISION",
            f"Team: {d['team']}",
            f"Reviewer: {d['reviewer']}",
            f"Decision: {d['decision_state']}",
            f"Market: {p['title']}",
            f"Ticker: {p['market_ticker']}",
            f"Next: {d['next_stage']}",
            f"Reason: {d['rationale']}",
        ]
    )


def format_step16(record: dict) -> str:
    d = record["executor_decision"]
    o = d["proposed_order"]
    return "\n".join(
        [
            "EXECUTOR DECISION",
            f"Team: {d['team']}",
            f"Decision: {d['decision_state']}",
            f"Market: {d['title']}",
            f"Ticker: {d['market_ticker']}",
            f"Order: {o['action']} {o['side']} x{o['contracts']} @ {o['max_price_dollars']}",
            f"Next: {d['next_stage']}",
            f"Reason: {d['executor_reason']}",
        ]
    )


def format_step18(record: dict) -> str:
    s = record["simulated_submission"]
    o = s["order_payload"]
    return "\n".join(
        [
            "SIMULATED SUBMISSION",
            f"Team: {s['team']}",
            f"Outcome: {s['simulated_outcome']}",
            f"Market: {s['title']}",
            f"Ticker: {s['market_ticker']}",
            f"Order: {o['action']} {o['side']} x{o['contracts']} @ {o['max_price_dollars']}",
            f"Status: {s['submission_status']}",
            f"Reason: {s['reason']}",
        ]
    )


def format_step26(record: dict) -> str:
    c = record["candidate_snapshot"]
    d = record["checks"]["request_attempt"]["details"]
    o = c["order_payload_internal"]
    blocked_by = ", ".join(d.get("blocked_by", [])) or "none"
    return "\n".join(
        [
            "LIVE PATH ATTEMPT",
            f"Team: {c['team']}",
            f"Market: {c['title']}",
            f"Ticker: {c['market_ticker']}",
            f"Order: {o['action']} {o['side']} x{o['contracts']} @ {o['max_price_dollars']}",
            f"Request sent: {d['request_sent']}",
            f"Blocked by: {blocked_by}",
        ]
    )


def build_message(event_name: str, record: dict) -> str:
    if event_name == "step14":
        return format_step14(record)
    if event_name == "step16":
        return format_step16(record)
    if event_name == "step18":
        return format_step18(record)
    if event_name == "step26":
        return format_step26(record)
    raise RuntimeError(f"Unknown event source: {event_name}")


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
    parser.add_argument("--event", required=True, choices=sorted(EVENT_SOURCES.keys()))
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step27/event_notifier.jsonl"

    bot_token = read_secret_from_env_or_file("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_FILE")
    chat_id = read_secret_from_env_or_file("TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_ID_FILE")

    record = load_latest_record(args.event)
    message = build_message(args.event, record)

    response = send_telegram_message(bot_token, chat_id, message)
    response_payload = response.json()

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step27_event_notifier_summary",
        "checks": {
            "record_load": {
                "ok": True,
                "details": {
                    "event": args.event,
                    "source_kind": record.get("kind"),
                },
            },
            "telegram_send": {
                "ok": True,
                "details": {
                    "status_code": response.status_code,
                    "telegram_ok": response_payload.get("ok"),
                },
            },
        },
        "notification_preview": {
            "event": args.event,
            "message": message,
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
