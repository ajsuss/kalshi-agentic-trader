import json
from datetime import datetime, timezone
from pathlib import Path
import os

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path("/Users/Apple/kalshi-agentic-trader")
ENV_PATH = PROJECT_ROOT / ".env"
LOG_DIR = PROJECT_ROOT / "logs" / "step2"
LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ENV_PATH)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(filename: str, payload: dict):
    path = LOG_DIR / filename
    with path.open("a") as f:
        f.write(json.dumps(payload, default=str) + "\n")


def read_text_file(path_str: str) -> str:
    return Path(path_str).expanduser().read_text().strip()


def update_env_chat_id(chat_id: str):
    lines = ENV_PATH.read_text().splitlines()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("TELEGRAM_CHAT_ID="):
            new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n")


def main():
    token_file = os.getenv("TELEGRAM_BOT_TOKEN_FILE", "").strip()
    existing_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token_file:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN_FILE in .env")

    token = read_text_file(token_file)
    base = f"https://api.telegram.org/bot{token}"

    print("TELEGRAM_PROBE_START")
    print("ENV_FILE", str(ENV_PATH))
    print("LOG_DIR", str(LOG_DIR))
    print("EXISTING_CHAT_ID", existing_chat_id if existing_chat_id else "<blank>")

    # 1) Pull updates
    updates_r = requests.get(f"{base}/getUpdates", timeout=20)
    print("GET_UPDATES_STATUS", updates_r.status_code)

    try:
        updates_json = updates_r.json()
    except Exception as e:
        append_jsonl("telegram_updates.jsonl", {
            "ts": utc_now_iso(),
            "kind": "telegram_get_updates",
            "status_code": updates_r.status_code,
            "ok": False,
            "error": f"non-json response: {e}",
            "body_preview": updates_r.text[:500],
        })
        raise

    append_jsonl("telegram_updates.jsonl", {
        "ts": utc_now_iso(),
        "kind": "telegram_get_updates",
        "status_code": updates_r.status_code,
        "ok": updates_r.ok,
        "body_preview": json.dumps(updates_json)[:1500],
    })

    if not updates_json.get("ok"):
        raise RuntimeError(f"Telegram getUpdates failed: {updates_json}")

    results = updates_json.get("result", [])
    print("GET_UPDATES_OK", updates_json.get("ok"))
    print("GET_UPDATES_COUNT", len(results))

    discovered_chat_id = None
    discovered_username = None

    # Find most recent private chat update with a message
    for upd in reversed(results):
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue
        chat = msg.get("chat", {})
        if chat.get("type") == "private":
            discovered_chat_id = str(chat.get("id"))
            user = msg.get("from", {})
            discovered_username = user.get("username")
            break

    if not discovered_chat_id:
        print("DISCOVERED_CHAT_ID", "<none>")
        print("ACTION_NEEDED", "Send /start to the bot again, then rerun this script.")
        return

    print("DISCOVERED_CHAT_ID", discovered_chat_id)
    print("DISCOVERED_USERNAME", discovered_username)

    # 2) Persist chat id into .env
    update_env_chat_id(discovered_chat_id)
    print("ENV_UPDATED_CHAT_ID", discovered_chat_id)

    append_jsonl("telegram_chat_id.jsonl", {
        "ts": utc_now_iso(),
        "kind": "telegram_chat_id_capture",
        "chat_id": discovered_chat_id,
        "username": discovered_username,
        "env_path": str(ENV_PATH),
    })

    # 3) Send a system online message
    text = "Kalshi agent control node: system online. Step 2 Telegram test successful."
    send_r = requests.post(
        f"{base}/sendMessage",
        data={
            "chat_id": discovered_chat_id,
            "text": text,
        },
        timeout=20,
    )
    print("SEND_MESSAGE_STATUS", send_r.status_code)

    try:
        send_json = send_r.json()
    except Exception as e:
        append_jsonl("telegram_send.jsonl", {
            "ts": utc_now_iso(),
            "kind": "telegram_send_message",
            "status_code": send_r.status_code,
            "ok": False,
            "error": f"non-json response: {e}",
            "body_preview": send_r.text[:500],
        })
        raise

    append_jsonl("telegram_send.jsonl", {
        "ts": utc_now_iso(),
        "kind": "telegram_send_message",
        "status_code": send_r.status_code,
        "ok": send_json.get("ok"),
        "body_preview": json.dumps(send_json)[:1500],
    })

    print("SEND_MESSAGE_OK", send_json.get("ok"))
    if send_json.get("ok"):
        result = send_json.get("result", {})
        print("SENT_MESSAGE_ID", result.get("message_id"))
        print("SENT_CHAT_ID", result.get("chat", {}).get("id"))
    else:
        print("SEND_MESSAGE_BODY", json.dumps(send_json)[:500])

    print("TELEGRAM_PROBE_DONE")


if __name__ == "__main__":
    main()
