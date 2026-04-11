#!/usr/bin/env python3
from __future__ import annotations

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
        raise RuntimeError(f"No {kind} found in {path}")

    return latest


def main() -> None:
    run_id = str(uuid.uuid4())
    log_path = "logs/step39/retired_candidates.jsonl"

    step16 = load_latest_record(
        "logs/step16/executor_decisions.jsonl",
        "step16_executor_decision_record",
    )
    step36 = load_latest_record(
        "logs/step36/candidate_freshness_guard.jsonl",
        "step36_candidate_freshness_guard_summary",
    )

    exec_decision = step16["executor_decision"]
    freshness = step36["checks"]["freshness_evaluation"]["details"]
    freshness_candidate = step36["checks"]["candidate_load"]["details"]

    proposal_matches = (
        exec_decision.get("source_proposal_id")
        == freshness_candidate.get("source_proposal_id")
    )

    should_retire = (
        proposal_matches
        and exec_decision.get("ready_for_order_submission") is True
        and freshness.get("freshness_guard_allowed") is False
    )

    retirement_record = None
    if should_retire:
        market_snapshot = freshness.get("market_snapshot", {})
        retirement_record = {
            "retirement_id": str(uuid.uuid4()),
            "retired_at": utc_now_iso(),
            "reason_code": "freshness_guard_failed",
            "team": exec_decision.get("team"),
            "source_executor_decision_id": exec_decision.get("executor_decision_id"),
            "source_proposal_id": exec_decision.get("source_proposal_id"),
            "market_ticker": exec_decision.get("market_ticker"),
            "title": exec_decision.get("title"),
            "previous_decision_state": exec_decision.get("decision_state"),
            "previous_next_stage": exec_decision.get("next_stage"),
            "age_minutes": freshness.get("age_minutes"),
            "market_status": market_snapshot.get("status"),
            "market_last_price_dollars": market_snapshot.get("last_price_dollars"),
            "freshness_guard_allowed": freshness.get("freshness_guard_allowed"),
            "retired": True,
        }

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step39_retire_stale_candidates_summary",
        "checks": {
            "step16_executor_decision": {
                "ok": True,
                "details": {
                    "source_run_id": step16.get("run_id"),
                    "source_proposal_id": exec_decision.get("source_proposal_id"),
                    "market_ticker": exec_decision.get("market_ticker"),
                    "ready_for_order_submission": exec_decision.get("ready_for_order_submission"),
                },
            },
            "step36_freshness_guard": {
                "ok": True,
                "details": {
                    "source_run_id": step36.get("run_id"),
                    "source_proposal_id": freshness_candidate.get("source_proposal_id"),
                    "freshness_guard_allowed": freshness.get("freshness_guard_allowed"),
                    "age_minutes": freshness.get("age_minutes"),
                    "market_status": freshness.get("market_snapshot", {}).get("status"),
                },
            },
            "retirement_decision": {
                "ok": True,
                "details": {
                    "proposal_matches": proposal_matches,
                    "should_retire": should_retire,
                    "retirement_created": retirement_record is not None,
                },
            },
        },
        "retirement_record": retirement_record,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
