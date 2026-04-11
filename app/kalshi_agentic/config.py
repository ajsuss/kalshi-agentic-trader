from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"


def _load_dotenv() -> None:
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=False)


def _read_text_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required file does not exist: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"Required file is empty: {path}")
    return value


def _read_secret(
    *,
    direct_env_var: str,
    file_env_var: str,
    required: bool = True,
) -> str:
    direct_value = os.getenv(direct_env_var, "").strip()
    if direct_value:
        return direct_value

    file_value = os.getenv(file_env_var, "").strip()
    if file_value:
        return _read_text_file(Path(file_value).expanduser())

    if required:
        raise ValueError(
            f"Missing secret. Set {direct_env_var} directly or provide {file_env_var}."
        )
    return ""


def _resolve_kalshi_base_url(kalshi_env: str) -> str:
    override = os.getenv("KALSHI_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")

    normalized = kalshi_env.strip().lower()
    if normalized in {"prod", "production"}:
        return "https://api.elections.kalshi.com"

    raise ValueError(
        "No default Kalshi base URL is configured for non-production mode. "
        "Set KALSHI_BASE_URL explicitly in .env."
    )


@dataclass(frozen=True)
class Settings:
    app_env: str
    kalshi_env: str
    kalshi_base_url: str
    kalshi_api_key_id: str
    kalshi_private_key_path: Path
    telegram_bot_token: str
    telegram_chat_id: str
    project_root: Path
    logs_dir: Path


def load_settings() -> Settings:
    _load_dotenv()

    app_env = os.getenv("APP_ENV", "").strip() or "dev"
    kalshi_env = os.getenv("KALSHI_ENV", "").strip() or "prod"

    kalshi_api_key_id = _read_secret(
        direct_env_var="KALSHI_API_KEY_ID",
        file_env_var="KALSHI_API_KEY_ID_FILE",
        required=True,
    )

    kalshi_private_key_raw = os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip()
    if not kalshi_private_key_raw:
        raise ValueError("Missing KALSHI_PRIVATE_KEY_PATH in .env.")
    kalshi_private_key_path = Path(kalshi_private_key_raw).expanduser()
    if not kalshi_private_key_path.exists():
        raise FileNotFoundError(
            f"Kalshi private key file not found: {kalshi_private_key_path}"
        )

    telegram_bot_token = _read_secret(
        direct_env_var="TELEGRAM_BOT_TOKEN",
        file_env_var="TELEGRAM_BOT_TOKEN_FILE",
        required=True,
    )

    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not telegram_chat_id:
        raise ValueError("Missing TELEGRAM_CHAT_ID in .env.")

    kalshi_base_url = _resolve_kalshi_base_url(kalshi_env)

    return Settings(
        app_env=app_env,
        kalshi_env=kalshi_env,
        kalshi_base_url=kalshi_base_url,
        kalshi_api_key_id=kalshi_api_key_id,
        kalshi_private_key_path=kalshi_private_key_path,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        project_root=PROJECT_ROOT,
        logs_dir=PROJECT_ROOT / "logs",
    )
