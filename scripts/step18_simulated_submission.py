#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from datetime import datetime, UTC


ALLOWED_OUTCOMES = {"simulated_submitted", "simulated_rejected"}


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--outcome",
        required=True,
        choices=sorted(ALLOWED_OUTCOMES),
    )
    parser.add_argument("--reason", required=True)
    return parser.parse_args()


def build_simulated_submission(candidate: dict, args: argparse.Namespace) -> dict:
    submitted = args.outcome == "simulated_submitted"

    return {
        "simulated_submission_id": str(uuid.uuid4()),
        "source_submission_candidate_id": candidate.get("submission_candidate_id"),
        "source_executor_decision_id": candidate.get("source_executor_decision_id"),
        "source_executor_intake_id": candidate.get("source_executor_intake_id"),
        "source_decision_id": candidate.get("source_decision_id"),
        "source_packet_id": candidate.get("source_packet_id"),
        "source_proposal_id": candidate.get("source_proposal_id"),
        "team": candidate.get("team"),
        "market_ticker": candidate.get("market_ticker"),
        "event_ticker": candidate.get("event_ticker"),
        "title": candidate.get("title"),
        "family": candidate.get("family"),
        "horizon": candidate.get("horizon"),
        "order_payload": candidate.get("order_payload"),
        "governance_snapshot": candidate.get("governance_snapshot"),
        "submission_checks": candidate.get("submission_checks"),
        "simulated_outcome": args.outcome,
        "reason": args.reason,
        "submission_status": (
            "simulated_submission_recorded" if submitted else "simulated_submission_blocked"
        ),
        "actual_submission_performed": False,
    }


def main() -> None:
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step18/simulated_submission.jsonl"

    step17_summary = load_latest_step17_summary("logs/step17/order_submission_candidates.jsonl")
    candidate = find_candidate(step17_summary, args.candidate_id)

    simulated = build_simulated_submission(candidate, args)

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step18_simulated_submission_record",
        "checks": {
            "step17_summary_load": {
                "ok": True,
                "details": {
                    "source_run_id": step17_summary.get("run_id"),
                },
            },
            "candidate_lookup": {
                "ok": True,
                "details": {
                    "submission_candidate_id": candidate.get("submission_candidate_id"),
                    "market_ticker": candidate.get("market_ticker"),
                    "team": candidate.get("team"),
                },
            },
            "simulation_record": {
                "ok": True,
                "details": {
                    "simulated_outcome": simulated["simulated_outcome"],
                    "submission_status": simulated["submission_status"],
                    "actual_submission_performed": simulated["actual_submission_performed"],
                },
            },
        },
        "simulated_submission": simulated,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
