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


def test_scanstatus_format(monkeypatch):
    app = _app(monkeypatch)

    def fake_scan():
        return [], {
            "markets_fetched": 100,
            "pages_scanned": 2,
            "active_markets": 90,
            "binary_markets": 80,
            "quote_usable": 7,
            "history_usable": 22,
            "final_candidate_count": 5,
            "top_rejections": [("no_live_quote", 70)],
        }, None

    app._fetch_markets_with_diagnostics = fake_scan  # type: ignore[method-assign]
    text = app.router.dispatch("/scanstatus")
    assert "Scan Diagnostics" in text
    assert "markets fetched".lower() in text.lower()


def test_recommend_generates_message(monkeypatch):
    app = _app(monkeypatch)

    def fake_scan():
        return [
            {
                "ticker": "TEST-1",
                "title": "Test Market",
                "event_ticker": "EVT-1",
                "scan_score": 88.2,
                "scan_rationale": "live_quote, volume=10",
                "yes_ask_dollars": 0.52,
                "last_price_dollars": 0.50,
                "volume_fp": 10,
                "open_interest_fp": 12,
            }
        ], {"markets_fetched": 1, "pages_scanned": 1, "final_candidate_count": 1}, None

    app._fetch_markets_with_diagnostics = fake_scan  # type: ignore[method-assign]
    text = app.router.dispatch("/recommend")
    assert "Dry-Run Recommendation" in text
    assert "TEST-1" in text
