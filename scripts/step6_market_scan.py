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
from app.kalshi_agentic.market_scan import (
    fetch_markets_page,
    summarize_markets_page,
    rank_market_candidates,
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
    parser.add_argument("--limit", type=int, default=25, help="How many markets to fetch")
    parser.add_argument("--top", type=int, default=10, help="How many ranked results to keep")
    args = parser.parse_args()

    settings = load_settings()
    client = KalshiClient(settings=settings)

    run_id = str(uuid.uuid4())
    log_path = "logs/step6/market_scan.jsonl"

    checks = {
        "markets_page_fetch": {"ok": False, "details": {}},
        "page_summary": {"ok": False, "details": {}},
        "candidate_ranking": {"ok": False, "details": {}},
    }

    payload = fetch_markets_page(client, limit=args.limit, cursor=None)

    append_jsonl(
        log_path,
        {
            "ts": utc_now_iso(),
            "run_id": run_id,
            "kind": "raw_markets_page",
            "params": {"limit": args.limit},
            "payload": payload,
        },
    )

    checks["markets_page_fetch"]["ok"] = True
    checks["markets_page_fetch"]["details"] = {
        "requested_limit": args.limit,
        "cursor_present": payload.get("cursor") is not None,
    }

    page_summary = summarize_markets_page(payload)
    checks["page_summary"]["ok"] = True
    checks["page_summary"]["details"] = {
        "market_count": page_summary["market_count"],
        "cursor": page_summary["cursor"],
    }

    ranked = rank_market_candidates(page_summary["markets"], top_n=args.top)
    checks["candidate_ranking"]["ok"] = True
    checks["candidate_ranking"]["details"] = {
        "top_requested": args.top,
        "top_returned": len(ranked),
    }

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step6_market_scan_summary",
        "checks": checks,
        "top_candidates": ranked,
        "overall_ok": all(item["ok"] for item in checks.values()),
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
