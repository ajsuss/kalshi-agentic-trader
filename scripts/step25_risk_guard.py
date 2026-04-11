#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from datetime import datetime, UTC


DEFAULT_TOTAL_BANKROLL = 500.0
DEFAULT_MAX_ORDER_NOTIONAL_PCT = 0.10
DEFAULT_MAX_CONTRACTS = 5
DEFAULT_MAX_PRICE = 0.85

TEAM_BUDGETS = {
    "algorithms": 0.40,
    "information_media": 0.35,
    "deliberators": 0.25,
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--bankroll", type=float, default=DEFAULT_TOTAL_BANKROLL)
    parser.add_argument("--max-order-notional-pct", type=float, default=DEFAULT_MAX_ORDER_NOTIONAL_PCT)
    parser.add_argument("--max-contracts", type=int, default=DEFAULT_MAX_CONTRACTS)
    parser.add_argument("--max-price", type=float, default=DEFAULT_MAX_PRICE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step25/risk_guard.jsonl"

    step17_summary = load_latest_step17_summary("logs/step17/order_submission_candidates.jsonl")
    candidate = find_candidate(step17_summary, args.candidate_id)

    team = candidate.get("team")
    order = candidate.get("order_payload", {})

    contracts = int(order.get("contracts"))
    max_price = float(order.get("max_price_dollars"))
    estimated_notional = contracts * max_price
    total_bankroll = float(args.bankroll)

    team_budget_fraction = TEAM_BUDGETS.get(team, 0.0)
    team_budget_dollars = total_bankroll * team_budget_fraction
    max_order_notional_dollars = total_bankroll * float(args.max_order_notional_pct)

    checks = {
        "candidate_exists": True,
        "contracts_within_limit": contracts <= int(args.max_contracts),
        "price_within_limit": max_price <= float(args.max_price),
        "order_notional_within_global_limit": estimated_notional <= max_order_notional_dollars,
        "order_notional_within_team_budget": estimated_notional <= team_budget_dollars,
    }

    allowed = all(checks.values())

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step25_risk_guard_summary",
        "checks": {
            "candidate_load": {
                "ok": True,
                "details": {
                    "source_run_id": step17_summary.get("run_id"),
                    "submission_candidate_id": candidate.get("submission_candidate_id"),
                    "market_ticker": candidate.get("market_ticker"),
                    "team": team,
                },
            },
            "risk_evaluation": {
                "ok": True,
                "details": {
                    "contracts": contracts,
                    "max_price_dollars": max_price,
                    "estimated_order_notional_dollars": round(estimated_notional, 4),
                    "total_bankroll_dollars": total_bankroll,
                    "team_budget_fraction": team_budget_fraction,
                    "team_budget_dollars": round(team_budget_dollars, 4),
                    "max_order_notional_dollars": round(max_order_notional_dollars, 4),
                    "checks": checks,
                    "risk_guard_allowed": allowed,
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
