#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
STEP43_PATH = REPO_ROOT / "scripts" / "step43_repo_state_snapshot.py"
STEP47_PATH = REPO_ROOT / "scripts" / "step47_deliberation_cycle.py"
STEP8_LOG_PATH = REPO_ROOT / "logs" / "step8" / "base_market_scan.jsonl"
STEP6_LOG_PATH = REPO_ROOT / "logs" / "step6" / "market_scan.jsonl"


def run_json(script_path: Path, timeout: int = 45) -> dict[str, Any]:
    completed = subprocess.run(
        ["python3", str(script_path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{script_path.name} failed ({completed.returncode}): {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def latest_market_candidates() -> list[dict[str, Any]]:
    for path, kind in (
        (STEP8_LOG_PATH, "step8_base_market_scan_summary"),
        (STEP6_LOG_PATH, "step6_market_scan_summary"),
    ):
        if not path.exists():
            continue
        latest = None
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("kind") == kind:
                    latest = record
        if latest:
            return latest.get("top_candidates", []) or []
    return []


def match_markets(query: str, candidates: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
    q = query.lower().strip()
    if not q:
        return candidates[:top_n]

    scored: list[tuple[float, dict[str, Any]]] = []
    for market in candidates:
        ticker = str(market.get("ticker", ""))
        title = str(market.get("title", market.get("subtitle", "")))
        hay = f"{ticker} {title}".lower()
        ratio = difflib.SequenceMatcher(a=q, b=hay).ratio()
        if q in hay:
            ratio += 0.4
        scored.append((ratio, market))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:top_n] if item[0] > 0.15]


def format_market_line(market: dict[str, Any]) -> str:
    ticker = market.get("ticker")
    title = market.get("title", market.get("subtitle"))
    yes_ask = market.get("yes_ask_dollars")
    no_bid = market.get("no_bid_dollars")
    score = market.get("scan_score")
    return f"- {ticker}: {title} | yes_ask={yes_ask} no_bid={no_bid} scan_score={score}"


def answer_prompt(prompt: str) -> dict[str, Any]:
    prompt_l = prompt.lower().strip()
    snapshot = run_json(STEP43_PATH, timeout=30)
    response_lines: list[str] = []
    actions: list[str] = []

    if any(k in prompt_l for k in ("position", "portfolio", "current state", "where are we")):
        response_lines.extend(
            [
                "Current control-plane position:",
                f"- active_candidate_count={snapshot.get('active_candidate_count')}",
                f"- retired_candidate_count={snapshot.get('retired_candidate_count')}",
                f"- executor_actionable_now={snapshot.get('executor_actionable_now')}",
                f"- execution_mode={snapshot.get('execution_mode')}",
            ]
        )
        actions.append("position_summary")

    candidates = latest_market_candidates()
    looks_like_market_query = any(
        k in prompt_l for k in ("market", "find", "similar", "ticker", "look up", "search")
    )
    if looks_like_market_query:
        matched = match_markets(prompt, candidates, top_n=5)
        if matched:
            response_lines.append("Closest markets:")
            response_lines.extend(format_market_line(m) for m in matched)
        else:
            response_lines.append("No close market matches found in local scan logs (step8/step6).")
        actions.append("market_search")

    if any(k in prompt_l for k in ("trade", "deliberate", "next best", "recommend")):
        cycle = run_json(STEP47_PATH, timeout=45)
        d = cycle.get("deliberation", {})
        response_lines.extend(
            [
                "Deliberation recommendation (read-only):",
                f"- priority={d.get('priority')}",
                f"- recommended_next_step={d.get('recommended_next_step')}",
                f"- rationale={d.get('rationale')}",
            ]
        )
        actions.append("deliberation")

    if not actions:
        response_lines.extend(
            [
                "I can help with:",
                "- current position summary",
                "- market lookup/similar markets from local scan logs",
                "- read-only deliberation recommendation",
                "Try: /ask current position and find similar markets for Philadelphia spread",
            ]
        )
        actions.append("help")

    return {
        "kind": "step51_operator_agent_response",
        "actions": actions,
        "prompt": prompt,
        "response_text": "\n".join(response_lines),
        "snapshot_source": snapshot.get("state_source"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Operator prompt agent for Telegram /ask")
    parser.add_argument("--prompt", required=True, help="Prompt/question from operator")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = answer_prompt(args.prompt)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
