#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone


STEP43_PATH = Path("scripts/step43_repo_state_snapshot.py")
STEP48_LOG_PATH = Path("logs/step48/periodic_brain_loop.jsonl")
PERF_SEED_PATH = Path("state/performance_seed.json")
PERF_LOG_PATH = Path("logs/step49/performance_snapshot.jsonl")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def run_step43() -> dict:
    completed = subprocess.run(
        ["python3", str(STEP43_PATH)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"step43 failed with code {completed.returncode}: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_step48_iterations() -> list[dict]:
    if not STEP48_LOG_PATH.exists():
        return []

    iterations = []
    with STEP48_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == "step48_periodic_brain_loop_iteration":
                iterations.append(record)
    return iterations


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def build_snapshot(control: dict, perf_seed: dict, iterations: list[dict]) -> dict:
    rec_counts: Counter[str] = Counter()
    priorities: Counter[str] = Counter()

    first_ts = None
    last_ts = None
    for item in iterations:
        cycle = item.get("cycle", {}).get("deliberation", {})
        rec = cycle.get("recommended_next_step")
        priority = cycle.get("priority")
        if rec:
            rec_counts[rec] += 1
        if priority:
            priorities[priority] += 1

        parsed = parse_iso(item.get("ts"))
        if parsed is not None:
            if first_ts is None or parsed < first_ts:
                first_ts = parsed
            if last_ts is None or parsed > last_ts:
                last_ts = parsed

    duration_minutes = None
    if first_ts and last_ts:
        duration_minutes = round((last_ts - first_ts).total_seconds() / 60.0, 3)

    return {
        "ts": utc_now_iso(),
        "kind": "step49_performance_snapshot",
        "performance": {
            "starting_bankroll_usd": perf_seed.get("starting_bankroll_usd"),
            "current_bankroll_usd": perf_seed.get("current_bankroll_usd"),
            "realized_pnl_usd": perf_seed.get("realized_pnl_usd"),
            "unrealized_pnl_usd": perf_seed.get("unrealized_pnl_usd"),
            "win_rate": perf_seed.get("win_rate"),
            "max_drawdown_pct": perf_seed.get("max_drawdown_pct"),
        },
        "control_plane": {
            "state_source": control.get("state_source"),
            "active_candidate_count": control.get("active_candidate_count"),
            "retired_candidate_count": control.get("retired_candidate_count"),
            "executor_actionable_now": control.get("executor_actionable_now"),
            "execution_mode": control.get("execution_mode"),
        },
        "brain_loop_stats": {
            "iterations_count": len(iterations),
            "first_iteration_ts": first_ts.isoformat() if first_ts else None,
            "last_iteration_ts": last_ts.isoformat() if last_ts else None,
            "duration_minutes": duration_minutes,
            "priority_counts": dict(priorities),
            "recommended_next_step_counts": dict(rec_counts),
        },
        "overall_ok": True,
    }


def main() -> None:
    control = run_step43()
    perf_seed = load_json(PERF_SEED_PATH)
    iterations = load_step48_iterations()

    snapshot = build_snapshot(control, perf_seed, iterations)
    append_jsonl(PERF_LOG_PATH, snapshot)
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
