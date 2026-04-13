from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


CommandHandler = Callable[[list[str]], str]


@dataclass
class CommandRoute:
    command: str
    description: str
    handler: CommandHandler


class TelegramCommandRouter:
    """Minimal command router abstraction for Telegram-first control plane."""

    def __init__(self) -> None:
        self._routes: dict[str, CommandRoute] = {}

    def register(self, command: str, description: str, handler: CommandHandler) -> None:
        normalized = command.strip().lower()
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        self._routes[normalized] = CommandRoute(
            command=normalized,
            description=description,
            handler=handler,
        )

    def dispatch(self, text: str) -> str:
        parts = (text or "").strip().split()
        if not parts:
            return "No command provided."

        command = parts[0].lower()
        if command not in self._routes:
            return f"Unknown command: {command}"

        return self._routes[command].handler(parts[1:])

    def help_text(self) -> str:
        rows = ["Available commands:"]
        for route in sorted(self._routes.values(), key=lambda r: r.command):
            rows.append(f"{route.command}: {route.description}")
        return "\n".join(rows)
