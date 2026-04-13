from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.execution.executor import Executor, TradeIntent
from app.state.manager import StateManager


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LegacyCompat:
    repo_root: Path

    @property
    def state(self) -> StateManager:
        return StateManager.from_repo_root(self.repo_root)

    def build_step43_snapshot(self) -> dict[str, Any]:
        seed = self.state.read_json("codex_seed_state.json", default={})
        return {
            "snapshot_ts": utc_now_iso(),
            "state_source": "seed",
            "active_candidate_count": seed.get("active_candidate_count"),
            "retired_candidate_count": seed.get("retired_candidate_count"),
            "executor_actionable_now": seed.get("executor_actionable_now"),
            "retired_candidate_market_ticker": seed.get("retired_candidate_market_ticker"),
            "guarded_live_path_blocked_by": seed.get("guarded_live_path_blocked_by", []),
            "execution_mode": seed.get("execution_mode", "dry_run"),
        }

    def build_step45_team_status_snapshot(self) -> dict[str, Any]:
        seed = self.state.read_json("team_status_seed.json", default={})
        control = self.build_step43_snapshot()

        out = dict(seed)
        out["snapshot_ts"] = utc_now_iso()
        out["state_source"] = control.get("state_source", "seed")
        out["control_plane"] = {
            "active_candidate_count": control.get("active_candidate_count"),
            "retired_candidate_count": control.get("retired_candidate_count"),
            "executor_actionable_now": control.get("executor_actionable_now"),
            "execution_mode": control.get("execution_mode"),
            "guarded_live_path_blocked_by": control.get("guarded_live_path_blocked_by", []),
        }
        return out

    def build_step46_digest(self) -> dict[str, Any]:
        control = self.build_step43_snapshot()
        teams = self.build_step45_team_status_snapshot()
        return {
            "ts": utc_now_iso(),
            "kind": "step46_control_plane_digest",
            "digest": {
                "source": control.get("state_source"),
                "execution_mode": control.get("execution_mode"),
                "active_candidate_count": control.get("active_candidate_count"),
                "retired_candidate_count": control.get("retired_candidate_count"),
                "executor_actionable_now": control.get("executor_actionable_now"),
                "guarded_path_blocked_by": control.get("guarded_live_path_blocked_by", []),
                "phase": (teams.get("progress") or {}).get("phase"),
            },
        }

    def build_executor_review(self, *, market_ticker: str, side: str, contracts: int, max_price_dollars: float) -> dict[str, Any]:
        intent = TradeIntent(
            market_ticker=market_ticker,
            side=side,
            contracts=contracts,
            max_price_dollars=max_price_dollars,
            rationale="legacy_compat_review",
        )
        result = Executor().review(intent)
        return asdict(result)
