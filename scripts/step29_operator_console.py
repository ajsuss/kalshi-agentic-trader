#!/usr/bin/env python3
from __future__ import annotations

import json
import uuid
from pathlib import Path
from datetime import datetime, UTC


SOURCES = {
    "team_feeds": {
        "path": "logs/step11/team_candidate_feeds.jsonl",
        "kind": "step11_team_candidate_feeds_summary",
    },
    "review_packets": {
        "path": "logs/step13/review_packets.jsonl",
        "kind": "step13_review_packets_summary",
    },
    "executor_intake": {
        "path": "logs/step15/executor_intake.jsonl",
        "kind": "step15_executor_intake_summary",
    },
    "executor_decision": {
        "path": "logs/step16/executor_decisions.jsonl",
        "kind": "step16_executor_decision_record",
    },
    "submission_candidates": {
        "path": "logs/step17/order_submission_candidates.jsonl",
        "kind": "step17_order_submission_candidates_summary",
    },
    "simulated_submission": {
        "path": "logs/step18/simulated_submission.jsonl",
        "kind": "step18_simulated_submission_record",
    },
    "execution_gate": {
        "path": "logs/step19/execution_gate.jsonl",
        "kind": "step19_execution_gate_summary",
    },
    "risk_guard": {
        "path": "logs/step25/risk_guard.jsonl",
        "kind": "step25_risk_guard_summary",
    },
    "guarded_live_path": {
        "path": "logs/step26/guarded_live_order_path.jsonl",
        "kind": "step37_guarded_live_order_path_fresh_summary",
    },
    "deduped_notifier": {
        "path": "logs/step28/deduped_event_notifier.jsonl",
        "kind": "step28_deduped_event_notifier_summary",
    },
    "retired_candidates": {
        "path": "logs/step39/retired_candidates.jsonl",
        "kind": "step39_retire_stale_candidates_summary",
    },
    "active_queue": {
        "path": "logs/step42/active_queue_view.jsonl",
        "kind": "step42_active_queue_view_summary",
    },
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_latest(path: str, kind: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None

    latest = None
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == kind:
                latest = record
    return latest


def summarize_team_feeds(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    details = record["checks"]["feed_build"]["details"]
    return {
        "present": True,
        "run_id": record["run_id"],
        "algorithms_count": details["algorithms_count"],
        "information_media_count": details["information_media_count"],
        "deliberators_count": details["deliberators_count"],
    }


def summarize_review_packets(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    details = record["checks"]["review_packet_build"]["details"]
    return {
        "present": True,
        "run_id": record["run_id"],
        "algorithms_count": details["algorithms_count"],
        "information_media_count": details["information_media_count"],
        "deliberators_count": details["deliberators_count"],
    }


def summarize_executor_intake(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    items = record.get("executor_intake_packets", [])
    first = items[0] if items else None
    return {
        "present": True,
        "run_id": record["run_id"],
        "intake_count": len(items),
        "top_market_ticker": first.get("market_ticker") if first else None,
        "top_team": first.get("team") if first else None,
    }


def summarize_executor_decision(record: dict | None, retired_record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    d = record["executor_decision"]

    retired = False
    retirement_reason = None
    retirement_market_status = None
    if retired_record and retired_record.get("retirement_record"):
        rr = retired_record["retirement_record"]
        if rr and rr.get("source_proposal_id") == d.get("source_proposal_id"):
            retired = bool(rr.get("retired"))
            retirement_reason = rr.get("reason_code")
            retirement_market_status = rr.get("market_status")

    actionable_now = bool(d.get("ready_for_order_submission")) and not retired

    return {
        "present": True,
        "run_id": record["run_id"],
        "team": d["team"],
        "market_ticker": d["market_ticker"],
        "decision_state": d["decision_state"],
        "ready_for_order_submission": d["ready_for_order_submission"],
        "retired": retired,
        "retirement_reason": retirement_reason,
        "retirement_market_status": retirement_market_status,
        "actionable_now": actionable_now,
        "next_stage": d["next_stage"],
    }


def summarize_submission_candidates(record: dict | None, retired_record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    details = record["checks"]["candidate_build"]["details"]
    items = record.get("order_submission_candidates", [])
    first = items[0] if items else None

    retired = False
    retired_market_ticker = None
    if retired_record and retired_record.get("retirement_record"):
        rr = retired_record["retirement_record"]
        if rr:
            retired = bool(rr.get("retired"))
            retired_market_ticker = rr.get("market_ticker")

    top_candidate_retired = bool(first and retired and first.get("market_ticker") == retired_market_ticker)

    return {
        "present": True,
        "run_id": record["run_id"],
        "candidate_count": details["candidate_count"],
        "valid_candidate_count": details["valid_candidate_count"],
        "top_candidate_id": first.get("submission_candidate_id") if first else None,
        "top_market_ticker": first.get("market_ticker") if first else None,
        "top_candidate_retired": top_candidate_retired,
    }


def summarize_simulated_submission(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    s = record["simulated_submission"]
    return {
        "present": True,
        "run_id": record["run_id"],
        "team": s["team"],
        "market_ticker": s["market_ticker"],
        "simulated_outcome": s["simulated_outcome"],
        "submission_status": s["submission_status"],
    }


def summarize_execution_gate(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    d = record["checks"]["execution_gate"]["details"]
    return {
        "present": True,
        "run_id": record["run_id"],
        "live_execution_allowed": d["allowed"],
        "execution_mode": d["env_snapshot"]["EXECUTION_MODE"],
        "live_trading_enabled": d["env_snapshot"]["LIVE_TRADING_ENABLED"],
    }


def summarize_risk_guard(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    d = record["checks"]["risk_evaluation"]["details"]
    return {
        "present": True,
        "run_id": record["run_id"],
        "estimated_order_notional_dollars": d["estimated_order_notional_dollars"],
        "risk_guard_allowed": d["risk_guard_allowed"],
        "team_budget_dollars": d["team_budget_dollars"],
    }


def summarize_guarded_live_path(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    d = record["checks"]["request_attempt"]["details"]
    return {
        "present": True,
        "run_id": record["run_id"],
        "request_sent": d["request_sent"],
        "client_profile_used": d["client_profile_used"],
        "blocked_by": d["blocked_by"],
    }


def summarize_deduped_notifier(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    d = record["checks"]["dedupe_check"]["details"]
    return {
        "present": True,
        "run_id": record["run_id"],
        "already_seen": d["already_seen"],
        "skipped_duplicate": d["skipped_duplicate"],
        "event": record["notification_preview"]["event"],
    }


def summarize_retired_candidates(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    rr = record.get("retirement_record")
    return {
        "present": True,
        "run_id": record["run_id"],
        "retirement_created": rr is not None,
        "market_ticker": rr.get("market_ticker") if rr else None,
        "reason_code": rr.get("reason_code") if rr else None,
        "market_status": rr.get("market_status") if rr else None,
        "retired": rr.get("retired") if rr else None,
    }

def summarize_active_queue(record: dict | None) -> dict:
    if record is None:
        return {"present": False}

    details = record["checks"]["active_queue_build"]["details"]
    queue = record.get("active_queue", {})
    active = queue.get("active_candidates", [])
    retired = queue.get("retired_candidates", [])

    top_active = active[0] if active else None
    top_retired = retired[0] if retired else None

    return {
        "present": True,
        "run_id": record["run_id"],
        "active_candidate_count": details["active_candidate_count"],
        "retired_candidate_count": details["retired_candidate_count"],
        "executor_actionable_now": details["executor_actionable_now"],
        "top_active_market_ticker": top_active.get("market_ticker") if top_active else None,
        "top_retired_market_ticker": top_retired.get("market_ticker") if top_retired else None,
    }

def main() -> None:
    run_id = str(uuid.uuid4())
    log_path = "logs/step29/operator_console.jsonl"

    loaded = {
        name: load_latest(meta["path"], meta["kind"])
        for name, meta in SOURCES.items()
    }

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step40_operator_console_retirement_summary",
        "console": {
            "team_feeds": summarize_team_feeds(loaded["team_feeds"]),
            "review_packets": summarize_review_packets(loaded["review_packets"]),
            "executor_intake": summarize_executor_intake(loaded["executor_intake"]),
            "executor_decision": summarize_executor_decision(
                loaded["executor_decision"],
                loaded["retired_candidates"],
            ),
            "submission_candidates": summarize_submission_candidates(
                loaded["submission_candidates"],
                loaded["retired_candidates"],
            ),
            "active_queue": summarize_active_queue(loaded["active_queue"]),
            "simulated_submission": summarize_simulated_submission(loaded["simulated_submission"]),
            "execution_gate": summarize_execution_gate(loaded["execution_gate"]),
            "risk_guard": summarize_risk_guard(loaded["risk_guard"]),
            "guarded_live_path": summarize_guarded_live_path(loaded["guarded_live_path"]),
            "deduped_notifier": summarize_deduped_notifier(loaded["deduped_notifier"]),
            "retired_candidates": summarize_retired_candidates(loaded["retired_candidates"]),
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
