#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone


SEED_PATH = Path("state/codex_seed_state.json")


SOURCES = {
    "step42": {
        "path": Path("logs/step42/active_queue_view.jsonl"),
        "kind": "step42_active_queue_view_summary",
    },
    "step40": {
        "path": Path("logs/step29/operator_console.jsonl"),
        "kind": "step40_operator_console_retirement_summary",
    },
    "step37": {
        "path": Path("logs/step26/guarded_live_order_path.jsonl"),
        "kind": "step37_guarded_live_order_path_fresh_summary",
    },
    "step39": {
        "path": Path("logs/step39/retired_candidates.jsonl"),
        "kind": "step39_retire_stale_candidates_summary",
    },
    "step19": {
        "path": Path("logs/step19/execution_gate.jsonl"),
        "kind": "step19_execution_gate_summary",
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_latest_record(path: Path, kind: str) -> dict | None:
    if not path.exists():
        return None

    latest = None
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == kind:
                latest = record
    return latest


def load_seed_state() -> dict:
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"Missing seed state file: {SEED_PATH}")
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def build_from_logs(records: dict[str, dict | None]) -> dict | None:
    step42 = records["step42"]
    step40 = records["step40"]
    step37 = records["step37"]
    step39 = records["step39"]
    step19 = records["step19"]

    if step42 is None and step40 is None and step37 is None and step39 is None and step19 is None:
        return None

    active_candidate_count = None
    retired_candidate_count = None
    if step42:
        details = step42.get("checks", {}).get("active_queue_build", {}).get("details", {})
        active_candidate_count = details.get("active_candidate_count")
        retired_candidate_count = details.get("retired_candidate_count")

    executor_actionable_now = None
    if step40:
        executor_actionable_now = (
            step40.get("console", {})
            .get("executor_decision", {})
            .get("actionable_now")
        )

    retired_candidate_market_ticker = None
    if step39:
        retired_candidate_market_ticker = (
            step39.get("retirement_record", {}) or {}
        ).get("market_ticker")

    guarded_live_path_blocked_by = []
    if step37:
        guarded_live_path_blocked_by = (
            step37.get("checks", {})
            .get("request_attempt", {})
            .get("details", {})
            .get("blocked_by", [])
            or []
        )

    execution_mode = None
    if step19:
        execution_mode = (
            step19.get("checks", {})
            .get("execution_gate", {})
            .get("details", {})
            .get("env_snapshot", {})
            .get("EXECUTION_MODE")
        )

    return {
        "snapshot_ts": utc_now_iso(),
        "state_source": "runtime_logs",
        "active_candidate_count": active_candidate_count,
        "retired_candidate_count": retired_candidate_count,
        "executor_actionable_now": executor_actionable_now,
        "retired_candidate_market_ticker": retired_candidate_market_ticker,
        "guarded_live_path_blocked_by": guarded_live_path_blocked_by,
        "execution_mode": execution_mode,
    }


def build_from_seed(seed: dict) -> dict:
    return {
        "snapshot_ts": utc_now_iso(),
        "state_source": "seed",
        "active_candidate_count": seed.get("active_candidate_count"),
        "retired_candidate_count": seed.get("retired_candidate_count"),
        "executor_actionable_now": seed.get("executor_actionable_now"),
        "retired_candidate_market_ticker": seed.get("retired_candidate_market_ticker"),
        "guarded_live_path_blocked_by": seed.get("guarded_live_path_blocked_by", []),
        "execution_mode": seed.get("execution_mode"),
    }


def main() -> None:
    records = {
        name: load_latest_record(meta["path"], meta["kind"])
        for name, meta in SOURCES.items()
    }

    runtime_snapshot = build_from_logs(records)
    if runtime_snapshot is not None:
        print(json.dumps(runtime_snapshot, indent=2))
        return

    seed = load_seed_state()
    print(json.dumps(build_from_seed(seed), indent=2))


if __name__ == "__main__":
    main()
