from __future__ import annotations

from typing import Any

from .kalshi_client import KalshiClient


def _ensure_dict_payload(payload: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{context} expected a dict JSON payload, got {type(payload).__name__}")
    return payload


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def fetch_account_limits_status(client: KalshiClient) -> dict[str, Any]:
    path = "/trade-api/v2/account/limits"
    response = client.auth_get(path)
    payload = _ensure_dict_payload(response.json(), context=path)
    return {
        "path": path,
        "status_code": response.status_code,
        "payload": payload,
    }


def summarize_account_limits_status(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _ensure_dict_payload(snapshot.get("payload"), context="account_limits_status")
    return {
        "path": snapshot.get("path"),
        "status_code": snapshot.get("status_code"),
        "top_level_keys": sorted(payload.keys()),
        "usage_tier": payload.get("usage_tier"),
        "read_limit": payload.get("read_limit"),
        "write_limit": payload.get("write_limit"),
    }


def fetch_event_snapshot(client: KalshiClient, *, limit: int = 2) -> dict[str, Any]:
    path = "/trade-api/v2/events"
    params = {"limit": limit}
    response = client.public_get(path, params=params)
    payload = _ensure_dict_payload(response.json(), context=path)
    return {
        "path": path,
        "params": params,
        "status_code": response.status_code,
        "payload": payload,
    }


def summarize_event_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _ensure_dict_payload(snapshot.get("payload"), context="event_snapshot")
    events = _safe_list(payload.get("events"))

    sample_events: list[dict[str, Any]] = []
    for event in events[:5]:
        if not isinstance(event, dict):
            continue
        sample_events.append(
            {
                "event_ticker": event.get("event_ticker"),
                "series_ticker": event.get("series_ticker"),
                "title": event.get("title"),
                "sub_title": event.get("sub_title"),
                "category": event.get("category"),
                "mutually_exclusive": event.get("mutually_exclusive"),
                "last_updated_ts": event.get("last_updated_ts"),
            }
        )

    return {
        "path": snapshot.get("path"),
        "params": snapshot.get("params"),
        "status_code": snapshot.get("status_code"),
        "event_count": len(events),
        "sample_events": sample_events,
    }


def fetch_market_snapshot(client: KalshiClient, *, limit: int = 3) -> dict[str, Any]:
    path = "/trade-api/v2/markets"
    params = {"limit": limit}
    response = client.public_get(path, params=params)
    payload = _ensure_dict_payload(response.json(), context=path)
    return {
        "path": path,
        "params": params,
        "status_code": response.status_code,
        "payload": payload,
    }


def summarize_market_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _ensure_dict_payload(snapshot.get("payload"), context="market_snapshot")
    markets = _safe_list(payload.get("markets"))

    sample_markets: list[dict[str, Any]] = []
    for market in markets[:5]:
        if not isinstance(market, dict):
            continue
        sample_markets.append(
            {
                "ticker": market.get("ticker"),
                "event_ticker": market.get("event_ticker"),
                "title": market.get("title"),
                "status": market.get("status"),
                "market_type": market.get("market_type"),
                "yes_bid_dollars": market.get("yes_bid_dollars"),
                "yes_ask_dollars": market.get("yes_ask_dollars"),
                "no_bid_dollars": market.get("no_bid_dollars"),
                "no_ask_dollars": market.get("no_ask_dollars"),
                "last_price_dollars": market.get("last_price_dollars"),
                "volume_fp": market.get("volume_fp"),
                "liquidity_dollars": market.get("liquidity_dollars"),
                "close_time": market.get("close_time"),
            }
        )

    return {
        "path": snapshot.get("path"),
        "params": snapshot.get("params"),
        "status_code": snapshot.get("status_code"),
        "market_count": len(markets),
        "sample_markets": sample_markets,
    }
