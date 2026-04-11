#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, UTC

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.kalshi_agentic.config import load_settings
from app.kalshi_agentic.kalshi_client import KalshiClient


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def file_state(path_str: str | None) -> dict:
    if not path_str:
        return {"present": False, "exists": False, "nonempty": False}
    p = Path(path_str)
    return {
        "present": True,
        "exists": p.exists(),
        "nonempty": p.exists() and p.is_file() and p.stat().st_size > 0,
    }


def read_text(path_str: str) -> str:
    return Path(path_str).read_text(encoding="utf-8").strip()


def main() -> None:
    load_dotenv()

    run_id = str(uuid.uuid4())
    log_path = "logs/step22/write_key_probe.jsonl"

    write_key_id_file = os.getenv("KALSHI_WRITE_API_KEY_ID_FILE")
    write_private_key_path = os.getenv("KALSHI_WRITE_PRIVATE_KEY_PATH")

    checks = {
        "write_key_files": {"ok": False, "details": {}},
        "account_limits_probe": {"ok": False, "details": {}},
        "api_keys_probe": {"ok": False, "details": {}},
        "matched_write_key": {"ok": False, "details": {}},
    }

    checks["write_key_files"]["details"] = {
        "api_key_id_file": file_state(write_key_id_file),
        "private_key_path": file_state(write_private_key_path),
    }

    files_ok = (
        checks["write_key_files"]["details"]["api_key_id_file"]["nonempty"]
        and checks["write_key_files"]["details"]["private_key_path"]["nonempty"]
    )
    checks["write_key_files"]["ok"] = files_ok

    if not files_ok:
        raise RuntimeError("Write key files are not present and nonempty.")

    write_api_key_id = read_text(write_key_id_file)

    original_key_id_file = os.getenv("KALSHI_API_KEY_ID_FILE")
    original_private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")

    os.environ["KALSHI_API_KEY_ID_FILE"] = write_key_id_file
    os.environ["KALSHI_PRIVATE_KEY_PATH"] = write_private_key_path

    client = None
    try:
        settings = load_settings()
        client = KalshiClient(settings=settings)

        limits_response = client.auth_get("/trade-api/v2/account/limits")
        limits_payload = limits_response.json()
        checks["account_limits_probe"]["ok"] = True
        checks["account_limits_probe"]["details"] = {
            "status_code": limits_response.status_code,
            "usage_tier": limits_payload.get("usage_tier"),
            "read_limit": limits_payload.get("read_limit"),
            "write_limit": limits_payload.get("write_limit"),
        }

        api_keys_response = client.auth_get("/trade-api/v2/api_keys")
        api_keys_payload = api_keys_response.json()
        api_keys = api_keys_payload.get("api_keys", [])
        checks["api_keys_probe"]["ok"] = True
        checks["api_keys_probe"]["details"] = {
            "status_code": api_keys_response.status_code,
            "api_key_count": len(api_keys) if isinstance(api_keys, list) else 0,
        }

        matched = None
        if isinstance(api_keys, list):
            for item in api_keys:
                if item.get("api_key_id") == write_api_key_id:
                    matched = item
                    break

        checks["matched_write_key"]["ok"] = matched is not None
        checks["matched_write_key"]["details"] = {
            "write_api_key_id": write_api_key_id,
            "matched": matched is not None,
            "matched_name": matched.get("name") if matched else None,
            "matched_scopes": matched.get("scopes") if matched else None,
        }

        summary = {
            "ts": utc_now_iso(),
            "run_id": run_id,
            "kind": "step22_write_key_probe_summary",
            "checks": checks,
            "overall_ok": all(section["ok"] for section in checks.values()),
        }

        append_jsonl(log_path, summary)
        print(json.dumps(summary, indent=2))

    finally:
        if client is not None:
            client.close()

        if original_key_id_file is not None:
            os.environ["KALSHI_API_KEY_ID_FILE"] = original_key_id_file
        else:
            os.environ.pop("KALSHI_API_KEY_ID_FILE", None)

        if original_private_key_path is not None:
            os.environ["KALSHI_PRIVATE_KEY_PATH"] = original_private_key_path
        else:
            os.environ.pop("KALSHI_PRIVATE_KEY_PATH", None)


if __name__ == "__main__":
    main()
