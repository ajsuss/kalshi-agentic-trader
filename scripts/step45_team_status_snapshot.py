#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone


SEED_PATH = Path("state/team_status_seed.json")
STEP43_SCRIPT_PATH = Path("scripts/step43_repo_state_snapshot.py")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_step43_snapshot() -> dict:
    completed = subprocess.run(
        ["python3", str(STEP43_SCRIPT_PATH)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"step43 snapshot command failed with code {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def build_snapshot(seed: dict, control_plane_seed: dict) -> dict:
    executor_actionable = control_plane_seed.get("executor_actionable_now")
    active_count = control_plane_seed.get("active_candidate_count")
    retired_count = control_plane_seed.get("retired_candidate_count")
    blocked_by = control_plane_seed.get("guarded_live_path_blocked_by", []) or []
    blocked_text = ", ".join(blocked_by) if blocked_by else "none"

    out = dict(seed)
    out["snapshot_ts"] = utc_now_iso()
    out["state_source"] = control_plane_seed.get("state_source", seed.get("state_source", "seed"))
    out["control_plane"] = {
        "active_candidate_count": active_count,
        "retired_candidate_count": retired_count,
        "executor_actionable_now": executor_actionable,
        "execution_mode": control_plane_seed.get("execution_mode"),
        "guarded_live_path_blocked_by": blocked_by,
    }

    if isinstance(out.get("teams"), dict) and isinstance(out["teams"].get("executor"), dict):
        out["teams"]["executor"]["status"] = "ready" if executor_actionable else "blocked"
        out["teams"]["executor"]["summary"] = (
            "Executor ready to route candidate through guarded path."
            if executor_actionable
            else f"Actionable_now false; guarded path blocks: {blocked_text}."
        )

    if isinstance(out.get("teams"), dict) and isinstance(out["teams"].get("algorithms"), dict):
        out["teams"]["algorithms"]["summary"] = (
            "Queue-aware dry-run monitoring active; candidate available for review."
            if active_count
            else "Queue-aware dry-run monitoring active; no actionable candidates currently."
        )

    if isinstance(out.get("next_best_trade"), dict):
        out["next_best_trade"]["available"] = bool(executor_actionable) and bool(active_count)
        out["next_best_trade"]["market_ticker"] = (
            control_plane_seed.get("retired_candidate_market_ticker")
            if not active_count
            else out["next_best_trade"].get("market_ticker")
        )
        if not active_count:
            out["next_best_trade"]["reason"] = (
                f"No active queue candidates (retired_count={retired_count}); "
                "previously approved Philadelphia spread candidate is retired."
            )
        elif not executor_actionable:
            out["next_best_trade"]["reason"] = (
                f"Candidate exists but executor is blocked by: {blocked_text}."
            )
        else:
            out["next_best_trade"]["reason"] = (
                "Candidate is present and executor is actionable; guarded dry-run path ready."
            )

    return out


def main() -> None:
    seed = load_json(SEED_PATH)
    control_plane_seed = load_step43_snapshot()
    snapshot = build_snapshot(seed, control_plane_seed)
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
