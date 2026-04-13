from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from app.core.agent_registry import AgentRegistry
from app.execution.executor import Executor, TradeIntent
from app.interfaces.telegram.router import TelegramCommandRouter
from app.migration.legacy_compat import LegacyCompat
from app.policies.risk_policy import RiskPolicy
from app.policies.operator_preferences import OperatorPreferences, load_operator_preferences
from app.state.manager import StateManager
from app.kalshi_agentic.client_factory import make_read_client
from app.kalshi_agentic.market_selection import fetch_event_by_ticker, fetch_market_by_ticker


REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = REPO_ROOT / ".env"
RUNTIME_DIR = REPO_ROOT / "logs" / "telegram_app"
OFFSET_STATE_PATH = RUNTIME_DIR / "offset_state.json"
EVENTS_LOG_PATH = RUNTIME_DIR / "events.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_secret(*, direct_env_var: str, file_env_var: str) -> str:
    direct_value = os.getenv(direct_env_var, "").strip()
    if direct_value:
        return direct_value

    file_value = os.getenv(file_env_var, "").strip()
    if file_value:
        path = Path(file_value).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Secret file does not exist: {path}")
        return path.read_text(encoding="utf-8").strip()

    raise ValueError(f"Missing {direct_env_var} or {file_env_var}")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_money(value: Any) -> str:
    number = _to_float(value, default=float("nan"))
    if number != number:
        return "n/a"
    return f"${number:,.2f}"


def _fmt_num(value: Any) -> str:
    number = _to_float(value, default=float("nan"))
    if number != number:
        return "n/a"
    return f"{number:,.2f}"


def _first(payload: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    return default


@dataclass(frozen=True)
class TelegramRuntimeConfig:
    bot_token: str
    chat_id: str

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}"


class TelegramApp:
    def __init__(self, config: TelegramRuntimeConfig, poll_timeout: int = 25) -> None:
        self.config = config
        self.poll_timeout = poll_timeout
        self.router = TelegramCommandRouter()
        self.registry = AgentRegistry()
        self.registry.load_from_package("app.agents")
        self.compat = LegacyCompat(repo_root=REPO_ROOT)
        self.executor = Executor(policy=RiskPolicy())
        self.state = StateManager.from_repo_root(REPO_ROOT)
        self.preferences = load_operator_preferences(REPO_ROOT)
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.register("/help", "Read-only: list commands and safety posture.", self._handle_help)
        self.router.register("/ping", "Read-only: liveness check.", self._handle_ping)
        self.router.register("/agents", "Read-only: list registered agents.", self._handle_agents)
        self.router.register("/status", "Read-only: control-plane summary.", self._handle_status)
        self.router.register("/team", "Read-only: team status summary.", self._handle_team)
        self.router.register("/digest", "Read-only: digest summary.", self._handle_digest)
        self.router.register("/policy", "Read-only: execution policy state.", self._handle_policy)
        self.router.register("/balance", "Read-only: account summary.", self._handle_balance)
        self.router.register("/positions", "Read-only: positions.", self._handle_positions)
        self.router.register("/orders", "Read-only: orders.", self._handle_orders)
        self.router.register("/markets", "Read-only: top scanned markets.", self._handle_markets)
        self.router.register("/scan", "Read-only: alias for /markets.", self._handle_markets)
        self.router.register("/scan_debug", "Debug: broad scan mode.", self._handle_scan_debug)
        self.router.register("/scanstatus", "Debug: scan diagnostics summary.", self._handle_scanstatus)
        self.router.register("/scanprefs", "Debug: universe and gate preferences.", self._handle_scanprefs)
        self.router.register("/why_nexttrade", "Debug: explain why top candidate won.", self._handle_why_nexttrade)
        self.router.register("/market", "Read-only: /market <MARKET_TICKER>", self._handle_market)
        self.router.register("/event", "Read-only: /event <EVENT_TICKER>", self._handle_event)
        self.router.register("/event_candidates", "Read-only: rank candidates within an event.", self._handle_event_candidates)
        self.router.register("/event_recommend", "Read-only: dry-run recommendation within event.", self._handle_event_recommend)
        self.router.register("/refresh", "Read-only: refresh candidates + recommendation.", self._handle_refresh)
        self.router.register("/candidates", "Read-only: top cached candidates.", self._handle_candidates)
        self.router.register("/nexttrade", "Read-only: cached best dry-run recommendation.", self._handle_nexttrade)
        self.router.register("/recommend", "Read-only: generate dry-run recommendation now.", self._handle_recommend)
        self.router.register("/review", "Read-only: /review <TICKER> <YES|NO> <CONTRACTS> <MAX_PRICE>", self._handle_review)

    def _help_sections(self) -> list[str]:
        return [
            "🤖 Kalshi Dry-Run Operator Bot",
            "Core: /help /ping /policy /status /team /digest",
            "Account: /balance /positions /orders",
            "Markets: /markets (/scan) /market <TICKER> /event <EVENT_TICKER> /event_candidates <EVENT>",
            "Recommendation: /refresh /recommend /nexttrade /event_recommend <EVENT> /review ...",
            "Diagnostics: /scanstatus [/scanstatus broad] /scan_debug /scanprefs /why_nexttrade",
            "Safety: live trading disabled by default; no live order route enabled.",
        ]

    def _handle_help(self, _: list[str]) -> str:
        return "\n".join(self._help_sections())

    def _handle_ping(self, _: list[str]) -> str:
        return f"pong {utc_now_iso()}"

    def _handle_agents(self, _: list[str]) -> str:
        agents = self.registry.list_agents()
        if not agents:
            return "No agents currently registered."
        lines = ["🧠 Registered agents:"]
        lines.extend(f"• {a['name']} — {a['description']}" for a in agents)
        return "\n".join(lines)

    def _with_read_client(self) -> tuple[Any | None, str | None]:
        try:
            return make_read_client()[0], None
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)

    def _handle_status(self, args: list[str]) -> str:
        payload = self.compat.build_step43_snapshot()
        if args and args[0].lower() == "raw":
            return json.dumps(payload, indent=2)

        return "\n".join(
            [
                "📊 Control Plane Status",
                f"Source: {payload.get('state_source', 'unknown')}",
                f"Execution mode: {payload.get('execution_mode', 'unknown')}",
                f"Active candidates: {payload.get('active_candidate_count', 'n/a')}",
                f"Retired candidates: {payload.get('retired_candidate_count', 'n/a')}",
                f"Executor actionable: {payload.get('executor_actionable_now', 'n/a')}",
                f"Blocked by: {', '.join(payload.get('guarded_live_path_blocked_by', []) or ['none'])}",
            ]
        )

    def _handle_team(self, args: list[str]) -> str:
        payload = self.registry.run("team_status", {"repo_root": REPO_ROOT})
        if args and args[0].lower() == "raw":
            return json.dumps(payload, indent=2)

        control = payload.get("control_plane", {})
        progress = payload.get("progress", {})
        next_trade = payload.get("next_best_trade", {})
        return "\n".join(
            [
                "👥 Team Status",
                f"Phase: {progress.get('phase', 'n/a')}",
                f"Progress: {progress.get('completed_steps', 'n/a')}/{progress.get('total_steps', 'n/a')}",
                f"Control mode: {control.get('execution_mode', 'n/a')}",
                f"Active/Retired: {control.get('active_candidate_count', 'n/a')}/{control.get('retired_candidate_count', 'n/a')}",
                f"Seed next-trade available: {next_trade.get('available', False)}",
            ]
        )

    def _handle_digest(self, args: list[str]) -> str:
        payload = self.compat.build_step46_digest()
        if args and args[0].lower() == "raw":
            return json.dumps(payload, indent=2)

        digest = payload.get("digest", {})
        return "\n".join(
            [
                "🧾 Digest",
                f"Execution mode: {digest.get('execution_mode', 'n/a')}",
                f"Active/Retired: {digest.get('active_candidate_count', 'n/a')}/{digest.get('retired_candidate_count', 'n/a')}",
                f"Executor actionable: {digest.get('executor_actionable_now', 'n/a')}",
                f"Blocked by: {', '.join(digest.get('guarded_path_blocked_by', []) or ['none'])}",
            ]
        )

    def _handle_policy(self, _: list[str]) -> str:
        decision = self.executor.policy.evaluate(
            {"market_ticker": "POLICY-CHECK", "side": "YES", "contracts": 1, "max_price_dollars": 0.5}
        )
        reasons = decision.reasons or ["none"]
        advice = []
        if "execution_mode_not_live" in reasons:
            advice.append("set EXECUTION_MODE=live")
        if "live_trading_not_armed" in reasons:
            advice.append("set KALSHI_LIVE_TRADING_ARMED=1")

        return "\n".join(
            [
                "🛡️ Policy Check",
                f"Mode: {decision.mode}",
                f"Approved: {decision.approved}",
                f"Reasons: {', '.join(reasons)}",
                f"For approval: {', '.join(advice) if advice else 'already policy-approved'}",
            ]
        )

    def _auth_get_first_ok(self, paths: list[str]) -> tuple[dict[str, Any] | None, str | None, str | None]:
        client, error = self._with_read_client()
        if client is None:
            return None, f"Read-client unavailable: {error}", None

        try:
            for path in paths:
                try:
                    response = client.auth_get(path)
                    return response.json(), None, path
                except Exception:
                    continue
            return None, f"No supported endpoint from: {', '.join(paths)}", None
        finally:
            client.close()

    def _handle_balance(self, _: list[str]) -> str:
        limits_payload, limits_error, limits_path = self._auth_get_first_ok([
            "/trade-api/v2/account/limits",
        ])
        balance_payload, _, balance_path = self._auth_get_first_ok([
            "/trade-api/v2/account/balance",
            "/trade-api/v2/portfolio/balance",
        ])

        if limits_payload is None and balance_payload is None:
            return f"💼 Account Summary\nUnavailable ({limits_error})."

        merged = {}
        if isinstance(limits_payload, dict):
            merged.update(limits_payload)
        if isinstance(balance_payload, dict):
            merged.update(balance_payload)

        cash = _first(merged, ["cash_balance", "balance", "balance_dollars", "available_cash"]) 
        buying_power = _first(merged, ["buying_power", "buying_power_dollars", "available_buying_power"])
        collateral = _first(merged, ["available_collateral", "collateral", "collateral_dollars"])

        lines = [
            "💼 Account Summary",
            f"Limits endpoint: {limits_path or 'unavailable'}",
            f"Balance endpoint: {balance_path or 'unavailable'}",
            f"Cash balance: {_fmt_money(cash)}",
            f"Buying power: {_fmt_money(buying_power)}",
            f"Available collateral: {_fmt_money(collateral)}",
            f"Read limit: {_fmt_num(_first(merged, ['read_limit']))}",
            f"Write limit: {_fmt_num(_first(merged, ['write_limit']))}",
        ]
        if cash is None and buying_power is None:
            lines.append("Note: monetary balances were not present in the returned endpoint payload.")
        return "\n".join(lines)

    def _extract_list(self, payload: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _hours_to_close(self, close_time: Any) -> float | None:
        if not isinstance(close_time, str) or not close_time:
            return None
        try:
            dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return (dt - now).total_seconds() / 3600.0
        except ValueError:
            return None

    def _evaluate_market_quality(self, market: dict[str, Any]) -> dict[str, Any]:
        prefs: OperatorPreferences = self.preferences
        ticker = str(market.get("ticker", ""))
        title = str(market.get("title", ""))
        status = market.get("status")
        market_type = market.get("market_type")
        yes_bid = _to_float(market.get("yes_bid_dollars"), default=0.0)
        yes_ask = _to_float(market.get("yes_ask_dollars"), default=0.0)
        no_bid = _to_float(market.get("no_bid_dollars"), default=0.0)
        last_price = _to_float(market.get("last_price_dollars"), default=0.0)
        volume = _to_float(market.get("volume_fp"), default=0.0)
        open_interest = _to_float(market.get("open_interest_fp"), default=0.0)
        close_hours = self._hours_to_close(market.get("close_time"))

        lower_ticker = ticker.lower()
        lower_title = title.lower()
        ticker_parts = [p for p in ticker.split("-") if p]
        family_member_flag = (
            ticker.startswith("KX")
            and len(ticker_parts) >= 3
            and len(ticker_parts[-1]) <= 6
            and "," not in title
        )
        title_multi_predicate = (
            title.count(",") >= 2
            or lower_title.count("yes ") >= 2
            or "both teams to score" in lower_title
            or "wins by over" in lower_title
            or " parlay" in lower_title
        )
        pattern_flag = any(p.lower() in lower_ticker for p in prefs.excluded_ticker_patterns) or any(
            p.lower() in lower_title for p in prefs.excluded_title_patterns
        )
        composite_flag = title_multi_predicate or (pattern_flag and not family_member_flag)
        long_title_flag = len(title) > prefs.max_title_length

        quote_live = (0.0 < yes_ask < 1.0) and (0.0 <= yes_bid < yes_ask)
        quote_quality = 0.0
        spread = None
        if quote_live:
            spread = yes_ask - yes_bid
            quote_quality = max(0.0, 1.0 - min(spread, 1.0))
        elif 0.0 < yes_ask < 1.0 or 0.0 < no_bid < 1.0:
            quote_quality = 0.2

        history_signal = volume + open_interest
        history_usable = (0.0 < last_price < 1.0) or (history_signal >= prefs.min_history_signal)
        weak_history = history_signal < (prefs.min_volume + prefs.min_open_interest) and last_price == 0.0

        score_parts: dict[str, float] = {
            "base_active_binary": 40.0 if (status == "active" and market_type == "binary") else -100.0,
            "quote_quality": quote_quality * 40.0,
            "volume_quality": min(volume, 2000.0) / 80.0,
            "open_interest_quality": min(open_interest, 2000.0) / 70.0,
            "price_sanity": 10.0 if 0.0 < last_price < 1.0 else -5.0,
        }
        penalties: dict[str, float] = {}

        if composite_flag:
            penalties["composite_market"] = prefs.penalize_composite
        if long_title_flag:
            penalties["low_interpretability"] = prefs.penalize_low_interpretability
        if quote_quality < prefs.min_quote_quality:
            penalties["no_or_weak_live_quote"] = prefs.penalize_no_live_quote
        if close_hours is not None and close_hours < prefs.min_close_hours:
            penalties["too_close_to_expiry"] = prefs.penalize_too_close
        if close_hours is not None and close_hours > prefs.max_close_hours:
            penalties["too_far_to_expiry"] = prefs.penalize_too_far
        if weak_history:
            penalties["weak_history_signal"] = prefs.penalize_weak_signal

        score = sum(score_parts.values()) - sum(penalties.values())

        eligible = (
            status == "active"
            and market_type == "binary"
            and history_usable
            and (quote_quality >= prefs.min_quote_quality or history_signal >= (prefs.min_volume + prefs.min_open_interest))
        )

        reasons = []
        if composite_flag:
            reasons.append("composite/extended pattern")
        if long_title_flag:
            reasons.append("long/unreadable title")
        if not history_usable:
            reasons.append("no usable history signal")
        if quote_quality < prefs.min_quote_quality:
            reasons.append("weak quote quality")
        if close_hours is not None and close_hours < prefs.min_close_hours:
            reasons.append("too close to close time")

        return {
            "eligible": eligible,
            "score": round(score, 4),
            "score_parts": score_parts,
            "penalties": penalties,
            "quote_quality": round(quote_quality, 4),
            "spread": spread,
            "history_signal": round(history_signal, 2),
            "composite_flag": composite_flag,
            "family_member_flag": family_member_flag,
            "long_title_flag": long_title_flag,
            "close_hours": close_hours,
            "reasons": reasons,
        }

    def _normalize_identifier(self, raw: str) -> str:
        value = raw.strip()
        if value.startswith("http://") or value.startswith("https://"):
            parsed = urlparse(value)
            segments = [s for s in parsed.path.split("/") if s]
            for segment in reversed(segments):
                candidate = segment.strip()
                if candidate and candidate not in {"markets", "event", "events"}:
                    return candidate.upper()
        return value.upper()

    def _looks_market_like(self, identifier: str) -> bool:
        value = identifier.upper()
        return value.startswith("KX") and "-" in value

    def _cached_similar_matches(self, identifier: str) -> list[str]:
        key = re.sub(r"[^A-Z0-9]", "", identifier.upper())
        cached = self._load_cached_recommendation()
        candidates = cached.get("candidates") or []
        matches = []
        for c in candidates:
            ticker = str(c.get("ticker", ""))
            title = str(c.get("title", ""))
            searchable = re.sub(r"[^A-Z0-9]", "", f"{ticker} {title}".upper())
            if key and key in searchable:
                matches.append(ticker)
        return matches[:5]

    def _resolve_market_or_event(self, raw_identifier: str) -> dict[str, Any]:
        ident = self._normalize_identifier(raw_identifier)
        attempts: list[str] = []
        cached_matches = self._cached_similar_matches(ident)
        client, error = self._with_read_client()
        if client is None:
            return {"identifier": ident, "attempts": attempts, "error": f"read_client_unavailable: {error}", "cached_matches": cached_matches}

        try:
            if self._looks_market_like(ident):
                attempts.append("market_direct")
                try:
                    market_payload = fetch_market_by_ticker(client, ident)
                    market = market_payload.get("market", market_payload)
                    if isinstance(market, dict) and market.get("ticker"):
                        return {
                            "identifier": ident,
                            "attempts": attempts,
                            "kind": "market",
                            "market": market,
                            "cached_matches": cached_matches,
                        }
                except Exception:
                    pass

            attempts.append("event_direct")
            try:
                event_payload = fetch_event_by_ticker(client, ident, with_nested_markets=True)
                event = event_payload.get("event", event_payload)
                if isinstance(event, dict) and (event.get("event_ticker") or event.get("ticker")):
                    markets = event_payload.get("markets") if isinstance(event_payload.get("markets"), list) else []
                    return {
                        "identifier": ident,
                        "attempts": attempts,
                        "kind": "event",
                        "event": event,
                        "markets": markets,
                        "cached_matches": cached_matches,
                    }
            except Exception:
                pass

            attempts.append("recent_scan_substring_search")
            top, _, _ = self._fetch_markets_with_diagnostics_mode(mode="broad", pages=3, limit_per_page=80)
            if top:
                normalized = re.sub(r"[^A-Z0-9]", "", ident)
                for market in top:
                    ticker = str(market.get("ticker", ""))
                    event_ticker = str(market.get("event_ticker", ""))
                    title = str(market.get("title", ""))
                    blob = re.sub(r"[^A-Z0-9]", "", f"{ticker} {event_ticker} {title}".upper())
                    if normalized and normalized in blob:
                        return {
                            "identifier": ident,
                            "attempts": attempts,
                            "kind": "market",
                            "market": market,
                            "cached_matches": cached_matches,
                            "inferred_from_scan": True,
                        }
        finally:
            client.close()

        return {"identifier": ident, "attempts": attempts, "kind": "unknown", "cached_matches": cached_matches}

    def _expand_event_children(self, event_identifier: str, event_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        direct = event_payload.get("markets") if isinstance(event_payload.get("markets"), list) else []
        if direct:
            return [m for m in direct if isinstance(m, dict)], "event_nested_markets"

        client, error = self._with_read_client()
        if client is None:
            return [], f"no_read_client:{error}"
        try:
            attempts = [
                {"event_ticker": event_identifier, "limit": 100},
                {"series_ticker": event_payload.get("series_ticker"), "limit": 100},
            ]
            for params in attempts:
                params = {k: v for k, v in params.items() if v}
                if not params:
                    continue
                try:
                    payload = client.public_get("/trade-api/v2/markets", params=params).json()
                    markets = payload.get("markets") if isinstance(payload.get("markets"), list) else []
                    if markets:
                        filtered = []
                        for m in markets:
                            if not isinstance(m, dict):
                                continue
                            if m.get("event_ticker") == event_identifier or not event_identifier:
                                filtered.append(m)
                        return (filtered or markets), f"markets_endpoint_query:{params}"
                except Exception:
                    continue
        finally:
            client.close()

        # broad scan inference fallback
        inferred, _, _ = self._fetch_markets_with_diagnostics_mode(mode="broad", pages=4, limit_per_page=120)
        slug_key = re.sub(r"[^A-Z0-9]", "", event_identifier.upper())
        matches: list[dict[str, Any]] = []
        for m in inferred:
            if not isinstance(m, dict):
                continue
            blob = re.sub(
                r"[^A-Z0-9]",
                "",
                f"{m.get('event_ticker', '')} {m.get('ticker', '')} {m.get('title', '')}".upper(),
            )
            if slug_key and slug_key in blob:
                matches.append(m)
        if matches:
            return matches[:20], "broad_scan_inference"
        return [], "no_children_found"

    def _seed_markets_from_recent_events(self, max_events: int = 12) -> list[dict[str, Any]]:
        client, error = self._with_read_client()
        if client is None:
            return []
        collected: dict[str, dict[str, Any]] = {}
        try:
            payload = client.public_get("/trade-api/v2/events", params={"limit": max_events}).json()
            events = payload.get("events") if isinstance(payload.get("events"), list) else []
            for event in events[:max_events]:
                if not isinstance(event, dict):
                    continue
                event_ticker = event.get("event_ticker") or event.get("ticker")
                if not event_ticker:
                    continue
                try:
                    expanded = fetch_event_by_ticker(client, str(event_ticker), with_nested_markets=True)
                    markets = expanded.get("markets") if isinstance(expanded.get("markets"), list) else []
                    for market in markets:
                        if isinstance(market, dict) and market.get("ticker"):
                            collected[market["ticker"]] = market
                except Exception:
                    continue
        except Exception:
            return []
        finally:
            client.close()
        return list(collected.values())

    def _handle_positions(self, _: list[str]) -> str:
        payload, error, path = self._auth_get_first_ok([
            "/trade-api/v2/portfolio/positions",
            "/trade-api/v2/positions",
        ])
        if payload is None:
            return f"📌 Positions\nUnavailable ({error})."

        positions = self._extract_list(payload, ["positions", "market_positions", "portfolio_positions"])
        if not positions:
            return f"📌 Positions\nEndpoint {path} returned no position list."

        lines = [f"📌 Positions (top {min(10, len(positions))}) from {path}:"]
        for pos in positions[:10]:
            ticker = _first(pos, ["ticker", "market_ticker", "market"])
            side = _first(pos, ["side", "position_side", "direction"], default="n/a")
            qty = _first(pos, ["quantity", "position", "contracts", "count"], default="n/a")
            avg_price = _first(pos, ["avg_price", "average_price", "cost_basis", "entry_price"]) 
            mark = _first(pos, ["mark_price", "last_price", "mark", "current_price"]) 
            unrealized = _first(pos, ["unrealized_pnl", "unrealized_profit_loss", "u_pnl"]) 
            lines.append(
                f"• {ticker or 'unknown'} | side={side} | qty={qty} | avg={_fmt_money(avg_price)} | "
                f"mark={_fmt_money(mark)} | uPnL={_fmt_money(unrealized)}"
            )
        lines.append("If values show n/a, those fields are not provided by the current endpoint payload.")
        return "\n".join(lines)

    def _handle_orders(self, _: list[str]) -> str:
        payload, error, path = self._auth_get_first_ok([
            "/trade-api/v2/portfolio/orders",
            "/trade-api/v2/orders",
        ])
        if payload is None:
            return f"🧾 Orders\nUnavailable ({error})."

        orders = self._extract_list(payload, ["orders", "open_orders", "recent_orders"])
        if not orders:
            return f"🧾 Orders\nEndpoint {path} returned no order list."

        lines = [f"🧾 Orders (top {min(10, len(orders))}) from {path}:"]
        for order in orders[:10]:
            ticker = _first(order, ["ticker", "market_ticker", "market"])
            side = _first(order, ["side", "action", "direction"], default="n/a")
            status = _first(order, ["status", "order_status"], default="n/a")
            qty = _first(order, ["quantity", "count", "contracts"], default="n/a")
            filled = _first(order, ["filled_quantity", "filled_count", "matched_count"], default="n/a")
            limit_price = _first(order, ["limit_price", "price", "price_dollars"]) 
            created = _first(order, ["created_time", "created_at", "timestamp"], default="n/a")
            lines.append(
                f"• {ticker or 'unknown'} | {side} | {status} | qty={qty} filled={filled} "
                f"| limit={_fmt_money(limit_price)} | created={created}"
            )
        lines.append("If values show n/a, those fields are not provided by the current endpoint payload.")
        return "\n".join(lines)

    def _fetch_markets_with_diagnostics(self, pages: int = 6, limit_per_page: int = 100) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
        return self._fetch_markets_with_diagnostics_mode(mode=self.preferences.default_scan_mode, pages=pages, limit_per_page=limit_per_page)

    def _fetch_markets_with_diagnostics_mode(self, mode: str, pages: int = 6, limit_per_page: int = 100) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
        scan_mode = (mode or "strict").lower()
        client, error = self._with_read_client()
        if client is None:
            return [], {}, f"Read-client unavailable: {error}"

        by_ticker: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        diag_counter = Counter()
        pages_scanned = 0

        try:
            for _ in range(pages):
                params: dict[str, Any] = {"limit": limit_per_page}
                if cursor:
                    params["cursor"] = cursor

                response = client.public_get("/trade-api/v2/markets", params=params)
                payload = response.json()
                markets = payload.get("markets", []) if isinstance(payload.get("markets"), list) else []

                pages_scanned += 1
                diag_counter["markets_fetched"] += len(markets)

                for market in markets:
                    ticker = market.get("ticker")
                    if ticker:
                        by_ticker[ticker] = market

                cursor = payload.get("cursor")
                if not cursor:
                    break

            candidates = []
            rejection_reasons: Counter[str] = Counter()

            for market in by_ticker.values():
                if market.get("status") == "active":
                    diag_counter["active_markets"] += 1
                else:
                    rejection_reasons["non_active_status"] += 1
                    continue

                if market.get("market_type") == "binary":
                    diag_counter["binary_markets"] += 1
                else:
                    rejection_reasons["non_binary_market"] += 1
                    continue

                quality = self._evaluate_market_quality(market)
                if quality["quote_quality"] >= self.preferences.min_quote_quality:
                    diag_counter["quote_usable"] += 1
                if quality["history_signal"] >= self.preferences.min_history_signal:
                    diag_counter["history_usable"] += 1

                category = str(market.get("category", "")).lower()
                if scan_mode == "strict":
                    if self.preferences.strict_scan_exclude_composite and quality["composite_flag"]:
                        if quality.get("family_member_flag"):
                            rejection_reasons["event_child_excluded_as_composite"] += 1
                        else:
                            rejection_reasons["true_composite_excluded"] += 1
                        rejection_reasons["strict_universe_composite_excluded"] += 1
                        continue
                    if self.preferences.strict_scan_require_interpretable_title and quality["long_title_flag"]:
                        rejection_reasons["strict_universe_unreadable_title"] += 1
                        continue
                    if self.preferences.strict_scan_preferred_categories and category not in [c.lower() for c in self.preferences.strict_scan_preferred_categories]:
                        rejection_reasons["strict_universe_non_preferred_category"] += 1
                        continue
                    if self.preferences.strict_scan_excluded_categories and category in [c.lower() for c in self.preferences.strict_scan_excluded_categories]:
                        rejection_reasons["strict_universe_excluded_category"] += 1
                        continue

                if not quality["eligible"]:
                    if quality.get("family_member_flag"):
                        rejection_reasons["event_child_excluded_other_reasons"] += 1
                    for reason in quality["reasons"]:
                        rejection_reasons[reason] += 1
                    continue

                if quality.get("family_member_flag"):
                    diag_counter["event_child_allowed"] += 1

                ranked = dict(market)
                ranked["scan_score"] = quality["score"]
                ranked["scan_score_parts"] = quality["score_parts"]
                ranked["scan_penalties"] = quality["penalties"]
                ranked["scan_quote_quality"] = quality["quote_quality"]
                ranked["scan_close_hours"] = quality["close_hours"]
                ranked["scan_composite_flag"] = quality["composite_flag"]
                ranked["scan_family_member_flag"] = quality.get("family_member_flag")
                ranked["scan_rationale"] = (
                    f"quote_q={quality['quote_quality']:.2f}, history={quality['history_signal']:.1f}, "
                    f"penalties={','.join(quality['penalties'].keys()) or 'none'}"
                )
                candidates.append(ranked)

            if scan_mode == "strict" and len(candidates) < 3:
                seeded = self._seed_markets_from_recent_events(max_events=15)
                for market in seeded:
                    ticker = market.get("ticker")
                    if not ticker or ticker in by_ticker:
                        continue
                    by_ticker[ticker] = market
                    quality = self._evaluate_market_quality(market)
                    if self.preferences.strict_scan_exclude_composite and quality["composite_flag"]:
                        rejection_reasons["strict_universe_composite_excluded"] += 1
                        continue
                    if not quality["eligible"]:
                        rejection_reasons["seeded_event_market_ineligible"] += 1
                        continue
                    ranked = dict(market)
                    ranked["scan_score"] = quality["score"]
                    ranked["scan_score_parts"] = quality["score_parts"]
                    ranked["scan_penalties"] = quality["penalties"]
                    ranked["scan_quote_quality"] = quality["quote_quality"]
                    ranked["scan_close_hours"] = quality["close_hours"]
                    ranked["scan_composite_flag"] = quality["composite_flag"]
                    ranked["scan_family_member_flag"] = quality.get("family_member_flag")
                    ranked["scan_rationale"] = (
                        f"quote_q={quality['quote_quality']:.2f}, history={quality['history_signal']:.1f}, "
                        f"penalties={','.join(quality['penalties'].keys()) or 'none'}, source=event_seed"
                    )
                    candidates.append(ranked)
                diag_counter["seeded_event_markets"] += len(seeded)

            candidates.sort(
                key=lambda item: (
                    item.get("scan_score", 0.0),
                    item.get("scan_quote_quality", 0.0),
                    _to_float(item.get("open_interest_fp")),
                ),
                reverse=True,
            )

            diagnostics = {
                "pages_scanned": pages_scanned,
                "cursor_exhausted": cursor is None,
                "markets_fetched": diag_counter["markets_fetched"],
                "deduped_markets": len(by_ticker),
                "active_markets": diag_counter["active_markets"],
                "binary_markets": diag_counter["binary_markets"],
                "quote_usable": diag_counter["quote_usable"],
                "history_usable": diag_counter["history_usable"],
                "event_child_allowed": diag_counter["event_child_allowed"],
                "final_candidate_count": len(candidates),
                "top_rejections": rejection_reasons.most_common(3),
                "rejection_counts": dict(rejection_reasons),
                "scan_mode": scan_mode,
                "preference_summary": {
                    "min_quote_quality": self.preferences.min_quote_quality,
                    "min_close_hours": self.preferences.min_close_hours,
                    "max_close_hours": self.preferences.max_close_hours,
                    "min_recommendation_score": self.preferences.min_recommendation_score,
                    "strict_scan_exclude_composite": self.preferences.strict_scan_exclude_composite,
                    "strict_scan_require_interpretable_title": self.preferences.strict_scan_require_interpretable_title,
                },
            }
            return candidates[:12], diagnostics, None
        except Exception as exc:  # noqa: BLE001
            return [], {}, str(exc)
        finally:
            client.close()

    def _persist_candidates(
        self,
        candidates: list[dict[str, Any]],
        recommendation: dict[str, Any] | None,
        diagnostics: dict[str, Any] | None,
    ) -> None:
        self.state.write_json(
            "runtime/recommendation_state.json",
            {
                "ts": utc_now_iso(),
                "candidates": candidates,
                "recommendation": recommendation,
                "diagnostics": diagnostics or {},
            },
        )

    def _load_cached_recommendation(self) -> dict[str, Any]:
        return self.state.read_json("runtime/recommendation_state.json", default={})

    def _format_candidate_line(self, c: dict[str, Any], idx: int) -> str:
        penalties = c.get("scan_penalties", {})
        penalty_names = ",".join(penalties.keys()) if isinstance(penalties, dict) and penalties else "none"
        return (
            f"{idx}. {c.get('ticker', 'n/a')} | score={_fmt_num(c.get('scan_score'))} | "
            f"quote_q={_fmt_num(c.get('scan_quote_quality'))} | "
            f"last={_fmt_money(c.get('last_price_dollars'))} | close_h={_fmt_num(c.get('scan_close_hours'))} | "
            f"penalties={penalty_names}"
        )

    def _parse_scan_mode(self, args: list[str]) -> str:
        if args and args[0].lower() in {"broad", "debug"}:
            return "broad"
        return self.preferences.default_scan_mode

    def _handle_markets(self, args: list[str]) -> str:
        mode = self._parse_scan_mode(args)
        candidates, diagnostics, error = self._fetch_markets_with_diagnostics_mode(mode=mode)
        if error:
            return f"📈 Market Scan\nUnavailable ({error})."
        if not candidates:
            return "📈 Market Scan\nNo candidates returned. Use /scanstatus for diagnostics."

        lines = [
            "📈 Top Markets",
            f"Mode: {diagnostics.get('scan_mode', mode)} | Candidates: {len(candidates)} | Fetched: {diagnostics.get('markets_fetched', 'n/a')} | Pages: {diagnostics.get('pages_scanned', 'n/a')}",
        ]
        for idx, c in enumerate(candidates[:8]):
            lines.append(self._format_candidate_line(c, idx + 1))
            lines.append(f"   ↳ {c.get('title', 'n/a')}")
            lines.append(f"   ↳ why: {c.get('scan_rationale', 'n/a')}")
        return "\n".join(lines)

    def _handle_scan_debug(self, _: list[str]) -> str:
        return self._handle_markets(["broad"])

    def _handle_scanprefs(self, _: list[str]) -> str:
        return "\n".join(
            [
                "🧭 Universe Preferences",
                f"default_scan_mode: {self.preferences.default_scan_mode}",
                f"strict_scan_exclude_composite: {self.preferences.strict_scan_exclude_composite}",
                f"strict_scan_require_interpretable_title: {self.preferences.strict_scan_require_interpretable_title}",
                f"strict_scan_max_title_length: {self.preferences.strict_scan_max_title_length}",
                f"strict_scan_preferred_categories: {self.preferences.strict_scan_preferred_categories or ['none']}",
                f"strict_scan_excluded_categories: {self.preferences.strict_scan_excluded_categories or ['none']}",
                "composite classifier scope: contract-level multi-predicate/bundled detection (not merely event-family membership)",
                f"min_quote_quality: {self.preferences.min_quote_quality}",
                f"recommendation gate: min_score={self.preferences.min_recommendation_score}, "
                f"require_live_quote={self.preferences.require_live_quote_for_recommendation}, "
                f"exclude_composite={self.preferences.exclude_composite_for_recommendation}",
            ]
        )

    def _handle_scanstatus(self, args: list[str]) -> str:
        mode = self._parse_scan_mode(args)
        candidates, diagnostics, error = self._fetch_markets_with_diagnostics_mode(mode=mode)
        if error:
            return f"🩺 Scan Diagnostics\nFailed ({error})."

        top_rej = diagnostics.get("top_rejections", [])
        rej_text = ", ".join(f"{name}:{count}" for name, count in top_rej) if top_rej else "none"
        rej = diagnostics.get("rejection_counts", {})
        return "\n".join(
            [
                "🩺 Scan Diagnostics",
                f"Scan mode: {diagnostics.get('scan_mode', mode)}",
                f"Markets fetched: {diagnostics.get('markets_fetched', 0)}",
                f"Pages scanned: {diagnostics.get('pages_scanned', 0)}",
                f"Active markets: {diagnostics.get('active_markets', 0)}",
                f"Binary markets: {diagnostics.get('binary_markets', 0)}",
                f"Quote-usable: {diagnostics.get('quote_usable', 0)}",
                f"History-usable: {diagnostics.get('history_usable', 0)}",
                f"Event child markets allowed: {diagnostics.get('event_child_allowed', 0)}",
                f"Final candidates: {diagnostics.get('final_candidate_count', len(candidates))}",
                f"Top rejection reasons: {rej_text}",
                f"Excluded by universe: {rej.get('strict_universe_composite_excluded', 0) + rej.get('strict_universe_unreadable_title', 0) + rej.get('strict_universe_non_preferred_category', 0) + rej.get('strict_universe_excluded_category', 0)}",
                f"True composite excluded: {rej.get('true_composite_excluded', 0)}",
                f"Event-child excluded as composite: {rej.get('event_child_excluded_as_composite', 0)}",
                f"Event-child excluded other reasons: {rej.get('event_child_excluded_other_reasons', 0)}",
                f"Excluded by composite flag: {rej.get('composite/extended pattern', 0) + rej.get('strict_universe_composite_excluded', 0)}",
                f"Excluded by weak quote: {rej.get('weak quote quality', 0)}",
                f"Excluded by close-time filter: {rej.get('too close to close time', 0)}",
                f"Prefs: min_quote={diagnostics.get('preference_summary', {}).get('min_quote_quality', 'n/a')}, "
                f"close_hours=[{diagnostics.get('preference_summary', {}).get('min_close_hours', 'n/a')},"
                f"{diagnostics.get('preference_summary', {}).get('max_close_hours', 'n/a')}]",
            ]
        )

    def _handle_market(self, args: list[str]) -> str:
        if not args:
            return "Usage: /market <MARKET_TICKER>"
        resolved = self._resolve_market_or_event(args[0])
        if resolved.get("kind") == "market":
            market = resolved.get("market", {})
            quality = self._evaluate_market_quality(market if isinstance(market, dict) else {})
            score_parts = quality.get("score_parts", {})
            penalties = quality.get("penalties", {})
            return "\n".join(
                [
                    f"🔎 Market {market.get('ticker', resolved.get('identifier', 'n/a'))}",
                    f"Title: {market.get('title', 'n/a')}",
                    f"Event: {market.get('event_ticker', 'n/a')}",
                    f"Status: {market.get('status', 'n/a')}",
                    f"Market type: {market.get('market_type', 'n/a')}",
                    f"YES bid/ask: {_fmt_money(market.get('yes_bid_dollars'))} / {_fmt_money(market.get('yes_ask_dollars'))}",
                    f"NO bid/ask: {_fmt_money(market.get('no_bid_dollars'))} / {_fmt_money(market.get('no_ask_dollars'))}",
                    f"Last: {_fmt_money(market.get('last_price_dollars'))}",
                    f"Volume: {_fmt_num(market.get('volume_fp'))} | OI: {_fmt_num(market.get('open_interest_fp'))}",
                    f"Close time: {market.get('close_time', 'n/a')} (hours_to_close={_fmt_num(quality.get('close_hours'))})",
                    f"Composite flag: {quality.get('composite_flag')} | Eligible: {quality.get('eligible')}",
                    f"Score: {_fmt_num(quality.get('score'))}",
                    f"Score parts: {', '.join(f'{k}={v:.1f}' for k, v in score_parts.items())}",
                    f"Penalties: {', '.join(f'{k}={v:.1f}' for k, v in penalties.items()) if penalties else 'none'}",
                ]
            )

        if resolved.get("kind") == "event":
            event = resolved.get("event", {})
            markets, source = self._expand_event_children(
                str(event.get("event_ticker", event.get("ticker", resolved.get("identifier", "")))),
                {"markets": resolved.get("markets", []), **(event if isinstance(event, dict) else {})},
            )
            lines = [
                f"ℹ️ '{resolved.get('identifier')}' appears to be an event-like identifier, not a direct market ticker.",
                f"Event: {event.get('event_ticker', event.get('ticker', 'n/a'))}",
                f"Title: {event.get('title', 'n/a')}",
                f"Event status: {event.get('status', event.get('event_status', 'n/a'))}",
                f"Event close: {event.get('close_time', event.get('expiration_time', 'n/a'))}",
                f"Child source: {source}",
                "Use /event <IDENTIFIER> for event view, or pick a child market ticker below:",
            ]
            for m in markets[:6]:
                lines.append(f"• {m.get('ticker', 'n/a')} — {m.get('title', 'n/a')}")
            return "\n".join(lines)

        return "\n".join(
            [
                "🔎 Market lookup failed to resolve identifier.",
                f"Input normalized as: {resolved.get('identifier', 'n/a')}",
                f"Tried: {', '.join(resolved.get('attempts', []) or ['none'])}",
                f"Likely type guess: {'market-like' if self._looks_market_like(resolved.get('identifier', '')) else 'event/slug-like'}",
                f"Similar cached matches: {', '.join(resolved.get('cached_matches', []) or ['none'])}",
                "Tip: try /event <IDENTIFIER> or /markets and copy a listed ticker.",
            ]
        )

    def _handle_event(self, args: list[str]) -> str:
        if not args:
            return "Usage: /event <EVENT_TICKER>"
        resolved = self._resolve_market_or_event(args[0])

        if resolved.get("kind") == "event":
            event = resolved.get("event", {})
            markets, source = self._expand_event_children(
                str(event.get("event_ticker", event.get("ticker", resolved.get("identifier", "")))),
                {"markets": resolved.get("markets", []), **(event if isinstance(event, dict) else {})},
            )
            lines = [
                f"🗂️ Event {event.get('event_ticker', event.get('ticker', resolved.get('identifier', 'n/a')))}",
                f"Title: {event.get('title', 'n/a')}",
                f"Status: {event.get('status', event.get('event_status', 'n/a'))}",
                f"Close time: {event.get('close_time', event.get('expiration_time', 'n/a'))}",
                f"Child markets: {len(markets)} (source={source})",
                "Use these tickers with /market or /review:",
            ]
            for m in markets[:8]:
                lines.append(
                    f"• {m.get('ticker', 'n/a')} — {m.get('title', 'n/a')} "
                    f"(last={_fmt_money(m.get('last_price_dollars'))}, yes_ask={_fmt_money(m.get('yes_ask_dollars'))})"
                )
            return "\n".join(lines)

        if resolved.get("kind") == "market":
            market = resolved.get("market", {})
            return "\n".join(
                [
                    f"ℹ️ '{resolved.get('identifier')}' resolved to market ticker {market.get('ticker', 'n/a')}, not event.",
                    f"Related event ticker: {market.get('event_ticker', 'n/a')}",
                    "Tip: run /market <ticker> for market details.",
                ]
            )

        return "\n".join(
            [
                "🗂️ Event lookup failed to resolve identifier.",
                f"Input normalized as: {resolved.get('identifier', 'n/a')}",
                f"Tried: {', '.join(resolved.get('attempts', []) or ['none'])}",
                f"Similar cached matches: {', '.join(resolved.get('cached_matches', []) or ['none'])}",
                "Tip: paste a Kalshi event URL or run /markets to discover related tickers.",
            ]
        )

    def _rank_event_children(self, markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        for market in markets:
            if not isinstance(market, dict):
                continue
            quality = self._evaluate_market_quality(market)
            if market.get("status") != "active" or market.get("market_type") != "binary":
                continue
            scored = dict(market)
            scored["scan_score"] = quality["score"]
            scored["scan_quote_quality"] = quality["quote_quality"]
            scored["scan_penalties"] = quality["penalties"]
            scored["scan_rationale"] = (
                f"quote_q={quality['quote_quality']:.2f}, history={quality['history_signal']:.1f}, "
                f"penalties={','.join(quality['penalties'].keys()) or 'none'}"
            )
            scored["scan_composite_flag"] = quality["composite_flag"]
            ranked.append(scored)
        ranked.sort(key=lambda m: (m.get("scan_score", 0.0), m.get("scan_quote_quality", 0.0)), reverse=True)
        return ranked

    def _handle_event_candidates(self, args: list[str]) -> str:
        if not args:
            return "Usage: /event_candidates <EVENT_OR_URL>"
        resolved = self._resolve_market_or_event(" ".join(args))
        if resolved.get("kind") != "event":
            return "Could not resolve event. Try /event <IDENTIFIER> first."
        event = resolved.get("event", {})
        event_id = str(event.get("event_ticker", event.get("ticker", resolved.get("identifier", ""))))
        markets, source = self._expand_event_children(event_id, {"markets": resolved.get("markets", []), **(event if isinstance(event, dict) else {})})
        ranked = self._rank_event_children(markets)
        if not ranked:
            return f"No rankable child markets found for event {event_id} (source={source})."
        lines = [f"🎯 Event Candidates {event_id} (source={source})"]
        for i, m in enumerate(ranked[:5]):
            lines.append(self._format_candidate_line(m, i + 1))
            lines.append(f"   ↳ {m.get('title', 'n/a')}")
        return "\n".join(lines)

    def _handle_event_recommend(self, args: list[str]) -> str:
        if not args:
            return "Usage: /event_recommend <EVENT_OR_URL>"
        resolved = self._resolve_market_or_event(" ".join(args))
        if resolved.get("kind") != "event":
            return "Could not resolve event. Try /event <IDENTIFIER> first."
        event = resolved.get("event", {})
        event_id = str(event.get("event_ticker", event.get("ticker", resolved.get("identifier", ""))))
        markets, source = self._expand_event_children(event_id, {"markets": resolved.get("markets", []), **(event if isinstance(event, dict) else {})})
        ranked = self._rank_event_children(markets)
        if not ranked:
            return f"No acceptable event child market candidates for {event_id} (source={source})."

        winner = None
        for candidate in ranked:
            score = _to_float(candidate.get("scan_score"))
            quote_q = _to_float(candidate.get("scan_quote_quality"))
            if score < self.preferences.min_recommendation_score:
                continue
            if self.preferences.require_live_quote_for_recommendation and quote_q < self.preferences.min_quote_quality:
                continue
            if self.preferences.exclude_composite_for_recommendation and candidate.get("scan_composite_flag"):
                continue
            winner = candidate
            break
        if winner is None:
            return f"No acceptable dry-run event recommendation right now for {event_id}."

        max_price = _to_float(winner.get("yes_ask_dollars"), default=0.5)
        if not (0.0 < max_price < 1.0):
            max_price = min(0.95, max(0.05, _to_float(winner.get("last_price_dollars"), default=0.5)))
        review = self.executor.review(
            TradeIntent(
                market_ticker=str(winner.get("ticker", "UNKNOWN")),
                side="YES",
                contracts=1,
                max_price_dollars=max_price,
                rationale=f"event_scoped_recommendation:{event_id}",
            )
        )
        payload = {
            "market_ticker": winner.get("ticker"),
            "title": winner.get("title"),
            "scan_score": winner.get("scan_score"),
            "scan_rationale": winner.get("scan_rationale"),
            "scan_penalties": winner.get("scan_penalties", {}),
            "proposed_side": "YES",
            "proposed_contracts": 1,
            "proposed_max_price_dollars": max_price,
            "executor_review": review.__dict__,
        }
        return f"Event source={source}\n" + self._format_recommendation(payload)

    def _generate_recommendation(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any], str | None]:
        candidates, diagnostics, error = self._fetch_markets_with_diagnostics()
        if error:
            return None, [], diagnostics, error
        if not candidates:
            self._persist_candidates([], None, diagnostics)
            return None, [], diagnostics, "No candidates available from current scan."

        winner = None
        for candidate in candidates:
            score = _to_float(candidate.get("scan_score"))
            quote_q = _to_float(candidate.get("scan_quote_quality"))
            composite = bool(candidate.get("scan_composite_flag"))
            if score < self.preferences.min_recommendation_score:
                continue
            if self.preferences.require_live_quote_for_recommendation and quote_q < self.preferences.min_quote_quality:
                continue
            if self.preferences.exclude_composite_for_recommendation and composite:
                continue
            winner = candidate
            break

        if winner is None:
            self._persist_candidates(candidates, None, diagnostics)
            return None, candidates, diagnostics, "No acceptable dry-run recommendation right now."

        quoted = _to_float(winner.get("yes_ask_dollars"), default=0.0)
        last = _to_float(winner.get("last_price_dollars"), default=0.5)
        chosen_price = quoted if 0.0 < quoted < 1.0 else min(0.95, max(0.05, last))

        review = self.executor.review(
            TradeIntent(
                market_ticker=winner.get("ticker", "UNKNOWN"),
                side="YES",
                contracts=1,
                max_price_dollars=float(chosen_price),
                rationale=f"dry_run_top_scan_candidate ({winner.get('scan_rationale', 'n/a')})",
            )
        )
        recommendation = {
            "market_ticker": winner.get("ticker"),
            "event_ticker": winner.get("event_ticker"),
            "title": winner.get("title"),
            "scan_score": winner.get("scan_score"),
            "scan_rationale": winner.get("scan_rationale"),
            "scan_penalties": winner.get("scan_penalties", {}),
            "proposed_side": "YES",
            "proposed_contracts": 1,
            "proposed_max_price_dollars": chosen_price,
            "executor_review": review.__dict__,
            "generated_at": utc_now_iso(),
            "rationale": "Top ranked market from read-only scan; reviewed via executor policy.",
            "quality_gate": {
                "min_score": self.preferences.min_recommendation_score,
                "require_live_quote": self.preferences.require_live_quote_for_recommendation,
                "exclude_composite": self.preferences.exclude_composite_for_recommendation,
            },
        }
        self._persist_candidates(candidates, recommendation, diagnostics)
        return recommendation, candidates, diagnostics, None

    def _format_recommendation(self, recommendation: dict[str, Any]) -> str:
        review = recommendation.get("executor_review", {})
        reasons = review.get("policy_reasons") or ["none"]
        penalties = recommendation.get("scan_penalties", {})
        guidance = []
        if "execution_mode_not_live" in reasons:
            guidance.append("set EXECUTION_MODE=live")
        if "live_trading_not_armed" in reasons:
            guidance.append("set KALSHI_LIVE_TRADING_ARMED=1")
        return "\n".join(
            [
                "🎯 Dry-Run Recommendation",
                f"Market: {recommendation.get('market_ticker', 'n/a')} ({recommendation.get('title', 'n/a')})",
                f"Side/Contracts: {recommendation.get('proposed_side')} x {recommendation.get('proposed_contracts')}",
                f"Max price: {_fmt_money(recommendation.get('proposed_max_price_dollars'))}",
                f"Score: {_fmt_num(recommendation.get('scan_score'))} | Why: {recommendation.get('scan_rationale', 'n/a')}",
                f"Candidate penalties: {', '.join(penalties.keys()) if penalties else 'none'}",
                f"Executor result: {'APPROVED' if review.get('approved') else 'BLOCKED'} (dry_run={review.get('dry_run')})",
                f"Policy reasons: {', '.join(reasons)}",
                f"To approve: {', '.join(guidance) if guidance else 'already policy-approved'}",
            ]
        )

    def _handle_refresh(self, _: list[str]) -> str:
        recommendation, candidates, diagnostics, error = self._generate_recommendation()
        if error:
            return (
                f"🔄 Refresh\nFailed ({error}).\n"
                f"Scan diagnostics: fetched={diagnostics.get('markets_fetched', 0)} candidates={diagnostics.get('final_candidate_count', 0)}"
            )
        return (
            f"🔄 Refresh complete: {len(candidates)} candidates ranked across {diagnostics.get('pages_scanned', 0)} pages.\n"
            + self._format_recommendation(recommendation or {})
        )

    def _handle_candidates(self, _: list[str]) -> str:
        cached = self._load_cached_recommendation()
        candidates = cached.get("candidates") or []
        if not candidates:
            return "🗂️ Candidates\nNo cached candidates yet. Run /refresh or /recommend first."

        lines = ["🗂️ Top Cached Candidates (3):"]
        lines.extend(self._format_candidate_line(c, idx + 1) for idx, c in enumerate(candidates[:3]))
        return "\n".join(lines)

    def _handle_why_nexttrade(self, _: list[str]) -> str:
        cached = self._load_cached_recommendation()
        candidates = cached.get("candidates") or []
        recommendation = cached.get("recommendation")
        if not candidates:
            return "🧠 Why Next Trade\nNo cached candidates. Run /refresh first."

        lines = ["🧠 Why Next Trade (top 3 comparison)"]
        lines.append(
            f"Gate: min_score={self.preferences.min_recommendation_score}, "
            f"require_live_quote={self.preferences.require_live_quote_for_recommendation}, "
            f"exclude_composite={self.preferences.exclude_composite_for_recommendation}"
        )
        for idx, c in enumerate(candidates[:3]):
            label = "WINNER" if isinstance(recommendation, dict) and c.get("ticker") == recommendation.get("market_ticker") else f"#{idx+1}"
            penalties = c.get("scan_penalties", {})
            penalty_text = ", ".join(f"{k}:{v:.1f}" for k, v in penalties.items()) if penalties else "none"
            score = _to_float(c.get("scan_score"))
            barely = " (barely passed)" if score < (self.preferences.min_recommendation_score + 5.0) else ""
            lines.append(
                f"{label} {c.get('ticker')} score={_fmt_num(c.get('scan_score'))}{barely} "
                f"quote_q={_fmt_num(c.get('scan_quote_quality'))} close_h={_fmt_num(c.get('scan_close_hours'))}"
            )
            lines.append(f"   why: {c.get('scan_rationale', 'n/a')}")
            lines.append(f"   penalties: {penalty_text}")
        return "\n".join(lines)

    def _handle_nexttrade(self, _: list[str]) -> str:
        cached = self._load_cached_recommendation()
        recommendation = cached.get("recommendation")
        if not isinstance(recommendation, dict):
            return "⏭️ Next Trade\nNo cached recommendation. Run /recommend first."
        return self._format_recommendation(recommendation)

    def _handle_recommend(self, _: list[str]) -> str:
        recommendation, _, diagnostics, error = self._generate_recommendation()
        if error:
            return (
                f"🎯 Recommend\nFailed ({error}).\n"
                f"Try /scanstatus for details (fetched={diagnostics.get('markets_fetched', 0)})."
            )
        return self._format_recommendation(recommendation or {})

    def _handle_review(self, args: list[str]) -> str:
        if len(args) != 4:
            return "Usage: /review <TICKER> <YES|NO> <CONTRACTS> <MAX_PRICE>"

        ticker, side, contracts_raw, max_price_raw = args
        try:
            contracts = int(contracts_raw)
            max_price = float(max_price_raw)
        except ValueError:
            return "Invalid number format for contracts or max price."

        result = self.executor.review(
            TradeIntent(
                market_ticker=ticker.upper(),
                side=side.upper(),
                contracts=contracts,
                max_price_dollars=max_price,
                rationale="telegram_review",
            )
        )
        reasons = result.policy_reasons or ["none"]
        needed = []
        if "execution_mode_not_live" in reasons:
            needed.append("set EXECUTION_MODE=live")
        if "live_trading_not_armed" in reasons:
            needed.append("set KALSHI_LIVE_TRADING_ARMED=1")

        return "\n".join(
            [
                "🧪 Review Result",
                f"Market: {result.intent.get('market_ticker')}",
                f"Side: {result.intent.get('side')}",
                f"Contracts: {result.intent.get('contracts')}",
                f"Max price: {_fmt_money(result.intent.get('max_price_dollars'))}",
                f"Outcome: {'APPROVED' if result.approved else 'BLOCKED'}",
                f"Dry-run: {result.dry_run}",
                f"Policy reasons: {', '.join(reasons)}",
                f"To approve: {', '.join(needed) if needed else 'already policy-approved'}",
            ]
        )

    def _load_offset(self) -> int | None:
        if not OFFSET_STATE_PATH.exists():
            return None
        payload = json.loads(OFFSET_STATE_PATH.read_text(encoding="utf-8"))
        value = payload.get("next_update_offset")
        return int(value) if value is not None else None

    def _save_offset(self, offset: int) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        OFFSET_STATE_PATH.write_text(
            json.dumps({"ts": utc_now_iso(), "next_update_offset": offset}, indent=2) + "\n",
            encoding="utf-8",
        )

    def _log_event(self, payload: dict[str, Any]) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with EVENTS_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")

    def _fetch_updates(self, offset: int | None) -> dict[str, Any]:
        params: dict[str, Any] = {"timeout": self.poll_timeout}
        if offset is not None:
            params["offset"] = offset
        response = requests.get(
            f"{self.config.base_url}/getUpdates",
            params=params,
            timeout=self.poll_timeout + 10,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {payload}")
        return payload

    def _send_message(self, text: str) -> None:
        response = requests.post(
            f"{self.config.base_url}/sendMessage",
            json={"chat_id": self.config.chat_id, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
        response.raise_for_status()

    def run_forever(self, poll_interval: float = 0.2) -> None:
        offset = self._load_offset()
        self._log_event({"ts": utc_now_iso(), "kind": "telegram_app_start", "offset": offset})

        while True:
            payload = self._fetch_updates(offset)
            for update in payload.get("result", []):
                update_id = update.get("update_id")
                if update_id is not None:
                    offset = int(update_id) + 1
                    self._save_offset(offset)

                message = update.get("message", {})
                chat_id = str((message.get("chat") or {}).get("id", ""))
                text = (message.get("text") or "").strip()
                if not text:
                    continue

                if self.config.chat_id and chat_id and chat_id != self.config.chat_id:
                    self._log_event({"ts": utc_now_iso(), "kind": "telegram_ignored_chat", "chat_id": chat_id, "text": text})
                    continue

                response_text = self.router.dispatch(text)
                self._send_message(response_text)
                self._log_event(
                    {
                        "ts": utc_now_iso(),
                        "kind": "telegram_command",
                        "chat_id": chat_id,
                        "text": text,
                        "response_preview": response_text[:120],
                    }
                )
            time.sleep(poll_interval)


def load_runtime_config() -> TelegramRuntimeConfig:
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=False)

    return TelegramRuntimeConfig(
        bot_token=read_secret(direct_env_var="TELEGRAM_BOT_TOKEN", file_env_var="TELEGRAM_BOT_TOKEN_FILE"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def run_self_check() -> int:
    try:
        config = load_runtime_config()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Telegram config load failed: {exc}")
        return 1

    print("[PASS] Telegram config loaded.")
    print(f"[INFO] TELEGRAM_CHAT_ID configured: {'yes' if config.chat_id else 'no'}")
    print("[INFO] Live trading default remains disabled unless explicitly armed via policy.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the rebuild-era Telegram operator app.")
    parser.add_argument("--self-check", action="store_true", help="Validate config and exit.")
    parser.add_argument("--once", action="store_true", help="Process one poll cycle and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.self_check:
        raise SystemExit(run_self_check())

    config = load_runtime_config()
    app = TelegramApp(config=config)

    if args.once:
        offset = app._load_offset()
        payload = app._fetch_updates(offset)
        print(json.dumps({"ok": True, "update_count": len(payload.get("result", []))}, indent=2))
        return

    app.run_forever()


if __name__ == "__main__":
    main()
