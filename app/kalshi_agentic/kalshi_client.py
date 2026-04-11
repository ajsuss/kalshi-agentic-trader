from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .config import Settings


class KalshiClient:
    """Small reusable read-only Kalshi client."""

    def __init__(self, settings: Settings, timeout: float = 15.0) -> None:
        self.settings = settings
        self.timeout = timeout
        self.base_url = settings.kalshi_base_url.rstrip("/")
        self.session = requests.Session()
        self._private_key = self._load_private_key(settings.kalshi_private_key_path)

    @staticmethod
    def _normalize_path(path: str) -> str:
        return path if path.startswith("/") else f"/{path}"

    @staticmethod
    def _load_private_key(private_key_path: Path) -> Any:
        key_bytes = private_key_path.read_bytes()
        return serialization.load_pem_private_key(key_bytes, password=None)

    def _sign(self, method: str, path: str, timestamp_ms: str) -> str:
        message = f"{timestamp_ms}{method.upper()}{path}".encode("utf-8")
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=hashes.SHA256().digest_size,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000))
        signature = self._sign(method=method, path=path, timestamp_ms=timestamp_ms)
        return {
            "KALSHI-ACCESS-KEY": self.settings.kalshi_api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    def public_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        normalized_path = self._normalize_path(path)
        response = self.session.get(
            f"{self.base_url}{normalized_path}",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    def auth_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        normalized_path = self._normalize_path(path)
        response = self.session.get(
            f"{self.base_url}{normalized_path}",
            params=params,
            headers=self._auth_headers(method="GET", path=normalized_path),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    def auth_post(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> requests.Response:
        normalized_path = self._normalize_path(path)
        headers = self._auth_headers(method="POST", path=normalized_path)
        headers["Content-Type"] = "application/json"
        response = self.session.post(
            f"{self.base_url}{normalized_path}",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    def close(self) -> None:
        self.session.close()
