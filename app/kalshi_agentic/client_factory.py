from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .config import load_settings
from .kalshi_client import KalshiClient


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _read_text(path_str: str) -> str:
    return Path(path_str).read_text(encoding="utf-8").strip()


def _build_client_from_paths(api_key_id_file: str, private_key_path: str) -> tuple[KalshiClient, dict]:
    old_key_file = os.getenv("KALSHI_API_KEY_ID_FILE")
    old_private_key = os.getenv("KALSHI_PRIVATE_KEY_PATH")

    try:
        os.environ["KALSHI_API_KEY_ID_FILE"] = api_key_id_file
        os.environ["KALSHI_PRIVATE_KEY_PATH"] = private_key_path
        settings = load_settings()
        client = KalshiClient(settings=settings)
    finally:
        if old_key_file is not None:
            os.environ["KALSHI_API_KEY_ID_FILE"] = old_key_file
        else:
            os.environ.pop("KALSHI_API_KEY_ID_FILE", None)

        if old_private_key is not None:
            os.environ["KALSHI_PRIVATE_KEY_PATH"] = old_private_key
        else:
            os.environ.pop("KALSHI_PRIVATE_KEY_PATH", None)

    metadata = {
        "api_key_id_file": api_key_id_file,
        "private_key_path": private_key_path,
        "api_key_id": _read_text(api_key_id_file),
    }
    return client, metadata


def make_read_client() -> tuple[KalshiClient, dict]:
    load_dotenv()
    api_key_id_file = _required_env("KALSHI_API_KEY_ID_FILE")
    private_key_path = _required_env("KALSHI_PRIVATE_KEY_PATH")
    client, metadata = _build_client_from_paths(api_key_id_file, private_key_path)
    metadata["profile"] = "read"
    return client, metadata


def make_write_client() -> tuple[KalshiClient, dict]:
    load_dotenv()
    api_key_id_file = _required_env("KALSHI_WRITE_API_KEY_ID_FILE")
    private_key_path = _required_env("KALSHI_WRITE_PRIVATE_KEY_PATH")
    client, metadata = _build_client_from_paths(api_key_id_file, private_key_path)
    metadata["profile"] = "write"
    return client, metadata


def select_client_profile(operation_kind: str) -> str:
    normalized = operation_kind.strip().lower()

    read_operations = {
        "public_data",
        "market_scan",
        "auth_read",
        "portfolio_read",
        "account_limits",
        "api_keys_read",
    }
    write_operations = {
        "order_submission",
        "order_cancel",
        "write",
    }

    if normalized in read_operations:
        return "read"
    if normalized in write_operations:
        return "write"

    raise RuntimeError(f"Unknown operation_kind: {operation_kind}")
