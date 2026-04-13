from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from app.core.agent import BaseAgent


@dataclass
class RegisteredAgent:
    name: str
    description: str
    instance: BaseAgent


class AgentRegistry:
    """Simple in-process registry and loader for BaseAgent implementations."""

    def __init__(self) -> None:
        self._agents: dict[str, RegisteredAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        key = agent.manifest.name.strip().lower()
        if not key:
            raise ValueError("Agent manifest name cannot be empty.")
        self._agents[key] = RegisteredAgent(
            name=agent.manifest.name,
            description=agent.manifest.description,
            instance=agent,
        )

    def load_from_package(self, package_name: str = "app.agents") -> int:
        package = importlib.import_module(package_name)
        discovered = 0

        for module_info in pkgutil.iter_modules(package.__path__, f"{package.__name__}."):
            module = importlib.import_module(module_info.name)
            discovered += self._register_from_module(module)

        return discovered

    def _register_from_module(self, module: ModuleType) -> int:
        count = 0
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not isinstance(attr, type):
                continue
            if attr is BaseAgent or not issubclass(attr, BaseAgent):
                continue
            try:
                self.register(attr())
                count += 1
            except TypeError:
                continue
        return count

    def list_agents(self) -> list[dict[str, str]]:
        return [
            {"name": reg.name, "description": reg.description}
            for reg in sorted(self._agents.values(), key=lambda a: a.name.lower())
        ]

    def run(self, name: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        key = name.strip().lower()
        if key not in self._agents:
            raise KeyError(f"Unknown agent: {name}")
        return self._agents[key].instance.run(context or {})
