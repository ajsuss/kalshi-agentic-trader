#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from datetime import datetime, timezone


STEP43_PATH = Path("scripts/step43_repo_state_snapshot.py")
STEP45_PATH = Path("scripts/step45_team_status_snapshot.py")
LOG_PATH = Path("logs/step47/deliberation_cycle.jsonl")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_script(path: Path) -> dict:
    completed = subprocess.run(
        ["python3", str(path)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{path.name} failed with code {completed.returncode}: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def build_cycle(control: dict, teams: dict) -> dict:
    active = control.get("active_candidate_count") or 0
    retired = control.get("retired_candidate_count") or 0
    actionable = bool(control.get("executor_actionable_now"))
    blocked_by = control.get("guarded_live_path_blocked_by", []) or []

    if active > 0 and actionable:
        recommendation = "review_for_guarded_submission"
        rationale = "Active queue has candidates and executor is actionable."
        priority = "high"
    elif active > 0 and not actionable:
        recommendation = "hold_until_unblocked"
        rationale = "Candidate exists but executor path is blocked."
        priority = "medium"
    else:
        recommendation = "refresh_candidate_generation"
        rationale = "No active queue candidates; continue monitoring and refresh cycle."
        priority = "low"

    next_trade = teams.get("next_best_trade", {})

    return {
        "ts": utc_now_iso(),
        "run_id": str(uuid.uuid4()),
        "kind": "step47_deliberation_cycle_summary",
        "inputs": {
            "control_source": control.get("state_source"),
            "active_candidate_count": active,
            "retired_candidate_count": retired,
            "executor_actionable_now": actionable,
            "blocked_by": blocked_by,
            "next_best_trade": next_trade,
        },
        "deliberation": {
            "team_votes": {
                "algorithms": recommendation,
                "information_media": recommendation,
                "deliberators": recommendation,
                "executor": "approve" if actionable and active > 0 else "block",
            },
            "priority": priority,
            "recommended_next_step": recommendation,
            "rationale": rationale,
        },
        "overall_ok": True,
    }


def main() -> None:
    control = run_script(STEP43_PATH)
    teams = run_script(STEP45_PATH)
    cycle = build_cycle(control, teams)
    append_jsonl(LOG_PATH, cycle)
    print(json.dumps(cycle, indent=2))


if __name__ == "__main__":
    main()
