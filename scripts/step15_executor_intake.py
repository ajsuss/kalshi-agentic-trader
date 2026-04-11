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


def load_step14_decisions(path: str) -> list[dict]:
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
            if record.get("kind") == "step14_review_decision_record":
                records.append(record)

    if not records:
        raise RuntimeError("No step14_review_decision_record entries found in step14 log.")

    return records


def latest_decision_by_packet(records: list[dict]) -> dict[str, dict]:
    latest = {}
    for record in records:
        decision = record.get("decision_record", {})
        packet_id = decision.get("source_packet_id")
        if packet_id:
            latest[packet_id] = decision
    return latest


def make_executor_intake(decision: dict) -> dict:
    proposal = decision.get("proposal_snapshot", {})
    order = decision.get("order_candidate", {})

    justification = {
        "team": decision.get("team"),
        "review_stage": decision.get("review_stage"),
        "reviewer": decision.get("reviewer"),
        "decision": decision.get("decision"),
        "rationale": decision.get("rationale"),
        "risk_comment": decision.get("risk_comment"),
        "thesis_stub": proposal.get("thesis_stub"),
    }

    return {
        "executor_intake_id": str(uuid.uuid4()),
        "source_decision_id": decision.get("decision_id"),
        "source_packet_id": decision.get("source_packet_id"),
        "source_proposal_id": decision.get("source_proposal_id"),
        "team": decision.get("team"),
        "market_ticker": proposal.get("market_ticker"),
        "event_ticker": proposal.get("event_ticker"),
        "title": proposal.get("title"),
        "family": proposal.get("family"),
        "horizon": proposal.get("horizon"),
        "proposed_order": {
            "market_ticker": order.get("market_ticker"),
            "side": order.get("side"),
            "action": order.get("action"),
            "contracts": order.get("contracts"),
            "max_price_dollars": order.get("max_price_dollars"),
            "expiration_policy": order.get("expiration_policy"),
            "time_in_force": order.get("time_in_force"),
        },
        "justification_packet": justification,
        "executor_status": "pending_executor_review",
        "human_override_available": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-items", type=int, default=10)
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step15/executor_intake.jsonl"

    step14_records = load_step14_decisions("logs/step14/review_decisions.jsonl")
    latest = latest_decision_by_packet(step14_records)

    approved = [
        d for d in latest.values()
        if d.get("decision") == "approve" and d.get("executor_ready") is True
    ]

    approved.sort(
        key=lambda d: (
            d.get("team", ""),
            d.get("proposal_snapshot", {}).get("market_ticker", ""),
        )
    )

    approved = approved[: args.max_items]
    intake_packets = [make_executor_intake(d) for d in approved]

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step15_executor_intake_summary",
        "checks": {
            "step14_decision_load": {
                "ok": True,
                "details": {
                    "decision_record_count": len(step14_records),
                    "latest_packet_count": len(latest),
                },
            },
            "executor_intake_build": {
                "ok": True,
                "details": {
                    "approved_count": len(approved),
                    "intake_count": len(intake_packets),
                    "max_items": args.max_items,
                },
            },
        },
        "executor_intake_packets": intake_packets,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
