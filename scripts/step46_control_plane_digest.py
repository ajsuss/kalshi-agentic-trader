#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone


STEP43_PATH = Path("scripts/step43_repo_state_snapshot.py")
STEP45_PATH = Path("scripts/step45_team_status_snapshot.py")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_snapshot_script(path: Path) -> dict:
    completed = subprocess.run(
        ["python3", str(path)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{path.name} failed with code {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def build_digest(control: dict, teams: dict) -> dict:
    blockers = control.get("guarded_live_path_blocked_by", []) or []
    blocked_text = ", ".join(blockers) if blockers else "none"

    return {
        "ts": utc_now_iso(),
        "kind": "step46_control_plane_digest",
        "digest": {
            "source": control.get("state_source"),
            "execution_mode": control.get("execution_mode"),
            "active_candidate_count": control.get("active_candidate_count"),
            "retired_candidate_count": control.get("retired_candidate_count"),
            "executor_actionable_now": control.get("executor_actionable_now"),
            "guarded_path_blocked_by": blockers,
            "guarded_path_blocked_by_text": blocked_text,
            "next_best_trade_available": teams.get("next_best_trade", {}).get("available"),
            "next_best_trade_market_ticker": teams.get("next_best_trade", {}).get("market_ticker"),
            "next_best_trade_reason": teams.get("next_best_trade", {}).get("reason"),
            "phase": teams.get("progress", {}).get("phase"),
        },
    }


def main() -> None:
    control = run_snapshot_script(STEP43_PATH)
    teams = run_snapshot_script(STEP45_PATH)
    digest = build_digest(control, teams)
    print(json.dumps(digest, indent=2))


if __name__ == "__main__":
    main()
