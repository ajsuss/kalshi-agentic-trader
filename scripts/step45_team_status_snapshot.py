#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone


SEED_PATH = Path("state/team_status_seed.json")
STEP43_PATH = Path("state/codex_seed_state.json")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_snapshot(seed: dict, control_plane_seed: dict) -> dict:
    executor_actionable = control_plane_seed.get("executor_actionable_now")
    active_count = control_plane_seed.get("active_candidate_count")

    out = dict(seed)
    out["snapshot_ts"] = utc_now_iso()
    out["state_source"] = seed.get("state_source", "seed")
    out["control_plane"] = {
        "active_candidate_count": active_count,
        "retired_candidate_count": control_plane_seed.get("retired_candidate_count"),
        "executor_actionable_now": executor_actionable,
        "execution_mode": control_plane_seed.get("execution_mode"),
    }

    if isinstance(out.get("teams"), dict) and isinstance(out["teams"].get("executor"), dict):
        out["teams"]["executor"]["status"] = "ready" if executor_actionable else "blocked"

    if isinstance(out.get("next_best_trade"), dict):
        out["next_best_trade"]["available"] = bool(executor_actionable) and bool(active_count)

    return out


def main() -> None:
    seed = load_json(SEED_PATH)
    control_plane_seed = load_json(STEP43_PATH)
    snapshot = build_snapshot(seed, control_plane_seed)
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
