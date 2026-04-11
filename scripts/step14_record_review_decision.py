#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from datetime import datetime, UTC


ALLOWED_DECISIONS = {"approve", "reject", "hold"}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_latest_step13_summary(path: str) -> dict:
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
            if record.get("kind") == "step13_review_packets_summary":
                latest = record

    if latest is None:
        raise RuntimeError("No step13_review_packets_summary found in step13 log.")

    return latest


def find_packet(step13_summary: dict, packet_id: str) -> dict:
    packets = step13_summary.get("packets", {})
    for team_name, items in packets.items():
        for packet in items:
            if packet.get("packet_id") == packet_id:
                found = dict(packet)
                found["_team_key"] = team_name
                return found
    raise RuntimeError(f"Could not find packet_id: {packet_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--decision", required=True, choices=sorted(ALLOWED_DECISIONS))
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--risk-comment", required=True)
    parser.add_argument("--side", choices=["yes", "no"], default=None)
    parser.add_argument("--contracts", type=int, default=None)
    parser.add_argument("--max-price", default=None)
    return parser.parse_args()


def validate_for_approval(args: argparse.Namespace) -> None:
    if args.decision != "approve":
        return

    missing = []
    if args.side is None:
        missing.append("--side")
    if args.contracts is None:
        missing.append("--contracts")
    if args.max_price is None:
        missing.append("--max-price")

    if missing:
        raise RuntimeError(
            "Approve decisions require order details. Missing: " + ", ".join(missing)
        )


def build_decision_record(packet: dict, args: argparse.Namespace) -> dict:
    approved = args.decision == "approve"

    draft_order = dict(packet.get("draft_order_template", {}))
    if approved:
        draft_order["side"] = args.side
        draft_order["contracts"] = args.contracts
        draft_order["max_price_dollars"] = args.max_price

    return {
        "decision_id": str(uuid.uuid4()),
        "source_packet_id": packet.get("packet_id"),
        "source_proposal_id": packet.get("source_proposal_id"),
        "team": packet.get("team"),
        "review_stage": packet.get("review_stage"),
        "required_reviewer": packet.get("required_reviewer"),
        "reviewer": args.reviewer,
        "decision": args.decision,
        "decision_state": {
            "approve": "approved",
            "reject": "rejected",
            "hold": "held",
        }[args.decision],
        "rationale": args.rationale,
        "risk_comment": args.risk_comment,
        "proposal_snapshot": packet.get("proposal_snapshot"),
        "order_candidate": draft_order,
        "executor_ready": approved,
        "human_required_now": packet.get("review_requirements", {}).get("human_required_now", False),
        "notify_now": packet.get("notification_policy", {}).get("notify_on_decision", False),
        "next_stage": (
            packet.get("next_stage_if_approved") if approved else "stopped_before_executor"
        ),
    }


def main() -> None:
    args = parse_args()
    validate_for_approval(args)

    run_id = str(uuid.uuid4())
    log_path = "logs/step14/review_decisions.jsonl"

    step13_summary = load_latest_step13_summary("logs/step13/review_packets.jsonl")
    packet = find_packet(step13_summary, args.packet_id)

    record = build_decision_record(packet, args)

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step14_review_decision_record",
        "checks": {
            "step13_summary_load": {
                "ok": True,
                "details": {
                    "source_run_id": step13_summary.get("run_id"),
                },
            },
            "packet_lookup": {
                "ok": True,
                "details": {
                    "packet_id": packet.get("packet_id"),
                    "team": packet.get("team"),
                    "required_reviewer": packet.get("required_reviewer"),
                },
            },
            "decision_build": {
                "ok": True,
                "details": {
                    "decision": record["decision"],
                    "executor_ready": record["executor_ready"],
                    "next_stage": record["next_stage"],
                    "notify_now": record["notify_now"],
                },
            },
        },
        "decision_record": record,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

