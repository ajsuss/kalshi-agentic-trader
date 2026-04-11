import json
import base64
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


PROJECT_ROOT = Path("/Users/Apple/kalshi-agentic-trader")
LOG_DIR = PROJECT_ROOT / "logs" / "step2"
LOG_DIR.mkdir(parents=True, exist_ok=True)

ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

BASE_URL = "https://api.elections.kalshi.com"
PUBLIC_EVENTS_PATH = "/trade-api/v2/events"
AUTH_LIMITS_PATH = "/trade-api/v2/account/limits"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_text_file(path_str: str) -> str:
    path = Path(path_str).expanduser()
    return path.read_text().strip()


def load_config():
    required = [
        "KALSHI_API_KEY_ID_FILE",
        "KALSHI_PRIVATE_KEY_PATH",
        "TELEGRAM_BOT_TOKEN_FILE",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing env vars in .env: {missing}")

    api_key_id = read_text_file(os.environ["KALSHI_API_KEY_ID_FILE"])
    private_key_path = Path(os.environ["KALSHI_PRIVATE_KEY_PATH"]).expanduser()

    if not private_key_path.exists():
        raise FileNotFoundError(f"Kalshi private key not found: {private_key_path}")

    return {
        "api_key_id": api_key_id,
        "private_key_path": private_key_path,
        "telegram_token": read_text_file(os.environ["TELEGRAM_BOT_TOKEN_FILE"]),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    }


def load_private_key(private_key_path: Path):
    pem = private_key_path.read_bytes()
    return serialization.load_pem_private_key(pem, password=None)


def kalshi_signature(private_key, timestamp_ms: str, method: str, path: str) -> str:
    message = f"{timestamp_ms}{method.upper()}{path}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def append_jsonl(filename: str, payload: dict):
    path = LOG_DIR / filename
    with path.open("a") as f:
        f.write(json.dumps(payload, default=str) + "\n")


def get_public_events():
    url = BASE_URL + PUBLIC_EVENTS_PATH
    r = requests.get(url, timeout=20)
    payload = {
        "ts": utc_now_iso(),
        "kind": "public_events_probe",
        "url": url,
        "status_code": r.status_code,
        "ok": r.ok,
    }
    try:
        data = r.json()
        payload["response_keys"] = list(data.keys()) if isinstance(data, dict) else None
        if isinstance(data, dict):
            events = data.get("events", [])
            payload["events_count"] = len(events) if isinstance(events, list) else None
            if events:
                payload["first_event_ticker"] = events[0].get("event_ticker")
        else:
            payload["body_preview"] = str(data)[:500]
    except Exception:
        payload["body_preview"] = r.text[:500]

    append_jsonl("public_events.jsonl", payload)
    return r


def get_auth_limits(api_key_id: str, private_key):
    timestamp_ms = str(int(time.time() * 1000))
    signature = kalshi_signature(private_key, timestamp_ms, "GET", AUTH_LIMITS_PATH)

    headers = {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }

    url = BASE_URL + AUTH_LIMITS_PATH
    r = requests.get(url, headers=headers, timeout=20)

    payload = {
        "ts": utc_now_iso(),
        "kind": "auth_limits_probe",
        "url": url,
        "status_code": r.status_code,
        "ok": r.ok,
        "request_headers_present": {
            "KALSHI-ACCESS-KEY": True,
            "KALSHI-ACCESS-TIMESTAMP": True,
            "KALSHI-ACCESS-SIGNATURE": True,
        },
    }

    try:
        data = r.json()
        payload["response_keys"] = list(data.keys()) if isinstance(data, dict) else None
        if isinstance(data, dict):
            payload["body_preview"] = json.dumps(data)[:800]
    except Exception:
        payload["body_preview"] = r.text[:800]

    append_jsonl("auth_limits.jsonl", payload)
    return r


def main():
    cfg = load_config()
    private_key = load_private_key(cfg["private_key_path"])

    print("STEP2_PROBE_START")
    print("ENV_LOADED", True)
    print("LOG_DIR", str(LOG_DIR))

    public_r = get_public_events()
    print("PUBLIC_EVENTS_STATUS", public_r.status_code)
    try:
        public_json = public_r.json()
        events = public_json.get("events", []) if isinstance(public_json, dict) else []
        print("PUBLIC_EVENTS_OK", public_r.ok)
        print("PUBLIC_EVENTS_COUNT", len(events) if isinstance(events, list) else "unknown")
        if isinstance(events, list) and events:
            print("PUBLIC_FIRST_EVENT_TICKER", events[0].get("event_ticker"))
    except Exception:
        print("PUBLIC_EVENTS_OK", public_r.ok)
        print("PUBLIC_EVENTS_BODY_PREVIEW", public_r.text[:300])

    auth_r = get_auth_limits(cfg["api_key_id"], private_key)
    print("AUTH_LIMITS_STATUS", auth_r.status_code)
    try:
        auth_json = auth_r.json()
        print("AUTH_LIMITS_OK", auth_r.ok)
        print("AUTH_LIMITS_KEYS", list(auth_json.keys()) if isinstance(auth_json, dict) else "non-dict")
        print("AUTH_LIMITS_BODY_PREVIEW", json.dumps(auth_json)[:500])
    except Exception:
        print("AUTH_LIMITS_OK", auth_r.ok)
        print("AUTH_LIMITS_BODY_PREVIEW", auth_r.text[:500])

    print("STEP2_PROBE_DONE")


if __name__ == "__main__":
    main()
