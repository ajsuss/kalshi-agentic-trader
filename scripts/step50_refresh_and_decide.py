#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone


LOG_PATH = Path("logs/step50/refresh_and_decide.jsonl")
STEP17_LOG = Path("logs/step17/order_submission_candidates.jsonl")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def run_script(args: list[str]) -> dict:
    completed = subprocess.run(
        [sys.executable] + args,
        capture_output=True,
        text=True,
    )
    return {
        "argv": args,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "ok": completed.returncode == 0,
    }


def load_latest_step17_candidate_id() -> str | None:
    if not STEP17_LOG.exists():
        return None

    latest = None
    with STEP17_LOG.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == "step17_order_submission_candidates_summary":
                latest = record

    if latest is None:
        return None

    candidates = latest.get("order_submission_candidates", [])
    if not candidates:
        return None

    return candidates[0].get("submission_candidate_id")


def main() -> None:
    run_id = str(uuid.uuid4())

    runs = {
        "step38_refresh_review_queue": run_script(["scripts/step38_refresh_review_queue.py"]),
        "step14_record_review_decision": run_script(["scripts/step14_record_review_decision.py"]),
        "step15_executor_intake": run_script(["scripts/step15_executor_intake.py"]),
        "step16_executor_decision": run_script(["scripts/step16_executor_decision.py"]),
        "step17_order_submission_candidates": run_script(["scripts/step17_order_submission_candidates.py"]),
        "step18_simulated_submission": run_script(["scripts/step18_simulated_submission.py"]),
        "step19_execution_gate": run_script(["scripts/step19_execution_gate.py"]),
    }

    candidate_id = load_latest_step17_candidate_id()
    if candidate_id:
        runs["step36_candidate_freshness_guard"] = run_script(
            ["scripts/step36_candidate_freshness_guard.py", "--candidate-id", candidate_id]
        )
        runs["step39_retire_stale_candidates"] = run_script(["scripts/step39_retire_stale_candidates.py"])
    else:
        runs["step36_candidate_freshness_guard"] = {
            "ok": False,
            "argv": ["scripts/step36_candidate_freshness_guard.py", "--candidate-id", "<missing>"],
            "returncode": None,
            "stdout": "",
            "stderr": "No candidate_id found in latest step17 summary.",
        }
        runs["step39_retire_stale_candidates"] = {
            "ok": False,
            "argv": ["scripts/step39_retire_stale_candidates.py"],
            "returncode": None,
            "stdout": "",
            "stderr": "Skipped because no candidate_id was available for step36.",
        }

    runs["step42_active_queue_view"] = run_script(["scripts/step42_active_queue_view.py"])
    runs["step46_control_plane_digest"] = run_script(["scripts/step46_control_plane_digest.py"])
    runs["step47_deliberation_cycle"] = run_script(["scripts/step47_deliberation_cycle.py"])
    runs["step49_performance_snapshot"] = run_script(["scripts/step49_performance_snapshot.py"])

    all_ok = all(item.get("ok") for item in runs.values())

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step50_refresh_and_decide_summary",
        "candidate_id_used": candidate_id,
        "runs": runs,
        "overall_ok": all_ok,
    }

    append_jsonl(LOG_PATH, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
