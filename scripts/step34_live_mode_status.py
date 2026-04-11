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


def main() -> None:
    load_dotenv()

    run_id = str(uuid.uuid4())
    log_path = "logs/step34/live_mode_status.jsonl"

    execution_mode = os.getenv("EXECUTION_MODE", "").strip().lower() or "dry_run"
    live_enabled = os.getenv("LIVE_TRADING_ENABLED", "").strip().lower() == "true"
    ack = os.getenv("LIVE_TRADING_ACK", "").strip()

    checks = {
        "execution_mode_is_live": execution_mode == "live",
        "live_flag_enabled": live_enabled,
        "live_ack_matches": ack == REQUIRED_ACK,
    }

    armed = all(checks.values())

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step34_live_mode_status_summary",
        "checks": {
            "env_state": {
                "ok": True,
                "details": {
                    "EXECUTION_MODE": execution_mode,
                    "LIVE_TRADING_ENABLED": "true" if live_enabled else "false",
                    "LIVE_TRADING_ACK_present": bool(ack),
                    "checks": checks,
                    "live_mode_fully_armed": armed,
                },
            },
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
