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
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.register("/help", "Read-only: list bot commands and safety posture.", self._handle_help)
        self.router.register("/ping", "Read-only: liveness check.", self._handle_ping)
        self.router.register("/agents", "Read-only: list registered agents.", self._handle_agents)
        self.router.register("/status", "Read-only: control-plane status snapshot.", self._handle_status)
        self.router.register("/team", "Read-only: team status snapshot.", self._handle_team)
        self.router.register("/digest", "Read-only: control digest.", self._handle_digest)
        self.router.register("/policy", "Read-only: current execution policy gate state.", self._handle_policy)
        self.router.register(
            "/review",
            "Read-only: simulate executor review: /review <TICKER> <YES|NO> <CONTRACTS> <MAX_PRICE>",
            self._handle_review,
        )

    def _handle_help(self, _: list[str]) -> str:
        return (
            self.router.help_text()
            + "\n\nSafety: live trading is disabled by default. "
            "No live order path is available from this bot without explicit arming and policy approval."
        )

    def _handle_ping(self, _: list[str]) -> str:
        return f"pong {utc_now_iso()}"

    def _handle_agents(self, _: list[str]) -> str:
        agents = self.registry.list_agents()
        if not agents:
            return "No agents are currently registered."
        lines = ["Registered agents:"]
        lines.extend(f"- {a['name']}: {a['description']}" for a in agents)
        return "\n".join(lines)

    def _handle_status(self, _: list[str]) -> str:
        payload = self.compat.build_step43_snapshot()
        return json.dumps(payload, indent=2)

    def _handle_team(self, _: list[str]) -> str:
        payload = self.registry.run("team_status", {"repo_root": REPO_ROOT})
        return json.dumps(payload, indent=2)

    def _handle_digest(self, _: list[str]) -> str:
        payload = self.compat.build_step46_digest()
        return json.dumps(payload, indent=2)

    def _handle_policy(self, _: list[str]) -> str:
        decision = self.executor.policy.evaluate(
            {
                "market_ticker": "POLICY-CHECK",
                "side": "YES",
                "contracts": 1,
                "max_price_dollars": 0.5,
            }
        )
        return json.dumps(
            {
                "mode": decision.mode,
                "approved": decision.approved,
                "reasons": decision.reasons,
                "live_trading_default": "disabled",
            },
            indent=2,
        )

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
                market_ticker=ticker,
                side=side.upper(),
                contracts=contracts,
                max_price_dollars=max_price,
                rationale="telegram_review",
            )
        )
        return json.dumps(result.__dict__, indent=2)

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
