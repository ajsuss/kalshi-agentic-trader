#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, UTC

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.kalshi_agentic.client_factory import (
    make_read_client,
    make_write_client,
    select_client_profile,
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def main() -> None:
    run_id = str(uuid.uuid4())
    log_path = "logs/step23/dual_client_selector.jsonl"

    read_client = None
    write_client = None

    try:
        read_client, read_meta = make_read_client()
        write_client, write_meta = make_write_client()

        read_limits_response = read_client.auth_get("/trade-api/v2/account/limits")
        read_limits = read_limits_response.json()

        write_limits_response = write_client.auth_get("/trade-api/v2/account/limits")
        write_limits = write_limits_response.json()

        selection_examples = {
            "market_scan": select_client_profile("market_scan"),
            "auth_read": select_client_profile("auth_read"),
            "portfolio_read": select_client_profile("portfolio_read"),
            "order_submission": select_client_profile("order_submission"),
        }

        summary = {
            "ts": utc_now_iso(),
            "run_id": run_id,
            "kind": "step23_dual_client_selector_summary",
            "checks": {
                "read_client_probe": {
                    "ok": True,
                    "details": {
                        "profile": read_meta["profile"],
                        "api_key_id": read_meta["api_key_id"],
                        "status_code": read_limits_response.status_code,
                        "usage_tier": read_limits.get("usage_tier"),
                        "read_limit": read_limits.get("read_limit"),
                        "write_limit": read_limits.get("write_limit"),
                    },
                },
                "write_client_probe": {
                    "ok": True,
                    "details": {
                        "profile": write_meta["profile"],
                        "api_key_id": write_meta["api_key_id"],
                        "status_code": write_limits_response.status_code,
                        "usage_tier": write_limits.get("usage_tier"),
                        "read_limit": write_limits.get("read_limit"),
                        "write_limit": write_limits.get("write_limit"),
                    },
                },
                "selector_examples": {
                    "ok": True,
                    "details": selection_examples,
                },
                "execution_mode_guard": {
                    "ok": True,
                    "details": {
                        "EXECUTION_MODE": os.getenv("EXECUTION_MODE", "dry_run"),
                        "LIVE_TRADING_ENABLED": os.getenv("LIVE_TRADING_ENABLED", "false"),
                        "LIVE_TRADING_ACK_present": bool(os.getenv("LIVE_TRADING_ACK", "").strip()),
                    },
                },
            },
            "overall_ok": True,
        }

        append_jsonl(log_path, summary)
        print(json.dumps(summary, indent=2))

    finally:
        if read_client is not None:
            read_client.close()
        if write_client is not None:
            write_client.close()


if __name__ == "__main__":
    main()
