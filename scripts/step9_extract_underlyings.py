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
from app.kalshi_agentic.market_scan import fetch_markets_page


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


def extract_underlying_market_tickers(market_payload: dict) -> list[str]:
    market = market_payload.get("market", market_payload)
    tickers: list[str] = []

    custom_strike = market.get("custom_strike") or {}
    associated_markets = custom_strike.get("Associated Markets")
    if isinstance(associated_markets, str) and associated_markets.strip():
        for item in associated_markets.split(","):
            ticker = item.strip()
            if ticker:
                tickers.append(ticker)

    for leg in market.get("mve_selected_legs", []) or []:
        ticker = leg.get("market_ticker")
        if ticker:
            tickers.append(ticker)

    deduped = []
    seen = set()
    for ticker in tickers:
        if ticker not in seen:
            seen.add(ticker)
            deduped.append(ticker)

    return deduped


def summarize_base_market(payload: dict) -> dict:
    market = payload.get("market", payload)
    return {
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "status": market.get("status"),
        "title": market.get("title"),
        "subtitle": market.get("sub_title", market.get("subtitle")),
        "market_type": market.get("market_type"),
        "close_time": market.get("close_time"),
        "yes_bid_dollars": market.get("yes_bid_dollars"),
        "yes_ask_dollars": market.get("yes_ask_dollars"),
        "no_bid_dollars": market.get("no_bid_dollars"),
        "no_ask_dollars": market.get("no_ask_dollars"),
        "last_price_dollars": market.get("last_price_dollars"),
        "volume_fp": market.get("volume_fp"),
        "liquidity_dollars": market.get("liquidity_dollars"),
        "yes_bid_size_fp": market.get("yes_bid_size_fp"),
        "yes_ask_size_fp": market.get("yes_ask_size_fp"),
        "no_bid_size_fp": market.get("no_bid_size_fp"),
        "no_ask_size_fp": market.get("no_ask_size_fp"),
    }


def is_reasonably_tradable_base_market(market: dict) -> bool:
    if market.get("status") != "active":
        return False

    if market.get("market_type") != "binary":
        return False

    yes_bid = _to_float(market.get("yes_bid_dollars"), default=-1.0)
    yes_ask = _to_float(market.get("yes_ask_dollars"), default=-1.0)
    no_bid = _to_float(market.get("no_bid_dollars"), default=-1.0)
    no_ask = _to_float(market.get("no_ask_dollars"), default=-1.0)

    if not (0.0 < yes_ask < 1.0):
        return False
    if not (0.0 < no_bid < 1.0):
        return False

    if yes_bid < 0.0 or no_ask < 0.0:
        return False

    return True


def score_base_market(market: dict) -> float:
    yes_bid = _to_float(market.get("yes_bid_dollars"), default=0.0)
    yes_ask = _to_float(market.get("yes_ask_dollars"), default=1.0)
    no_bid = _to_float(market.get("no_bid_dollars"), default=0.0)
    no_ask = _to_float(market.get("no_ask_dollars"), default=1.0)
    last_price = _to_float(market.get("last_price_dollars"), default=-1.0)
    volume = _to_float(market.get("volume_fp"), default=0.0)
    liquidity = _to_float(market.get("liquidity_dollars"), default=0.0)
    yes_ask_size = _to_float(market.get("yes_ask_size_fp"), default=0.0)
    no_bid_size = _to_float(market.get("no_bid_size_fp"), default=0.0)

    score = 30.0

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
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    args = parser.parse_args()

    settings = load_settings()
    client = KalshiClient(settings=settings)

    run_id = str(uuid.uuid4())
    log_path = "logs/step9/extract_underlyings.jsonl"

    cursor = None
    parent_pages_fetched = 0
    parent_market_count = 0
    underlying_tickers: list[str] = []

    for page_index in range(args.pages):
        payload = fetch_markets_page(client, limit=args.limit, cursor=cursor)
        markets = payload.get("markets", []) or []

        append_jsonl(
            log_path,
            {
                "ts": utc_now_iso(),
                "run_id": run_id,
                "kind": "raw_parent_markets_page",
                "page_index": page_index,
                "params": {"limit": args.limit, "cursor": cursor},
                "payload": payload,
            },
        )

        for market in markets:
            parent_market_count += 1
            underlying_tickers.extend(extract_underlying_market_tickers({"market": market}))

        parent_pages_fetched += 1
        cursor = payload.get("cursor")
        if not cursor:
            break

        time.sleep(args.sleep_seconds)

    deduped_underlyings = []
    seen = set()
    for ticker in underlying_tickers:
        if ticker not in seen:
            seen.add(ticker)
            deduped_underlyings.append(ticker)

    base_market_summaries = []
    for idx, ticker in enumerate(deduped_underlyings):
        response = client.public_get(f"/trade-api/v2/markets/{ticker}")
        payload = response.json()

        append_jsonl(
            log_path,
            {
                "ts": utc_now_iso(),
                "run_id": run_id,
                "kind": "raw_underlying_market",
                "underlying_index": idx,
                "ticker": ticker,
                "payload": payload,
            },
        )

        summary = summarize_base_market(payload)
        if is_reasonably_tradable_base_market(summary):
            summary["scan_score"] = score_base_market(summary)
            base_market_summaries.append(summary)

        time.sleep(args.sleep_seconds)

    base_market_summaries.sort(
        key=lambda item: (
            item.get("scan_score", 0.0),
            _to_float(item.get("liquidity_dollars")),
            _to_float(item.get("volume_fp")),
            _to_float(item.get("yes_ask_size_fp")),
            _to_float(item.get("no_bid_size_fp")),
        ),
        reverse=True,
    )

    top_candidates = base_market_summaries[: args.top]

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step9_extract_underlyings_summary",
        "checks": {
            "parent_page_scan": {
                "ok": parent_pages_fetched > 0,
                "details": {
                    "pages_requested": args.pages,
                    "pages_fetched": parent_pages_fetched,
                    "parent_market_count": parent_market_count,
                },
            },
            "underlying_extraction": {
                "ok": True,
                "details": {
                    "raw_underlying_count": len(underlying_tickers),
                    "deduped_underlying_count": len(deduped_underlyings),
                    "tradable_underlying_count": len(base_market_summaries),
                    "top_requested": args.top,
                    "top_returned": len(top_candidates),
                },
            },
        },
        "top_candidates": top_candidates,
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
