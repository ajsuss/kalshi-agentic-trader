#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
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
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--per-family", type=int, default=4)
    parser.add_argument("--per-feed", type=int, default=8)
    parser.add_argument("--per-team", type=int, default=5)
    parser.add_argument("--sleep-seconds", type=float, default=0.6)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step38/refresh_review_queue.jsonl"

    step10 = run_script(
        [
            "scripts/step10_candidate_board.py",
            "--pages", str(args.pages),
            "--limit", str(args.limit),
            "--per-family", str(args.per_family),
            "--sleep-seconds", str(args.sleep_seconds),
        ]
    )

    step11 = run_script(
        [
            "scripts/step11_team_candidate_feeds.py",
            "--per-feed", str(args.per_feed),
        ]
    )

    step12 = run_script(
        [
            "scripts/step12_proposal_stubs.py",
            "--per-team", str(args.per_team),
        ]
    )

    step13 = run_script(
        [
            "scripts/step13_review_packets.py",
            "--per-team", str(args.per_team),
        ]
    )

    step29 = run_script(["scripts/step29_operator_console.py"])

    record = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step38_refresh_review_queue_summary",
        "checks": {
            "step10_candidate_board": {"ok": step10["ok"], "details": step10},
            "step11_team_feeds": {"ok": step11["ok"], "details": step11},
            "step12_proposal_stubs": {"ok": step12["ok"], "details": step12},
            "step13_review_packets": {"ok": step13["ok"], "details": step13},
            "step29_operator_console": {"ok": step29["ok"], "details": step29},
        },
        "overall_ok": all(
            item["ok"]
            for item in [step10, step11, step12, step13, step29]
        ),
    }

    append_jsonl(log_path, record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
