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
from app.kalshi_agentic.market_scan import fetch_markets_page, summarize_markets_page


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_base_market(market: dict) -> bool:
    ticker = (market.get("ticker") or "")
    event_ticker = (market.get("event_ticker") or "")

    if ticker.startswith("KXMVE"):
        return False
    if event_ticker.startswith("KXMVE"):
        return False

    return True


def _is_reasonably_tradable_base_market(market: dict) -> bool:
    if not _is_base_market(market):
        return False

    if market.get("status") != "active":
        return False

    if market.get("market_type") != "binary":
        return False

    yes_bid = _to_float(market.get("yes_bid_dollars"), default=-1.0)
    yes_ask = _to_float(market.get("yes_ask_dollars"), default=-1.0)
    no_bid = _to_float(market.get("no_bid_dollars"), default=-1.0)
    no_ask = _to_float(market.get("no_ask_dollars"), default=-1.0)

    # require actual quoted internal prices on both sides
    if not (0.0 < yes_ask < 1.0):
        return False
    if not (0.0 < no_bid < 1.0):
        return False

    if yes_bid < 0.0 or no_ask < 0.0:
        return False

    return True


def _score_base_market(market: dict) -> float:
    yes_bid = _to_float(market.get("yes_bid_dollars"), default=0.0)
    yes_ask = _to_float(market.get("yes_ask_dollars"), default=1.0)
    no_bid = _to_float(market.get("no_bid_dollars"), default=0.0)
    no_ask = _to_float(market.get("no_ask_dollars"), default=1.0)
    last_price = _to_float(market.get("last_price_dollars"), default=-1.0)
    volume = _to_float(market.get("volume_fp"), default=0.0)
    liquidity = _to_float(market.get("liquidity_dollars"), default=0.0)
    yes_ask_size = _to_float(market.get("yes_ask_size_fp"), default=0.0)
    no_bid_size = _to_float(market.get("no_bid_size_fp"), default=0.0)

    score = 0.0

    score += 30.0  # passed base-market filter
    if 0.0 < last_price < 1.0:
        score += 10.0

    score += min(volume, 5000.0) / 50.0
    score += min(liquidity, 5000.0) / 25.0
    score += min(yes_ask_size, 5000.0) / 250.0
    score += min(no_bid_size, 5000.0) / 250.0

    score -= (yes_ask - yes_bid) * 40.0
    score -= (no_ask - no_bid) * 40.0

    return round(score, 4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    args = parser.parse_args()

    settings = load_settings()
    client = KalshiClient(settings=settings)

    run_id = str(uuid.uuid4())
    log_path = "logs/step8/base_market_scan.jsonl"

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
    base_markets = [m for m in deduped_markets if _is_base_market(m)]
    tradable_base_markets = [m for m in base_markets if _is_reasonably_tradable_base_market(m)]

    ranked = []
    for market in tradable_base_markets:
        scored = dict(market)
        scored["scan_score"] = _score_base_market(market)
        ranked.append(scored)

    ranked.sort(
        key=lambda item: (
            item.get("scan_score", 0.0),
            _to_float(item.get("liquidity_dollars")),
            _to_float(item.get("volume_fp")),
            _to_float(item.get("yes_ask_size_fp")),
            _to_float(item.get("no_bid_size_fp")),
        ),
        reverse=True,
    )

    ranked = ranked[: args.top]

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step8_base_market_scan_summary",
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
            "base_market_filter": {
                "ok": True,
                "details": {
                    "raw_market_count": raw_market_count,
                    "deduped_market_count": len(deduped_markets),
                    "base_market_count": len(base_markets),
                    "tradable_base_market_count": len(tradable_base_markets),
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

