from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.kalshi_agentic import JsonlLogger, KalshiClient, TelegramNotifier, load_settings, utc_now_iso


def main() -> int:
    run_id = uuid.uuid4().hex
    logger = JsonlLogger(PROJECT_ROOT / "logs" / "step3" / "health_check.jsonl")

    summary: dict[str, object] = {
        "run_id": run_id,
        "check_name": "step3_health_check",
        "mode": "read_only",
        "overall_ok": False,
        "checks": {},
    }

    settings = None
    client = None

    try:
        try:
            settings = load_settings()
            summary["checks"]["env_and_secrets"] = {
                "ok": True,
                "details": {
                    "app_env": settings.app_env,
                    "kalshi_env": settings.kalshi_env,
                    "kalshi_base_url": settings.kalshi_base_url,
                    "kalshi_api_key_id_present": bool(settings.kalshi_api_key_id),
                    "kalshi_private_key_exists": settings.kalshi_private_key_path.exists(),
                    "telegram_bot_token_present": bool(settings.telegram_bot_token),
                    "telegram_chat_id_present": bool(settings.telegram_chat_id),
                },
            }
        except Exception as exc:
            summary["checks"]["env_and_secrets"] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        if settings is not None:
            client = KalshiClient(settings)

            try:
                response = client.public_get("/trade-api/v2/events", params={"limit": 1})
                data = response.json()
                events = data.get("events", []) if isinstance(data, dict) else []
                summary["checks"]["kalshi_public"] = {
                    "ok": True,
                    "details": {
                        "status_code": response.status_code,
                        "event_count_returned": len(events),
                    },
                }
            except Exception as exc:
                summary["checks"]["kalshi_public"] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            try:
                response = client.auth_get("/trade-api/v2/account/limits")
                data = response.json()
                top_level_keys = sorted(list(data.keys())) if isinstance(data, dict) else []
                summary["checks"]["kalshi_authenticated"] = {
                    "ok": True,
                    "details": {
                        "status_code": response.status_code,
                        "top_level_keys": top_level_keys,
                    },
                }
            except Exception as exc:
                summary["checks"]["kalshi_authenticated"] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            try:
                notifier = TelegramNotifier(settings)
                message_data = notifier.send_message(
                    text=(
                        "Kalshi agentic trader Step 3 health check\n"
                        f"run_id={run_id}\n"
                        "mode=read_only"
                    ),
                    disable_notification=False,
                )
                result = message_data.get("result", {}) if isinstance(message_data, dict) else {}
                summary["checks"]["telegram_send"] = {
                    "ok": True,
                    "details": {
                        "message_id": result.get("message_id"),
                    },
                }
            except Exception as exc:
                summary["checks"]["telegram_send"] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        checks = summary.get("checks", {})
        summary["overall_ok"] = bool(checks) and all(
            isinstance(check_result, dict) and check_result.get("ok") is True
            for check_result in checks.values()
        )
        summary["completed_at_utc"] = utc_now_iso()

        entry = logger.write("step3_health_check", summary)
        print(json.dumps(entry, indent=2, sort_keys=True))

        return 0 if summary["overall_ok"] else 1

    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
