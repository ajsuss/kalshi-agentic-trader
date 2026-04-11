from __future__ import annotations

from typing import Any

import requests

from .config import Settings


class TelegramNotifier:
    """Small reusable Telegram notifier."""

    def __init__(self, settings: Settings, timeout: float = 10.0) -> None:
        self.settings = settings
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    def send_message(
        self,
        text: str,
        *,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": text,
            "disable_notification": disable_notification,
        }
        response = requests.post(
            f"{self.base_url}/sendMessage",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError(f"Telegram API returned non-ok response: {data}")
        return data
