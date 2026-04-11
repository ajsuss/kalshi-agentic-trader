#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from datetime import datetime, UTC

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.kalshi_agentic.client_factory import make_read_client


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_latest_step17_summary(path: str) -> dict:
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
            if record.get("kind") == "step17_order_submission_candidates_summary":
                latest = record

    if latest is None:
        raise RuntimeError("No step17_order_submission_candidates_summary found in step17 log.")

    return latest


def find_candidate(step17_summary: dict, candidate_id: str) -> dict:
    items = step17_summary.get("order_submission_candidates", [])
    for item in items:
        if item.get("submission_candidate_id") == candidate_id:
            return dict(item)
    raise RuntimeError(f"Could not find submission_candidate_id: {candidate_id}")


def load_latest_record(path: str, kind: str) -> dict | None:
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


def market_snapshot(candidate: dict) -> dict:
    read_client = None
    try:
        read_client, meta = make_read_client()
        ticker = candidate["market_ticker"]
        response = read_client.public_get(f"/trade-api/v2/markets/{ticker}")
        payload = response.json()
        market = payload.get("market", payload)

        return {
            "ok": True,
            "status_code": response.status_code,
            "ticker": market.get("ticker"),
            "status": market.get("status"),
            "yes_bid_dollars": market.get("yes_bid_dollars"),
            "yes_ask_dollars": market.get("yes_ask_dollars"),
            "no_bid_dollars": market.get("no_bid_dollars"),
            "no_ask_dollars": market.get("no_ask_dollars"),
            "last_price_dollars": market.get("last_price_dollars"),
            "client_profile_used": "read",
            "client_api_key_id": meta["api_key_id"],
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "ticker": candidate["market_ticker"],
            "status": None,
            "error_type": type(e).__name__,
            "error": str(e),
        }
    finally:
        if read_client is not None:
            read_client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--max-age-minutes", type=float, default=15.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step36/candidate_freshness_guard.jsonl"

    step17_summary = load_latest_step17_summary("logs/step17/order_submission_candidates.jsonl")
    candidate = find_candidate(step17_summary, args.candidate_id)

    candidate_summary_ts = parse_iso(step17_summary["ts"])
    age_minutes = (datetime.now(UTC) - candidate_summary_ts).total_seconds() / 60.0

    latest_step15 = load_latest_record("logs/step15/executor_intake.jsonl", "step15_executor_intake_summary")
    latest_step16 = load_latest_record("logs/step16/executor_decisions.jsonl", "step16_executor_decision_record")
    latest_step17 = step17_summary

    lineage_matches = True
    if latest_step15 is not None:
        intake_packets = latest_step15.get("executor_intake_packets", [])
        lineage_matches = lineage_matches and any(
            p.get("source_proposal_id") == candidate.get("source_proposal_id")
            for p in intake_packets
        )

    if latest_step16 is not None:
        exec_decision = latest_step16.get("executor_decision", {})
        lineage_matches = lineage_matches and (
            exec_decision.get("source_proposal_id") == candidate.get("source_proposal_id")
        )

    market = market_snapshot(candidate)

    quote_fields_present = all(
        market.get(field) is not None
        for field in ["yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars"]
    ) if market.get("ok") else False

    freshness_allowed = (
        age_minutes <= args.max_age_minutes
        and lineage_matches
        and market.get("ok") is True
        and market.get("status") == "active"
        and quote_fields_present
    )

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step36_candidate_freshness_guard_summary",
        "checks": {
            "candidate_load": {
                "ok": True,
                "details": {
                    "source_run_id": step17_summary.get("run_id"),
                    "submission_candidate_id": candidate.get("submission_candidate_id"),
                    "market_ticker": candidate.get("market_ticker"),
                    "source_proposal_id": candidate.get("source_proposal_id"),
                },
            },
            "freshness_evaluation": {
                "ok": True,
                "details": {
                    "candidate_summary_ts": step17_summary.get("ts"),
                    "age_minutes": round(age_minutes, 4),
                    "max_age_minutes": args.max_age_minutes,
                    "lineage_matches_latest_records": lineage_matches,
                    "market_snapshot": market,
                    "quote_fields_present": quote_fields_present,
                    "freshness_guard_allowed": freshness_allowed,
                },
            },
        },
        "candidate_snapshot": {
            "team": candidate.get("team"),
            "market_ticker": candidate.get("market_ticker"),
            "event_ticker": candidate.get("event_ticker"),
            "title": candidate.get("title"),
            "order_payload": candidate.get("order_payload"),
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
