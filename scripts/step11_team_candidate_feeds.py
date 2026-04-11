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


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_latest_step10_summary(path: str) -> dict:
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
            if record.get("kind") == "step10_candidate_board_summary":
                latest = record

    if latest is None:
        raise RuntimeError("No step10_candidate_board_summary found in step10 log.")

    return latest


def flatten_board(board: dict[str, list[dict]]) -> list[dict]:
    items: list[dict] = []
    for family, markets in board.items():
        for market in markets:
            row = dict(market)
            row["family_original"] = family
            items.append(row)
    return items


def refine_family(item: dict) -> str:
    original = item.get("family", "other")
    t = (item.get("ticker") or "").upper()
    title = (item.get("title") or "").upper()

    if original != "other":
        return original

    if "TOP20" in t or "TOP30" in t:
        return "outright"

    if "BTTS" in t or "BOTH TEAMS TO SCORE" in title:
        return "btts"

    if "ROUNDS" in t or "END BEFORE ROUND" in title:
        return "fight_rounds"

    if "ATPMATCH" in t or "WTAMATCH" in t:
        return "racket_match"

    return "other"


def horizon_rank(horizon: str) -> int:
    ranks = {
        "intraday": 0,
        "short_term": 1,
        "longer_term": 2,
        "unknown": 3,
        "expiredish": 4,
    }
    return ranks.get(horizon, 9)


def prepare_item(item: dict) -> dict:
    row = dict(item)
    row["family_refined"] = refine_family(row)
    row["yes_spread"] = round(
        _to_float(row.get("yes_ask_dollars")) - _to_float(row.get("yes_bid_dollars")),
        4,
    )
    row["no_spread"] = round(
        _to_float(row.get("no_ask_dollars")) - _to_float(row.get("no_bid_dollars")),
        4,
    )
    row["volume_fp_num"] = _to_float(row.get("volume_fp"))
    row["yes_ask_size_fp_num"] = _to_float(row.get("yes_ask_size_fp"))
    row["yes_bid_size_fp_num"] = _to_float(row.get("yes_bid_size_fp"))
    return row


def build_algorithms_feed(items: list[dict], per_feed: int) -> list[dict]:
    allowed = {"winner", "spread", "total"}
    feed = [i for i in items if i["family_refined"] in allowed]

    feed.sort(
        key=lambda i: (
            horizon_rank(i.get("horizon", "unknown")),
            i.get("yes_spread", 999.0),
            -i.get("volume_fp_num", 0.0),
            -i.get("yes_ask_size_fp_num", 0.0),
        )
    )
    return feed[:per_feed]


def build_information_media_feed(items: list[dict], per_feed: int) -> list[dict]:
    allowed = {"winner", "spread", "total", "fight_winner", "player_prop", "btts"}
    feed = [i for i in items if i["family_refined"] in allowed]

    feed.sort(
        key=lambda i: (
            horizon_rank(i.get("horizon", "unknown")),
            -i.get("volume_fp_num", 0.0),
            i.get("yes_spread", 999.0),
            -i.get("yes_ask_size_fp_num", 0.0),
        )
    )
    return feed[:per_feed]


def build_deliberators_feed(items: list[dict], per_feed: int) -> list[dict]:
    priority = {
        "outright": 0,
        "btts": 1,
        "racket_match": 1,
        "fight_rounds": 1,
        "winner": 2,
        "fight_winner": 3,
        "other": 4,
    }

    allowed = set(priority.keys())
    feed = [dict(i) for i in items if i["family_refined"] in allowed]

    feed.sort(
        key=lambda i: (
            priority.get(i["family_refined"], 9),
            horizon_rank(i.get("horizon", "unknown")),
            -i.get("volume_fp_num", 0.0),
            i.get("yes_spread", 999.0),
        )
    )

    feed = feed[:per_feed]

    for row in feed:
        row["manual_review_required"] = True

    return feed

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-feed", type=int, default=8)
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    log_path = "logs/step11/team_candidate_feeds.jsonl"

    step10_summary = load_latest_step10_summary("logs/step10/candidate_board.jsonl")
    flat = flatten_board(step10_summary["board"])
    prepared = [prepare_item(item) for item in flat]

    algorithms_feed = build_algorithms_feed(prepared, args.per_feed)
    information_media_feed = build_information_media_feed(prepared, args.per_feed)
    deliberators_feed = build_deliberators_feed(prepared, args.per_feed)

    summary = {
        "ts": utc_now_iso(),
        "run_id": run_id,
        "kind": "step11_team_candidate_feeds_summary",
        "checks": {
            "step10_summary_load": {
                "ok": True,
                "details": {
                    "source_run_id": step10_summary.get("run_id"),
                    "families_found": step10_summary.get("checks", {})
                    .get("candidate_board", {})
                    .get("details", {})
                    .get("families_found", []),
                },
            },
            "feed_build": {
                "ok": True,
                "details": {
                    "input_candidate_count": len(prepared),
                    "algorithms_count": len(algorithms_feed),
                    "information_media_count": len(information_media_feed),
                    "deliberators_count": len(deliberators_feed),
                    "per_feed": args.per_feed,
                },
            },
        },
        "feeds": {
            "algorithms": algorithms_feed,
            "information_media": information_media_feed,
            "deliberators": deliberators_feed,
        },
        "overall_ok": True,
    }

    append_jsonl(log_path, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
