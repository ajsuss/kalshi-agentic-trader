from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OperatorPreferences:
    excluded_ticker_patterns: list[str] = field(
        default_factory=lambda: [
            "XMVESPORTSMULTIGAME",
            "XMVECROSSCATEGORY",
            "MULTIGAME",
            "CROSSCATEGORY",
            "PARLAY",
            "BUNDLE",
            "COMPOSITE",
            "EXTENDED",
        ]
    )
    excluded_title_patterns: list[str] = field(
        default_factory=lambda: [
            "multi-game",
            "cross-category",
            "parlay",
            "bundle",
            "extended",
            "combination",
        ]
    )
    max_title_length: int = 140
    min_close_hours: float = 2.0
    max_close_hours: float = 24 * 21
    min_history_signal: float = 1.0
    min_open_interest: float = 5.0
    min_volume: float = 5.0
    min_quote_quality: float = 0.2
    penalize_no_live_quote: float = 15.0
    penalize_composite: float = 45.0
    penalize_low_interpretability: float = 25.0
    penalize_too_close: float = 40.0
    penalize_too_far: float = 10.0
    penalize_weak_signal: float = 30.0
    min_recommendation_score: float = 15.0


def load_operator_preferences(repo_root: Path) -> OperatorPreferences:
    config_path = repo_root / "state" / "operator_preferences.json"
    if not config_path.exists():
        return OperatorPreferences()

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return OperatorPreferences()

    base = OperatorPreferences()
    payload: dict[str, Any] = {**base.__dict__}
    for key, value in raw.items():
        if key in payload:
            payload[key] = value
    return OperatorPreferences(**payload)
