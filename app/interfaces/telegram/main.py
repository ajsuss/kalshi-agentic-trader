from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from app.core.agent_registry import AgentRegistry
from app.execution.executor import Executor, TradeIntent
from app.interfaces.telegram.router import TelegramCommandRouter
from app.migration.legacy_compat import LegacyCompat
from app.policies.risk_policy import RiskPolicy
from app.state.manager import StateManager
from app.kalshi_agentic.client_factory import make_read_client
from app.kalshi_agentic.market_scan import scan_market_universe
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


def _fmt_money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


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
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.register("/help", "Read-only: list commands and safety posture.", self._handle_help)
        self.router.register("/ping", "Read-only: liveness check.", self._handle_ping)
        self.router.register("/agents", "Read-only: list registered agents.", self._handle_agents)
        self.router.register("/status", "Read-only: control-plane summary.", self._handle_status)
        self.router.register("/team", "Read-only: team status summary.", self._handle_team)
        self.router.register("/digest", "Read-only: digest summary.", self._handle_digest)
        self.router.register("/policy", "Read-only: execution policy state.", self._handle_policy)
        self.router.register("/balance", "Read-only: account limits summary.", self._handle_balance)
        self.router.register("/positions", "Read-only: positions (if endpoint available).", self._handle_positions)
        self.router.register("/orders", "Read-only: orders (if endpoint available).", self._handle_orders)
        self.router.register("/markets", "Read-only: top scanned markets.", self._handle_markets)
        self.router.register("/scan", "Read-only: alias for /markets.", self._handle_markets)
        self.router.register("/market", "Read-only: /market <MARKET_TICKER>", self._handle_market)
        self.router.register("/event", "Read-only: /event <EVENT_TICKER>", self._handle_event)
        self.router.register("/refresh", "Read-only: refresh candidates + recommendation.", self._handle_refresh)
        self.router.register("/candidates", "Read-only: cached top candidates.", self._handle_candidates)
        self.router.register("/nexttrade", "Read-only: cached best dry-run recommendation.", self._handle_nexttrade)
        self.router.register("/recommend", "Read-only: generate dry-run recommendation now.", self._handle_recommend)
        self.router.register("/review", "Read-only: /review <TICKER> <YES|NO> <CONTRACTS> <MAX_PRICE>", self._handle_review)

    def _help_sections(self) -> list[str]:
        return [
            "🤖 Kalshi Dry-Run Operator Bot",
            "Read-only controls:",
            "/help /ping /policy /status /team /digest",
            "Market data:",
            "/markets (/scan) /market <TICKER> /event <EVENT_TICKER>",
            "Account views:",
            "/balance /positions /orders",
            "Dry-run recommendation loop:",
            "/refresh /candidates /nexttrade /recommend /review <TICKER> <YES|NO> <CONTRACTS> <MAX_PRICE>",
            "Safety:",
            "Live trading disabled by default. No live order path is enabled here.",
            "Use '/status raw' or '/digest raw' for JSON debug output.",
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
                f"Next trade available: {next_trade.get('available', False)}",
                f"Next trade ticker: {next_trade.get('market_ticker', 'n/a')}",
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
                f"Phase: {digest.get('phase', 'n/a')}",
            ]
        )

    def _handle_policy(self, _: list[str]) -> str:
        decision = self.executor.policy.evaluate(
            {
                "market_ticker": "POLICY-CHECK",
                "side": "YES",
                "contracts": 1,
                "max_price_dollars": 0.5,
            }
        )
        reasons = decision.reasons or ["none"]
        advice = []
        if "execution_mode_not_live" in reasons:
            advice.append("Set EXECUTION_MODE=live")
        if "live_trading_not_armed" in reasons:
            advice.append("Set KALSHI_LIVE_TRADING_ARMED=1")

        return "\n".join(
            [
                "🛡️ Policy Check",
                f"Mode: {decision.mode}",
                f"Approved: {decision.approved}",
                f"Reasons: {', '.join(reasons)}",
                f"For approval: {', '.join(advice) if advice else 'already policy-approved'}",
            ]
        )

    def _auth_get_first_ok(self, paths: list[str]) -> tuple[dict[str, Any] | None, str | None]:
        client, error = self._with_read_client()
        if client is None:
            return None, f"Read-client unavailable: {error}"

        try:
            for path in paths:
                try:
                    response = client.auth_get(path)
                    return response.json(), None
                except Exception:
                    continue
            return None, f"No supported endpoint from: {', '.join(paths)}"
        finally:
            client.close()

    def _handle_balance(self, _: list[str]) -> str:
        payload, error = self._auth_get_first_ok([
            "/trade-api/v2/account/limits",
            "/trade-api/v2/account/balance",
        ])
        if payload is None:
            return f"💼 Balance\nUnavailable ({error})."

        return "\n".join(
            [
                "💼 Account Summary",
                f"Usage tier: {payload.get('usage_tier', 'n/a')}",
                f"Read limit: {_fmt_num(payload.get('read_limit'))}",
                f"Write limit: {_fmt_num(payload.get('write_limit'))}",
                f"Balance: {_fmt_money(payload.get('balance_dollars') or payload.get('balance'))}",
                f"Buying power: {_fmt_money(payload.get('buying_power_dollars') or payload.get('buying_power'))}",
            ]
        )

    def _extract_list(self, payload: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _handle_positions(self, _: list[str]) -> str:
        payload, error = self._auth_get_first_ok([
            "/trade-api/v2/portfolio/positions",
            "/trade-api/v2/positions",
        ])
        if payload is None:
            return f"📌 Positions\nUnavailable ({error})."

        positions = self._extract_list(payload, ["positions", "market_positions", "portfolio_positions"])
        if not positions:
            return "📌 Positions\nNo positions returned by endpoint."

        lines = ["📌 Positions (top 10):"]
        for pos in positions[:10]:
            lines.append(
                f"• {pos.get('ticker', pos.get('market_ticker', 'unknown'))} "
                f"qty={pos.get('position', pos.get('quantity', 'n/a'))} "
                f"side={pos.get('side', 'n/a')}"
            )
        return "\n".join(lines)

    def _handle_orders(self, _: list[str]) -> str:
        payload, error = self._auth_get_first_ok([
            "/trade-api/v2/portfolio/orders",
            "/trade-api/v2/orders",
        ])
        if payload is None:
            return f"🧾 Orders\nUnavailable ({error})."

        orders = self._extract_list(payload, ["orders", "open_orders", "recent_orders"])
        if not orders:
            return "🧾 Orders\nNo orders returned by endpoint."

        lines = ["🧾 Orders (top 10):"]
        for order in orders[:10]:
            lines.append(
                f"• {order.get('ticker', order.get('market_ticker', 'unknown'))} "
                f"{order.get('side', 'n/a')} "
                f"qty={order.get('count', order.get('quantity', 'n/a'))} "
                f"status={order.get('status', 'n/a')}"
            )
        return "\n".join(lines)

    def _scan_candidates(self) -> tuple[list[dict[str, Any]], str | None]:
        client, error = self._with_read_client()
        if client is None:
            return [], f"Read-client unavailable: {error}"

        try:
            scan = scan_market_universe(client, pages=3, limit_per_page=25, top_n=8)
            return scan.get("top_candidates", []), None
        except Exception as exc:  # noqa: BLE001
            return [], str(exc)
        finally:
            client.close()

    def _persist_candidates(self, candidates: list[dict[str, Any]], recommendation: dict[str, Any] | None) -> None:
        self.state.write_json(
            "runtime/recommendation_state.json",
            {
                "ts": utc_now_iso(),
                "candidates": candidates,
                "recommendation": recommendation,
            },
        )

    def _load_cached_recommendation(self) -> dict[str, Any]:
        return self.state.read_json("runtime/recommendation_state.json", default={})

    def _format_candidate_line(self, c: dict[str, Any], idx: int) -> str:
        return (
            f"{idx}. {c.get('ticker', 'n/a')} | score={_fmt_num(c.get('scan_score'))} "
            f"| ask={_fmt_money(c.get('yes_ask_dollars'))} | vol={_fmt_num(c.get('volume_fp'))}"
        )

    def _handle_markets(self, _: list[str]) -> str:
        candidates, error = self._scan_candidates()
        if error:
            return f"📈 Market Scan\nUnavailable ({error})."
        if not candidates:
            return "📈 Market Scan\nNo candidates returned."

        lines = ["📈 Top Markets"]
        lines.extend(self._format_candidate_line(c, idx + 1) for idx, c in enumerate(candidates[:8]))
        return "\n".join(lines)

    def _handle_market(self, args: list[str]) -> str:
        if not args:
            return "Usage: /market <MARKET_TICKER>"

        ticker = args[0].strip().upper()
        client, error = self._with_read_client()
        if client is None:
            return f"🔎 Market\nUnavailable ({error})."

        try:
            market_payload = fetch_market_by_ticker(client, ticker)
            market = market_payload.get("market", market_payload)
            return "\n".join(
                [
                    f"🔎 Market {market.get('ticker', ticker)}",
                    f"Title: {market.get('title', 'n/a')}",
                    f"Status: {market.get('status', 'n/a')}",
                    f"YES bid/ask: {_fmt_money(market.get('yes_bid_dollars'))} / {_fmt_money(market.get('yes_ask_dollars'))}",
                    f"NO bid/ask: {_fmt_money(market.get('no_bid_dollars'))} / {_fmt_money(market.get('no_ask_dollars'))}",
                    f"Last: {_fmt_money(market.get('last_price_dollars'))}",
                    f"Volume: {_fmt_num(market.get('volume_fp'))} | Liquidity: {_fmt_money(market.get('liquidity_dollars'))}",
                ]
            )
        except Exception as exc:  # noqa: BLE001
            return f"🔎 Market\nLookup failed ({exc})."
        finally:
            client.close()

    def _handle_event(self, args: list[str]) -> str:
        if not args:
            return "Usage: /event <EVENT_TICKER>"

        event_ticker = args[0].strip().upper()
        client, error = self._with_read_client()
        if client is None:
            return f"🗂️ Event\nUnavailable ({error})."

        try:
            event_payload = fetch_event_by_ticker(client, event_ticker, with_nested_markets=True)
            event = event_payload.get("event", event_payload)
            markets = event_payload.get("markets", []) if isinstance(event_payload.get("markets"), list) else []
            lines = [
                f"🗂️ Event {event.get('event_ticker', event_ticker)}",
                f"Title: {event.get('title', 'n/a')}",
                f"Status: {event.get('status', 'n/a')}",
                f"Markets: {len(markets)}",
            ]
            for m in markets[:5]:
                lines.append(
                    f"• {m.get('ticker', 'n/a')} | last={_fmt_money(m.get('last_price_dollars'))} | "
                    f"yes_ask={_fmt_money(m.get('yes_ask_dollars'))}"
                )
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            return f"🗂️ Event\nLookup failed ({exc})."
        finally:
            client.close()

    def _generate_recommendation(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
        candidates, error = self._scan_candidates()
        if error:
            return None, [], error
        if not candidates:
            return None, [], "No candidates available from scan."

        top = candidates[0]
        max_price = top.get("yes_ask_dollars") or top.get("last_price_dollars") or 0.5
        review = self.executor.review(
            TradeIntent(
                market_ticker=top.get("ticker", "UNKNOWN"),
                side="YES",
                contracts=1,
                max_price_dollars=float(max_price),
                rationale="dry_run_top_scan_candidate",
            )
        )
        recommendation = {
            "market_ticker": top.get("ticker"),
            "event_ticker": top.get("event_ticker"),
            "title": top.get("title"),
            "scan_score": top.get("scan_score"),
            "proposed_side": "YES",
            "proposed_contracts": 1,
            "proposed_max_price_dollars": max_price,
            "executor_review": review.__dict__,
            "generated_at": utc_now_iso(),
            "rationale": "Top ranked market from live read-only scan; reviewed via executor policy.",
        }
        self._persist_candidates(candidates, recommendation)
        return recommendation, candidates, None

    def _format_recommendation(self, recommendation: dict[str, Any]) -> str:
        review = recommendation.get("executor_review", {})
        reasons = review.get("policy_reasons") or ["none"]
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
                f"Scan score: {_fmt_num(recommendation.get('scan_score'))}",
                f"Executor result: {'APPROVED' if review.get('approved') else 'BLOCKED'}",
                f"Dry-run: {review.get('dry_run')}",
                f"Policy reasons: {', '.join(reasons)}",
                f"For policy approval: {', '.join(guidance) if guidance else 'already policy-approved'}",
                f"Rationale: {recommendation.get('rationale')}",
            ]
        )

    def _handle_refresh(self, _: list[str]) -> str:
        recommendation, candidates, error = self._generate_recommendation()
        if error:
            return f"🔄 Refresh\nFailed ({error})."
        return (
            f"🔄 Refresh complete: {len(candidates)} candidates ranked.\n"
            + self._format_recommendation(recommendation or {})
        )

    def _handle_candidates(self, _: list[str]) -> str:
        cached = self._load_cached_recommendation()
        candidates = cached.get("candidates") or []
        if not candidates:
            return "🗂️ Candidates\nNo cached candidates yet. Run /refresh or /recommend first."

        lines = ["🗂️ Cached Candidates"]
        lines.extend(self._format_candidate_line(c, idx + 1) for idx, c in enumerate(candidates[:8]))
        return "\n".join(lines)

    def _handle_nexttrade(self, _: list[str]) -> str:
        cached = self._load_cached_recommendation()
        recommendation = cached.get("recommendation")
        if not isinstance(recommendation, dict):
            return "⏭️ Next Trade\nNo cached recommendation. Run /recommend first."
        return self._format_recommendation(recommendation)

    def _handle_recommend(self, _: list[str]) -> str:
        recommendation, _, error = self._generate_recommendation()
        if error:
            return f"🎯 Recommend\nFailed ({error})."
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
            json={
                "chat_id": self.config.chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
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
                    self._log_event(
                        {
                            "ts": utc_now_iso(),
                            "kind": "telegram_ignored_chat",
                            "chat_id": chat_id,
                            "text": text,
                        }
                    )
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
        bot_token=read_secret(
            direct_env_var="TELEGRAM_BOT_TOKEN",
            file_env_var="TELEGRAM_BOT_TOKEN_FILE",
        ),
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
