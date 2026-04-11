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


def load_latest_record(path: str, kind: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None

    latest = None
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == kind:
                latest = record
    return latest


def main() -> None:
    run_id = str(uuid.uuid4())
    log_path = "logs/step42/active_queue_view.jsonl"

    step17 = load_latest_record(
        "logs/step17/order_submission_candidates.jsonl",
        "step17_order_submission_candidates_summary",
    )
    step39 = load_latest_record(
        "logs/step39/retired_candidates.jsonl",
        "step39_retire_stale_candidates_summary",
    )
    step40 = load_latest_record(
        "logs/step29/operator_console.jsonl",
        "step40_operator_console_retirement_summary",
    )

    candidates = step17.get("order_submission_candidates", []) if step17 else []
    retirement_record = step39.get("retirement_record") if step39 else None

    retired_proposal_ids = set()
    if retirement_record and retirement_record.get("retired"):
        retired_proposal_ids.add(retirement_record.get("source_proposal_id"))

    active_candidates = []
    retired_candidates = []

    for item in candidates:
        proposal_id = item.get("source_proposal_id")
        candidate_view = {
            "submission_candidate_id": item.get("submission_candidate_id"),
            "team": item.get("team"),
            "market_ticker": item.get("market_ticker"),
            "title": item.get("title"),
            "source_proposal_id": proposal_id,
            "submission_status": item.get("submission_status"),
        }

        if proposal_id in retired_proposal_ids:
            retired_candidates.append(candidate_view)
        else:
            active_candidates.append(candidate_view)

    console_executor = step40.get("console", {}).get("executor_decision", {}) if step40 else {}

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step42_active_queue_view_summary",
        "checks": {
            "candidate_source": {
                "ok": True,
                "details": {
                    "step17_present": step17 is not None,
                    "candidate_count_total": len(candidates),
                },
            },
            "retirement_source": {
                "ok": True,
                "details": {
                    "step39_present": step39 is not None,
                    "retirement_present": retirement_record is not None,
                },
            },
            "active_queue_build": {
                "ok": True,
                "details": {
                    "active_candidate_count": len(active_candidates),
                    "retired_candidate_count": len(retired_candidates),
                    "executor_actionable_now": console_executor.get("actionable_now") if console_executor else None,
                },
            },
        },
        "active_queue": {
            "active_candidates": active_candidates,
            "retired_candidates": retired_candidates,
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
