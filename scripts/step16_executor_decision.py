#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from datetime import datetime, UTC


ALLOWED_DECISIONS = {"approve", "reject", "flag_for_human"}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_latest_step15_summary(path: str) -> dict:
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
            if record.get("kind") == "step15_executor_intake_summary":
                latest = record

    if latest is None:
        raise RuntimeError("No step15_executor_intake_summary found in step15 log.")

    return latest


def find_intake_packet(step15_summary: dict, intake_id: str) -> dict:
    packets = step15_summary.get("executor_intake_packets", [])
    for packet in packets:
        if packet.get("executor_intake_id") == intake_id:
            return dict(packet)
    raise RuntimeError(f"Could not find executor_intake_id: {intake_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--decision", required=True, choices=sorted(ALLOWED_DECISIONS))
    parser.add_argument("--reason", required=True)
    parser.add_argument("--sanity-check-note", required=True)
    return parser.parse_args()


def build_executor_decision(intake: dict, args: argparse.Namespace) -> dict:
    approved = args.decision == "approve"
    flagged = args.decision == "flag_for_human"

    return {
        "executor_decision_id": str(uuid.uuid4()),
        "source_executor_intake_id": intake.get("executor_intake_id"),
        "source_decision_id": intake.get("source_decision_id"),
        "source_packet_id": intake.get("source_packet_id"),
        "source_proposal_id": intake.get("source_proposal_id"),
        "team": intake.get("team"),
        "reviewer": args.reviewer,
        "decision": args.decision,
        "decision_state": {
            "approve": "executor_approved",
            "reject": "executor_rejected",
            "flag_for_human": "executor_flagged_for_human",
        }[args.decision],
        "market_ticker": intake.get("market_ticker"),
        "event_ticker": intake.get("event_ticker"),
        "title": intake.get("title"),
        "family": intake.get("family"),
        "horizon": intake.get("horizon"),
        "proposed_order": intake.get("proposed_order"),
        "justification_packet": intake.get("justification_packet"),
        "executor_reason": args.reason,
        "sanity_check_note": args.sanity_check_note,
        "ready_for_order_submission": approved,
        "human_override_required": flagged,
        "notification_event_type": (
            "executor_flagged_for_human"
            if flagged
            else "executor_decision_recorded"
        ),
        "next_stage": (
            "order_submission_candidate"
            if approved
            else "human_override_queue"
            if flagged
            else "stopped_before_order_submission"
        ),
    }


def main() -> None:
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step16/executor_decisions.jsonl"

    step15_summary = load_latest_step15_summary("logs/step15/executor_intake.jsonl")
    intake = find_intake_packet(step15_summary, args.intake_id)

    decision = build_executor_decision(intake, args)

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step16_executor_decision_record",
        "checks": {
            "step15_summary_load": {
                "ok": True,
                "details": {
                    "source_run_id": step15_summary.get("run_id"),
                },
            },
            "intake_lookup": {
                "ok": True,
                "details": {
                    "executor_intake_id": intake.get("executor_intake_id"),
                    "team": intake.get("team"),
                    "market_ticker": intake.get("market_ticker"),
                },
            },
            "executor_decision_build": {
                "ok": True,
                "details": {
                    "decision": decision["decision"],
                    "ready_for_order_submission": decision["ready_for_order_submission"],
                    "human_override_required": decision["human_override_required"],
                    "next_stage": decision["next_stage"],
                },
            },
        },
        "executor_decision": decision,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
