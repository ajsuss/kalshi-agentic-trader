from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.kalshi_agentic import JsonlLogger, KalshiClient, load_settings, utc_now_iso
from app.kalshi_agentic.snapshots import (
    fetch_account_limits_status,
    fetch_event_snapshot,
    fetch_market_snapshot,
    summarize_account_limits_status,
    summarize_event_snapshot,
    summarize_market_snapshot,
)


def main() -> int:
    run_id = uuid.uuid4().hex
    logger = JsonlLogger(PROJECT_ROOT / "logs" / "step4" / "snapshot_capture.jsonl")

    summary: dict[str, object] = {
        "run_id": run_id,
        "check_name": "step4_snapshot_capture",
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
                account_snapshot = fetch_account_limits_status(client)
                logger.write(
                    "step4_account_limits_status_raw",
                    {
                        "run_id": run_id,
                        **account_snapshot,
                    },
                )
                summary["checks"]["account_limits_status"] = {
                    "ok": True,
                    "details": summarize_account_limits_status(account_snapshot),
                }
            except Exception as exc:
                summary["checks"]["account_limits_status"] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            try:
                event_snapshot = fetch_event_snapshot(client, limit=2)
                logger.write(
                    "step4_event_snapshot_raw",
                    {
                        "run_id": run_id,
                        **event_snapshot,
                    },
                )
                summary["checks"]["event_snapshot"] = {
                    "ok": True,
                    "details": summarize_event_snapshot(event_snapshot),
                }
            except Exception as exc:
                summary["checks"]["event_snapshot"] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            try:
                market_snapshot = fetch_market_snapshot(client, limit=3)
                logger.write(
                    "step4_market_snapshot_raw",
                    {
                        "run_id": run_id,
                        **market_snapshot,
                    },
                )
                summary["checks"]["market_snapshot"] = {
                    "ok": True,
                    "details": summarize_market_snapshot(market_snapshot),
                }
            except Exception as exc:
                summary["checks"]["market_snapshot"] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        checks = summary.get("checks", {})
        summary["overall_ok"] = bool(checks) and all(
            isinstance(check_result, dict) and check_result.get("ok") is True
            for check_result in checks.values()
        )
        summary["completed_at_utc"] = utc_now_iso()

        entry = logger.write("step4_snapshot_capture", summary)
        print(json.dumps(entry, indent=2, sort_keys=True))

        return 0 if summary["overall_ok"] else 1

    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
