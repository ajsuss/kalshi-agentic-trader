from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.policies.risk_policy import PolicyDecision, RiskPolicy


@dataclass(frozen=True)
class TradeIntent:
    market_ticker: str
    side: str
    contracts: int
    max_price_dollars: float
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_ticker": self.market_ticker,
            "side": self.side,
            "contracts": self.contracts,
            "max_price_dollars": self.max_price_dollars,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ExecutorResult:
    approved: bool
    dry_run: bool
    reason: str
    policy_reasons: list[str]
    intent: dict[str, Any]


class Executor:
    """Single gateway for order execution decisions."""

    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def review(self, intent: TradeIntent) -> ExecutorResult:
        payload = intent.to_dict()
        policy: PolicyDecision = self.policy.evaluate(payload)
        if not policy.approved:
            return ExecutorResult(
                approved=False,
                dry_run=True,
                reason="blocked_by_policy",
                policy_reasons=policy.reasons,
                intent=payload,
            )

        return ExecutorResult(
            approved=True,
            dry_run=False,
            reason="approved_for_live_execution",
            policy_reasons=[],
            intent=payload,
        )
