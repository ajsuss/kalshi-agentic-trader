from __future__ import annotations

from app.execution.executor import Executor, TradeIntent
from app.interfaces.telegram.router import TelegramCommandRouter
from app.policies.risk_policy import RiskPolicy


def test_policy_blocks_live_by_default(monkeypatch):
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    monkeypatch.delenv("KALSHI_LIVE_TRADING_ARMED", raising=False)

    decision = RiskPolicy().evaluate(
        {"market_ticker": "TEST", "side": "YES", "contracts": 1, "max_price_dollars": 0.5}
    )
    assert decision.approved is False
    assert "live_trading_not_armed" in decision.reasons


def test_executor_routes_through_policy(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "dry_run")
    monkeypatch.setenv("KALSHI_LIVE_TRADING_ARMED", "0")

    result = Executor().review(
        TradeIntent(
            market_ticker="TEST",
            side="YES",
            contracts=3,
            max_price_dollars=0.55,
        )
    )
    assert result.approved is False
    assert result.reason == "blocked_by_policy"


def test_telegram_router_dispatches():
    router = TelegramCommandRouter()
    router.register("/status", "status", lambda args: "ok")
    assert router.dispatch("/status") == "ok"
