#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, UTC
from dotenv import load_dotenv

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.kalshi_agentic.client_factory import make_write_client
from app.kalshi_agentic.config import load_settings


REQUIRED_ACK = "I_UNDERSTAND_LIVE_TRADING_IS_ENABLED"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_latest_step17_summary(path: str) -> dict:
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
            if record.get("kind") == "step17_order_submission_candidates_summary":
                latest = record

    if latest is None:
        raise RuntimeError("No step17_order_submission_candidates_summary found in step17 log.")

    return latest


def find_candidate(step17_summary: dict, candidate_id: str) -> dict:
    items = step17_summary.get("order_submission_candidates", [])
    for item in items:
        if item.get("submission_candidate_id") == candidate_id:
            return dict(item)
    raise RuntimeError(f"Could not find submission_candidate_id: {candidate_id}")


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


def format_price_dollars(value: str | float) -> str:
    return f"{float(value):.4f}"


def build_create_order_payload(candidate: dict) -> dict:
    order = candidate["order_payload"]

    payload = {
        "ticker": order["market_ticker"],
        "action": order["action"],
        "side": order["side"],
        "count": order["contracts"],
        "type": "limit",
        "client_order_id": str(uuid.uuid4()),
    }

    max_price = format_price_dollars(order["max_price_dollars"])
    if order["side"] == "yes":
        payload["yes_price_dollars"] = max_price
    elif order["side"] == "no":
        payload["no_price_dollars"] = max_price
    else:
        raise RuntimeError("Order side must be yes or no.")

    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", required=True)
    return parser.parse_args()


def main() -> None:
    load_dotenv()

    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step20/live_order_path.jsonl"

    step17_summary = load_latest_step17_summary("logs/step17/order_submission_candidates.jsonl")
    candidate = find_candidate(step17_summary, args.candidate_id)
    gate = gate_state()

    payload = build_create_order_payload(candidate)

    result = {
        "request_sent": False,
        "request_ok": False,
        "status_code": None,
        "response_body": None,
        "error_type": None,
        "client_profile_used": "write",
        "client_api_key_id": None,
    }

    client = None
    client_meta = None

    try:
        if gate["allowed"]:
            _ = load_settings()
            client, client_meta = make_write_client()
            result["client_api_key_id"] = client_meta["api_key_id"]

            try:
                response = client.auth_post("/trade-api/v2/portfolio/orders", payload)
                result["request_sent"] = True
                result["request_ok"] = True
                result["status_code"] = response.status_code
                try:
                    result["response_body"] = response.json()
                except Exception:
                    result["response_body"] = response.text
            except requests.HTTPError as e:
                response = e.response
                result["request_sent"] = response is not None
                result["request_ok"] = False
                result["status_code"] = response.status_code if response is not None else None
                result["error_type"] = "http_error"
                if response is not None:
                    try:
                        result["response_body"] = response.json()
                    except Exception:
                        result["response_body"] = response.text
            except Exception as e:
                result["request_sent"] = False
                result["request_ok"] = False
                result["error_type"] = type(e).__name__
                result["response_body"] = str(e)

        summary = {
            "ts": utc_now_iso(),
            "run_id": run_id,
            "kind": "step24_live_order_path_factory_summary",
            "checks": {
                "step17_candidate_load": {
                    "ok": True,
                    "details": {
                        "source_run_id": step17_summary.get("run_id"),
                        "submission_candidate_id": candidate.get("submission_candidate_id"),
                        "market_ticker": candidate.get("market_ticker"),
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
                "request_attempt": {
                    "ok": True,
                    "details": result,
                },
            },
            "candidate_snapshot": {
                "team": candidate.get("team"),
                "market_ticker": candidate.get("market_ticker"),
                "event_ticker": candidate.get("event_ticker"),
                "title": candidate.get("title"),
                "order_payload_internal": candidate.get("order_payload"),
                "create_order_payload": payload,
            },
            "overall_ok": True,
        }

        append_jsonl(log_path, summary)
        print(json.dumps(summary, indent=2))

    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()
