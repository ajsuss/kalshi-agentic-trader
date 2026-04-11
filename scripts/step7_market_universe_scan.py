#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
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
    parser.add_argument("--pages", type=int, default=5, help="How many pages to scan")
    parser.add_argument("--limit", type=int, default=25, help="Markets per page")
    parser.add_argument("--top", type=int, default=15, help="How many ranked candidates to keep")
    parser.add_argument("--sleep-seconds", type=float, default=0.35, help="Pause between page requests")
    args = parser.parse_args()

    settings = load_settings()
    client = KalshiClient(settings=settings)

    run_id = str(uuid.uuid4())
    log_path = "logs/step7/market_universe_scan.jsonl"

    cursor = None
    pages_fetched = 0
    raw_market_count = 0
    by_ticker: dict[str, dict] = {}

    for page_index in range(args.pages):
        payload = fetch_markets_page(client, limit=args.limit, cursor=cursor)
        page_summary = summarize_markets_page(payload)

        append_jsonl(
            log_path,
            {
                "ts": utc_now_iso(),
                "run_id": run_id,
                "kind": "raw_markets_page",
                "page_index": page_index,
                "params": {"limit": args.limit, "cursor": cursor},
                "payload": payload,
            },
        )

        for market in page_summary["markets"]:
            ticker = market.get("ticker")
            if ticker:
                by_ticker[ticker] = market

        pages_fetched += 1
        raw_market_count += page_summary["market_count"]

        cursor = page_summary.get("cursor")
        if not cursor:
            break

        time.sleep(args.sleep_seconds)

    deduped_markets = list(by_ticker.values())
    ranked = rank_market_candidates(deduped_markets, top_n=args.top)

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step7_market_universe_scan_summary",
        "checks": {
            "page_fetch_loop": {
                "ok": pages_fetched > 0,
                "details": {
                    "pages_requested": args.pages,
                    "pages_fetched": pages_fetched,
                    "limit_per_page": args.limit,
                    "sleep_seconds": args.sleep_seconds,
                },
            },
            "universe_scan": {
                "ok": True,
                "details": {
                    "raw_market_count": raw_market_count,
                    "deduped_market_count": len(deduped_markets),
                    "top_requested": args.top,
                    "top_returned": len(ranked),
                },
            },
        },
        "top_candidates": ranked,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()