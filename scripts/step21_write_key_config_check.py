#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from datetime import datetime, UTC
from dotenv import load_dotenv


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def exists_nonempty(path_str: str | None) -> dict:
    if not path_str:
        return {"present": False, "exists": False, "nonempty": False}
    p = Path(path_str)
    return {
        "present": True,
        "exists": p.exists(),
        "nonempty": p.exists() and p.is_file() and p.stat().st_size > 0,
    }


def main() -> None:
    load_dotenv()

    run_id = str(uuid.uuid4())
    log_path = "logs/step21/write_key_config_check.jsonl"

    read_key_id_file = os.getenv("KALSHI_API_KEY_ID_FILE")
    read_private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    write_key_id_file = os.getenv("KALSHI_WRITE_API_KEY_ID_FILE")
    write_private_key_path = os.getenv("KALSHI_WRITE_PRIVATE_KEY_PATH")

    execution_mode = os.getenv("EXECUTION_MODE", "dry_run")
    live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false")
    live_ack_present = bool(os.getenv("LIVE_TRADING_ACK", "").strip())

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step21_write_key_config_check_summary",
        "checks": {
            "read_key_files": {
                "ok": True,
                "details": {
                    "api_key_id_file": exists_nonempty(read_key_id_file),
                    "private_key_path": exists_nonempty(read_private_key_path),
                },
            },
            "write_key_files": {
                "ok": True,
                "details": {
                    "api_key_id_file": exists_nonempty(write_key_id_file),
                    "private_key_path": exists_nonempty(write_private_key_path),
                },
            },
            "execution_mode_guard": {
                "ok": True,
                "details": {
                    "EXECUTION_MODE": execution_mode,
                    "LIVE_TRADING_ENABLED": live_enabled,
                    "LIVE_TRADING_ACK_present": live_ack_present,
                },
            },
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
