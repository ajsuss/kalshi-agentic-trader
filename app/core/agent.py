from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentManifest:
    """Minimal metadata used for agent discovery and routing."""

    name: str
    description: str
    version: str = "0.1.0"


class BaseAgent(ABC):
    """Base contract for all rebuild-era agents."""

    manifest: AgentManifest

    @abstractmethod
    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute agent logic and return structured output."""
        raise NotImplementedError
