from __future__ import annotations

from app.interfaces.telegram.main import TelegramApp, TelegramRuntimeConfig


def _app(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "dry_run")
    monkeypatch.setenv("KALSHI_LIVE_TRADING_ARMED", "0")
    return TelegramApp(config=TelegramRuntimeConfig(bot_token="dummy", chat_id="123"), poll_timeout=1)


def test_help_command_includes_operator_sections(monkeypatch):
    app = _app(monkeypatch)
    text = app.router.dispatch("/help")
    assert "Kalshi Dry-Run Operator Bot" in text
    assert "/markets" in text


def test_policy_command_is_human_readable(monkeypatch):
    app = _app(monkeypatch)
    text = app.router.dispatch("/policy")
    assert "Policy Check" in text
    assert "Approved: False" in text


def test_review_command_is_operator_readable(monkeypatch):
    app = _app(monkeypatch)
    text = app.router.dispatch("/review TEST YES 1 0.50")
    assert "Review Result" in text
    assert "Outcome: BLOCKED" in text


def test_candidates_command_requires_refresh_first(monkeypatch):
    app = _app(monkeypatch)
    text = app.router.dispatch("/candidates")
    assert "Run /refresh or /recommend first" in text
