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

from app.kalshi_agentic.config import load_settings
from app.kalshi_agentic.kalshi_client import KalshiClient
from app.kalshi_agentic.market_selection import (
    fetch_market_by_ticker,
    summarize_market_lookup,
    fetch_event_by_ticker,
    summarize_event_lookup,
    build_targeted_market_context,
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, help="Kalshi market ticker")
    parser.add_argument("--peer-limit", type=int, default=5)
    args = parser.parse_args()

    settings = load_settings()
    client = KalshiClient(settings=settings)

    run_id = str(uuid.uuid4())
    log_path = "logs/step5/targeted_snapshot.jsonl"

    checks = {
        "market_lookup": {"ok": False, "details": {}},
        "event_lookup": {"ok": False, "details": {}},
        "context_build": {"ok": False, "details": {}},
    }

    market_payload = fetch_market_by_ticker(client, args.market)
    market_summary = summarize_market_lookup(market_payload, args.market)

    append_jsonl(
        log_path,
        {
            "ts": utc_now_iso(),
            "run_id": run_id,
            "kind": "raw_market_lookup",
            "requested_market_ticker": args.market,
            "payload": market_payload,
        },
    )

    checks["market_lookup"]["ok"] = True
    checks["market_lookup"]["details"] = market_summary

    event_ticker = market_summary.get("event_ticker")
    if not event_ticker:
        raise RuntimeError("Could not derive event_ticker from market lookup.")

    event_payload = fetch_event_by_ticker(client, event_ticker, with_nested_markets=True)
    event_summary = summarize_event_lookup(event_payload, event_ticker)

    append_jsonl(
        log_path,
        {
            "ts": utc_now_iso(),
            "run_id": run_id,
            "kind": "raw_event_lookup",
            "requested_event_ticker": event_ticker,
            "payload": event_payload,
        },
    )

    checks["event_lookup"]["ok"] = True
    checks["event_lookup"]["details"] = event_summary

    context = build_targeted_market_context(
        market_payload=market_payload,
        event_payload=event_payload,
        target_market_ticker=args.market,
        peer_limit=args.peer_limit,
    )

    checks["context_build"]["ok"] = True
    checks["context_build"]["details"] = {
        "target_market_ticker": context["target_market"]["ticker"],
        "event_ticker": context["event_context"]["event_ticker"],
        "peer_market_count_included": context["event_context"]["peer_market_count_included"],
    }

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step5_targeted_snapshot_summary",
        "requested_market_ticker": args.market,
        "checks": checks,
        "targeted_context": context,
        "overall_ok": all(item["ok"] for item in checks.values()),
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
