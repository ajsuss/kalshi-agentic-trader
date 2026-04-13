from __future__ import annotations

from app.interfaces.telegram.main import TelegramApp, TelegramRuntimeConfig


def test_help_command_includes_read_only_text(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "dry_run")
    monkeypatch.setenv("KALSHI_LIVE_TRADING_ARMED", "0")

    app = TelegramApp(
        config=TelegramRuntimeConfig(bot_token="dummy", chat_id="123"),
        poll_timeout=1,
    )

    text = app.router.dispatch("/help")
    assert "/status" in text
    assert "Safety" in text


def test_review_command_is_policy_blocked_by_default(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "dry_run")
    monkeypatch.setenv("KALSHI_LIVE_TRADING_ARMED", "0")

    app = TelegramApp(
        config=TelegramRuntimeConfig(bot_token="dummy", chat_id="123"),
        poll_timeout=1,
    )

    text = app.router.dispatch("/review TEST YES 1 0.50")
    assert "blocked_by_policy" in text
