#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def load_latest_step11_summary(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Could not find log file: {path}")

    latest = None
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == "step11_team_candidate_feeds_summary":
                latest = record

    if latest is None:
        raise RuntimeError("No step11_team_candidate_feeds_summary found in step11 log.")

    return latest


def make_stub(team: str, item: dict) -> dict:
    review_mode = {
        "algorithms": "leader_review",
        "information_media": "leader_review",
        "deliberators": "human_review",
    }[team]

    family = item.get("family_refined", item.get("family", "unknown"))
    horizon = item.get("horizon", "unknown")
    price_hint = item.get("yes_ask_dollars")

    thesis = {
        "algorithms": f"Candidate from {family} / {horizon} feed with relatively tight quoted spread and structured market data.",
        "information_media": f"Candidate from {family} / {horizon} feed suitable for event-driven review before any order decision.",
        "deliberators": f"Candidate from {family} / {horizon} feed flagged for manual thesis development and human approval.",
    }[team]

    return {
        "proposal_id": str(uuid.uuid4()),
        "team": team,
        "review_mode": review_mode,
        "market_ticker": item.get("ticker"),
        "event_ticker": item.get("event_ticker"),
        "title": item.get("title"),
        "family": family,
        "horizon": horizon,
        "status": item.get("status"),
        "market_type": item.get("market_type"),
        "price_hint_yes_ask_dollars": price_hint,
        "yes_bid_dollars": item.get("yes_bid_dollars"),
        "yes_ask_dollars": item.get("yes_ask_dollars"),
        "no_bid_dollars": item.get("no_bid_dollars"),
        "no_ask_dollars": item.get("no_ask_dollars"),
        "scan_score": item.get("scan_score"),
        "thesis_stub": thesis,
        "recommended_action": "research_only",
        "executor_ready": False,
        "human_required": team == "deliberators",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-team", type=int, default=5)
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step12/proposal_stubs.jsonl"

    step11_summary = load_latest_step11_summary("logs/step11/team_candidate_feeds.jsonl")
    feeds = step11_summary["feeds"]

    proposals = {}
    for team_name, items in feeds.items():
        proposals[team_name] = [make_stub(team_name, item) for item in items[: args.per_team]]

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step12_proposal_stubs_summary",
        "checks": {
            "step11_summary_load": {
                "ok": True,
                "details": {
                    "source_run_id": step11_summary.get("run_id"),
                    "teams_found": sorted(feeds.keys()),
                },
            },
            "proposal_stub_build": {
                "ok": True,
                "details": {
                    "per_team_requested": args.per_team,
                    "algorithms_count": len(proposals.get("algorithms", [])),
                    "information_media_count": len(proposals.get("information_media", [])),
                    "deliberators_count": len(proposals.get("deliberators", [])),
                },
            },
        },
        "proposals": proposals,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
