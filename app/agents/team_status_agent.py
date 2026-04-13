from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.agent import AgentManifest, BaseAgent
from app.migration.legacy_compat import LegacyCompat


class TeamStatusAgent(BaseAgent):
    manifest = AgentManifest(
        name="team_status",
        description="Returns control-plane aligned team status snapshot.",
    )

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        repo_root = Path(context.get("repo_root", Path(__file__).resolve().parents[2]))
        compat = LegacyCompat(repo_root=repo_root)
        return compat.build_step45_team_status_snapshot()
