#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, UTC

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.kalshi_agentic.client_factory import make_read_client, make_write_client


REQUIRED_ACK = "I_UNDERSTAND_LIVE_TRADING_IS_ENABLED"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_latest_record(path: str, kind: str) -> dict:
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
            if record.get("kind") == kind:
                latest = record

    if latest is None:
        raise RuntimeError(f"No {kind} found in {path}.")

    return latest


def load_latest_step17_summary(path: str) -> dict:
    return load_latest_record(path, "step17_order_submission_candidates_summary")


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


def run_market_preflight(candidate: dict) -> dict:
    read_client = None
    read_meta = None
    try:
        read_client, read_meta = make_read_client()
        ticker = candidate["market_ticker"]
        response = read_client.public_get(f"/trade-api/v2/markets/{ticker}")
        payload = response.json()
        market = payload.get("market", payload)

        returned_ticker = market.get("ticker")
        status = market.get("status")

        ok = (
            response.status_code == 200
            and returned_ticker == ticker
            and status == "active"
        )

        return {
            "ok": ok,
            "status_code": response.status_code,
            "requested_ticker": ticker,
            "returned_ticker": returned_ticker,
            "market_status": status,
            "client_profile_used": "read",
            "client_api_key_id": read_meta["api_key_id"],
        }
    except requests.HTTPError as e:
        response = e.response
        response_body = None
        if response is not None:
            try:
                response_body = response.json()
            except Exception:
                response_body = response.text
        return {
            "ok": False,
            "status_code": response.status_code if response is not None else None,
            "requested_ticker": candidate["market_ticker"],
            "returned_ticker": None,
            "market_status": None,
            "client_profile_used": "read",
            "client_api_key_id": read_meta["api_key_id"] if read_meta else None,
            "error_type": "http_error",
            "response_body": response_body,
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "requested_ticker": candidate["market_ticker"],
            "returned_ticker": None,
            "market_status": None,
            "client_profile_used": "read",
            "client_api_key_id": read_meta["api_key_id"] if read_meta else None,
            "error_type": type(e).__name__,
            "response_body": str(e),
        }
    finally:
        if read_client is not None:
            read_client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--confirm-live-send", action="store_true")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step26/guarded_live_order_path.jsonl"

    step17_summary = load_latest_step17_summary("logs/step17/order_submission_candidates.jsonl")
    candidate = find_candidate(step17_summary, args.candidate_id)

    step25_summary = load_latest_record(
        "logs/step25/risk_guard.jsonl",
        "step25_risk_guard_summary",
    )
    risk_details = step25_summary.get("checks", {}).get("risk_evaluation", {}).get("details", {})
    risk_candidate_details = step25_summary.get("checks", {}).get("candidate_load", {}).get("details", {})
    risk_matches_candidate = risk_candidate_details.get("submission_candidate_id") == args.candidate_id
    risk_guard_allowed = bool(risk_details.get("risk_guard_allowed")) and risk_matches_candidate

    step36_summary = load_latest_record(
        "logs/step36/candidate_freshness_guard.jsonl",
        "step36_candidate_freshness_guard_summary",
    )
    freshness_details = step36_summary.get("checks", {}).get("freshness_evaluation", {}).get("details", {})
    freshness_candidate_details = step36_summary.get("checks", {}).get("candidate_load", {}).get("details", {})
    freshness_matches_candidate = freshness_candidate_details.get("submission_candidate_id") == args.candidate_id
    freshness_guard_allowed = bool(freshness_details.get("freshness_guard_allowed")) and freshness_matches_candidate

    gate = gate_state()
    payload = build_create_order_payload(candidate)
    preflight = run_market_preflight(candidate)

    result = {
        "request_sent": False,
        "request_ok": False,
        "status_code": None,
        "response_body": None,
        "error_type": None,
        "client_profile_used": "write",
        "client_api_key_id": None,
        "blocked_by": [],
        "confirm_live_send": args.confirm_live_send,
    }

    client = None

    try:
        if not risk_guard_allowed:
            result["blocked_by"].append("risk_guard")

        if not freshness_guard_allowed:
            result["blocked_by"].append("freshness_guard")

        if not gate["allowed"]:
            result["blocked_by"].append("execution_gate")

        if not preflight["ok"]:
            result["blocked_by"].append("market_preflight")

        if not args.confirm_live_send:
            result["blocked_by"].append("confirm_live_send")

        can_send = (
            risk_guard_allowed
            and freshness_guard_allowed
            and gate["allowed"]
            and preflight["ok"]
            and args.confirm_live_send
        )

        if can_send:
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
            "kind": "step37_guarded_live_order_path_fresh_summary",
            "checks": {
                "step17_candidate_load": {
                    "ok": True,
                    "details": {
                        "source_run_id": step17_summary.get("run_id"),
                        "submission_candidate_id": candidate.get("submission_candidate_id"),
                        "market_ticker": candidate.get("market_ticker"),
                    },
                },
                "step25_risk_guard": {
                    "ok": True,
                    "details": {
                        "source_run_id": step25_summary.get("run_id"),
                        "risk_candidate_id": risk_candidate_details.get("submission_candidate_id"),
                        "requested_candidate_id": args.candidate_id,
                        "risk_matches_candidate": risk_matches_candidate,
                        "risk_guard_allowed": risk_guard_allowed,
                    },
                },
                "step36_freshness_guard": {
                    "ok": True,
                    "details": {
                        "source_run_id": step36_summary.get("run_id"),
                        "freshness_candidate_id": freshness_candidate_details.get("submission_candidate_id"),
                        "requested_candidate_id": args.candidate_id,
                        "freshness_matches_candidate": freshness_matches_candidate,
                        "freshness_guard_allowed": freshness_guard_allowed,
                        "age_minutes": freshness_details.get("age_minutes"),
                        "market_snapshot": freshness_details.get("market_snapshot"),
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
                "market_preflight": {
                    "ok": True,
                    "details": preflight,
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