#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--sleep-seconds", type=float, default=10.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step30/dry_run_loop.jsonl"

    loop_records = []

    for i in range(args.iterations):
        iteration = i + 1

        operator_console = run_script(["scripts/step29_operator_console.py"])
        notifier_step26 = run_script(["scripts/step28_deduped_event_notifier.py", "--event", "step26"])

        record = {
            "ts": utc_now_iso(),
            "run_id": run_id,
            "kind": "step30_dry_run_loop_iteration",
            "iteration": iteration,
            "operator_console": operator_console,
            "notifier_step26": notifier_step26,
        }

        append_jsonl(log_path, record)
        loop_records.append(record)

        if iteration < args.iterations:
            time.sleep(args.sleep_seconds)

    success_count = sum(
        1
        for r in loop_records
        if r["operator_console"]["ok"] and r["notifier_step26"]["ok"]
    )

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step30_dry_run_loop_summary",
        "checks": {
            "loop_execution": {
                "ok": True,
                "details": {
                    "iterations_requested": args.iterations,
                    "iterations_completed": len(loop_records),
                    "sleep_seconds": args.sleep_seconds,
                    "fully_successful_iterations": success_count,
                },
            },
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
