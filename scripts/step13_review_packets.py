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


def load_latest_step12_summary(path: str) -> dict:
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
            if record.get("kind") == "step12_proposal_stubs_summary":
                latest = record

    if latest is None:
        raise RuntimeError("No step12_proposal_stubs_summary found in step12 log.")

    return latest


def routing_for_team(team: str) -> dict:
    if team == "algorithms":
        return {
            "review_stage": "team_leader_review",
            "required_reviewer": "algorithms_leader",
            "next_stage_if_approved": "executor_intake",
            "notify_on_submit": False,
            "notify_on_decision": True,
            "human_required_now": False,
        }

    if team == "information_media":
        return {
            "review_stage": "team_leader_review",
            "required_reviewer": "information_media_leader",
            "next_stage_if_approved": "executor_intake",
            "notify_on_submit": False,
            "notify_on_decision": True,
            "human_required_now": False,
        }

    if team == "deliberators":
        return {
            "review_stage": "human_review",
            "required_reviewer": "human_operator",
            "next_stage_if_approved": "executor_intake_or_manual_hold",
            "notify_on_submit": True,
            "notify_on_decision": True,
            "human_required_now": True,
        }

    raise ValueError(f"Unknown team: {team}")


def make_order_template(proposal: dict) -> dict:
    return {
        "market_ticker": proposal.get("market_ticker"),
        "side": None,
        "action": "buy",
        "contracts": None,
        "max_price_dollars": proposal.get("price_hint_yes_ask_dollars"),
        "expiration_policy": "day",
        "time_in_force": "limit",
    }


def make_review_packet(team: str, proposal: dict) -> dict:
    routing = routing_for_team(team)

    return {
        "packet_id": str(uuid.uuid4()),
        "source_proposal_id": proposal.get("proposal_id"),
        "team": team,
        "review_stage": routing["review_stage"],
        "required_reviewer": routing["required_reviewer"],
        "decision_state": "pending_review",
        "next_stage_if_approved": routing["next_stage_if_approved"],
        "notification_policy": {
            "notify_on_submit": routing["notify_on_submit"],
            "notify_on_decision": routing["notify_on_decision"],
        },
        "proposal_snapshot": {
            "market_ticker": proposal.get("market_ticker"),
            "event_ticker": proposal.get("event_ticker"),
            "title": proposal.get("title"),
            "family": proposal.get("family"),
            "horizon": proposal.get("horizon"),
            "status": proposal.get("status"),
            "market_type": proposal.get("market_type"),
            "price_hint_yes_ask_dollars": proposal.get("price_hint_yes_ask_dollars"),
            "scan_score": proposal.get("scan_score"),
            "thesis_stub": proposal.get("thesis_stub"),
        },
        "draft_order_template": make_order_template(proposal),
        "review_requirements": {
            "rationale_required": True,
            "position_size_required": True,
            "risk_comment_required": True,
            "human_required_now": routing["human_required_now"],
            "executor_ready": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-team", type=int, default=5)
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step13/review_packets.jsonl"

    step12_summary = load_latest_step12_summary("logs/step12/proposal_stubs.jsonl")
    proposals = step12_summary["proposals"]

    packets = {}
    for team_name, items in proposals.items():
        packets[team_name] = [
            make_review_packet(team_name, proposal)
            for proposal in items[: args.per_team]
        ]

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step13_review_packets_summary",
        "checks": {
            "step12_summary_load": {
                "ok": True,
                "details": {
                    "source_run_id": step12_summary.get("run_id"),
                    "teams_found": sorted(proposals.keys()),
                },
            },
            "review_packet_build": {
                "ok": True,
                "details": {
                    "per_team_requested": args.per_team,
                    "algorithms_count": len(packets.get("algorithms", [])),
                    "information_media_count": len(packets.get("information_media", [])),
                    "deliberators_count": len(packets.get("deliberators", [])),
                },
            },
        },
        "packets": packets,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
