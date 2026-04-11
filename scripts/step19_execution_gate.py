#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from datetime import datetime, UTC
from dotenv import load_dotenv

REQUIRED_ACK = "I_UNDERSTAND_LIVE_TRADING_IS_ENABLED"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_latest_step18_record(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Could not find log file: {path}")

    latest = None
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == "step18_simulated_submission_record":
                latest = record

    if latest is None:
        raise RuntimeError("No step18_simulated_submission_record found in step18 log.")

    return latest


def gate_state() -> dict:
    live_enabled = os.getenv("LIVE_TRADING_ENABLED", "").strip().lower() == "true"
    execute_mode = os.getenv("EXECUTION_MODE", "").strip().lower() or "dry_run"
    ack = os.getenv("LIVE_TRADING_ACK", "").strip()

    checks = {
        "execution_mode_is_live": execute_mode == "live",
        "live_flag_enabled": live_enabled,
        "live_ack_matches": ack == REQUIRED_ACK,
    }

    allowed = all(checks.values())

    return {
        "allowed": allowed,
        "checks": checks,
        "env_snapshot": {
            "EXECUTION_MODE": execute_mode,
            "LIVE_TRADING_ENABLED": "true" if live_enabled else "false",
            "LIVE_TRADING_ACK_present": bool(ack),
        },
    }


def main() -> None:
    load_dotenv()

    run_id = str(uuid.uuid4())
    log_path = "logs/step19/execution_gate.jsonl"

    step18_record = load_latest_step18_record("logs/step18/simulated_submission.jsonl")
    simulated = step18_record["simulated_submission"]
    gate = gate_state()

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step19_execution_gate_summary",
        "checks": {
            "step18_record_load": {
                "ok": True,
                "details": {
                    "source_run_id": step18_record.get("run_id"),
                    "submission_candidate_id": simulated.get("source_submission_candidate_id"),
                    "market_ticker": simulated.get("market_ticker"),
                },
            },
            "execution_gate": {
                "ok": True,
                "details": {
                    "allowed": gate["allowed"],
                    "checks": gate["checks"],
                    "env_snapshot": gate["env_snapshot"],
                },
            },
        },
        "candidate_snapshot": {
            "team": simulated.get("team"),
            "market_ticker": simulated.get("market_ticker"),
            "event_ticker": simulated.get("event_ticker"),
            "title": simulated.get("title"),
            "order_payload": simulated.get("order_payload"),
        },
        "gate_result": {
            "live_execution_allowed": gate["allowed"],
            "reason": (
                "All live execution checks passed."
                if gate["allowed"]
                else "Live execution blocked by safety gate."
            ),
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
