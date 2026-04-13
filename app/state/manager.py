from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StateManager:
    """Centralized JSON-backed state manager with atomic writes."""

    root: Path

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "StateManager":
        return cls(root=repo_root / "state")

    def _resolve(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError(f"State path escapes root: {relative_path}")
        return path

    def read_json(self, relative_path: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        path = self._resolve(relative_path)
        if not path.exists():
            return default.copy() if isinstance(default, dict) else (default or {})
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, relative_path: str, payload: dict[str, Any]) -> Path:
        path = self._resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(path)
        return path
