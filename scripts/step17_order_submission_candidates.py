#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from datetime import datetime, UTC


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_step16_records(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Could not find log file: {path}")

    records = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == "step16_executor_decision_record":
                records.append(record)

    if not records:
        raise RuntimeError("No step16_executor_decision_record entries found in step16 log.")

    return records


def latest_decision_by_intake(records: list[dict]) -> dict[str, dict]:
    latest = {}
    for record in records:
        decision = record.get("executor_decision", {})
        intake_id = decision.get("source_executor_intake_id")
        if intake_id:
            latest[intake_id] = decision
    return latest


def validate_order(order: dict) -> dict:
    errors = []

    if not order.get("market_ticker"):
        errors.append("missing market_ticker")
    if order.get("side") not in {"yes", "no"}:
        errors.append("side must be yes or no")
    if order.get("action") != "buy":
        errors.append("action must be buy")
    if not isinstance(order.get("contracts"), int) or order.get("contracts") <= 0:
        errors.append("contracts must be a positive integer")

    max_price_raw = order.get("max_price_dollars")
    try:
        max_price = float(max_price_raw)
        if not (0.0 < max_price <= 1.0):
            errors.append("max_price_dollars must be in (0, 1]")
    except (TypeError, ValueError):
        errors.append("max_price_dollars must be numeric")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
    }


def make_submission_candidate(decision: dict) -> dict:
    order = dict(decision.get("proposed_order", {}))
    validation = validate_order(order)

    return {
        "submission_candidate_id": str(uuid.uuid4()),
        "source_executor_decision_id": decision.get("executor_decision_id"),
        "source_executor_intake_id": decision.get("source_executor_intake_id"),
        "source_decision_id": decision.get("source_decision_id"),
        "source_packet_id": decision.get("source_packet_id"),
        "source_proposal_id": decision.get("source_proposal_id"),
        "team": decision.get("team"),
        "market_ticker": decision.get("market_ticker"),
        "event_ticker": decision.get("event_ticker"),
        "title": decision.get("title"),
        "family": decision.get("family"),
        "horizon": decision.get("horizon"),
        "order_payload": {
            "market_ticker": order.get("market_ticker"),
            "side": order.get("side"),
            "action": order.get("action"),
            "contracts": order.get("contracts"),
            "max_price_dollars": order.get("max_price_dollars"),
            "expiration_policy": order.get("expiration_policy"),
            "time_in_force": order.get("time_in_force"),
        },
        "governance_snapshot": {
            "team": decision.get("team"),
            "reviewer": decision.get("reviewer"),
            "decision": decision.get("decision"),
            "decision_state": decision.get("decision_state"),
            "executor_reason": decision.get("executor_reason"),
            "sanity_check_note": decision.get("sanity_check_note"),
        },
        "submission_checks": validation,
        "submission_status": "dry_run_ready" if validation["ok"] else "invalid_candidate",
        "actual_submission_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-items", type=int, default=10)
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step17/order_submission_candidates.jsonl"

    step16_records = load_step16_records("logs/step16/executor_decisions.jsonl")
    latest = latest_decision_by_intake(step16_records)

    approved = [
        d for d in latest.values()
        if d.get("decision") == "approve" and d.get("ready_for_order_submission") is True
    ]

    approved.sort(
        key=lambda d: (
            d.get("team", ""),
            d.get("market_ticker", ""),
        )
    )

    approved = approved[: args.max_items]
    candidates = [make_submission_candidate(d) for d in approved]

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step17_order_submission_candidates_summary",
        "checks": {
            "step16_decision_load": {
                "ok": True,
                "details": {
                    "decision_record_count": len(step16_records),
                    "latest_intake_count": len(latest),
                },
            },
            "candidate_build": {
                "ok": True,
                "details": {
                    "approved_count": len(approved),
                    "candidate_count": len(candidates),
                    "valid_candidate_count": sum(
                        1 for c in candidates if c.get("submission_checks", {}).get("ok") is True
                    ),
                    "max_items": args.max_items,
                },
            },
        },
        "order_submission_candidates": candidates,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
