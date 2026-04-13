from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyDecision:
    approved: bool
    reasons: list[str]
    mode: str


@dataclass(frozen=True)
class RiskPolicy:
    """Centralized risk and mode gating policy."""

    execution_mode_env: str = "EXECUTION_MODE"
    live_arm_env: str = "KALSHI_LIVE_TRADING_ARMED"

    def evaluate(self, intent: dict[str, Any]) -> PolicyDecision:
        mode = os.getenv(self.execution_mode_env, "dry_run").strip().lower() or "dry_run"
        armed = os.getenv(self.live_arm_env, "0").strip() == "1"

        reasons: list[str] = []

        if mode != "live":
            reasons.append("execution_mode_not_live")

        if not armed:
            reasons.append("live_trading_not_armed")

        contracts = int(intent.get("contracts", 0) or 0)
        if contracts <= 0:
            reasons.append("invalid_contract_size")

        side = str(intent.get("side", "")).upper()
        if side not in {"YES", "NO"}:
            reasons.append("invalid_side")

        return PolicyDecision(
            approved=len(reasons) == 0,
            reasons=reasons,
            mode=mode,
        )
