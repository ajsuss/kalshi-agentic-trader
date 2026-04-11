from __future__ import annotations

from typing import Any


def _safe_get(d: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    return d.get(key, default)


def fetch_market_by_ticker(client, market_ticker: str) -> dict[str, Any]:
    market_ticker = market_ticker.strip()
    response = client.public_get(f"/trade-api/v2/markets/{market_ticker}")
    return response.json()


def summarize_market_lookup(payload: dict[str, Any], requested_ticker: str) -> dict[str, Any]:
    market = payload.get("market", payload)

    return {
        "requested_market_ticker": requested_ticker,
        "market_ticker": _safe_get(market, "ticker"),
        "event_ticker": _safe_get(market, "event_ticker"),
        "status": _safe_get(market, "status"),
        "title": _safe_get(market, "title"),
        "subtitle": _safe_get(market, "subtitle", _safe_get(market, "sub_title")),
        "yes_bid_dollars": _safe_get(market, "yes_bid_dollars"),
        "yes_ask_dollars": _safe_get(market, "yes_ask_dollars"),
        "no_bid_dollars": _safe_get(market, "no_bid_dollars"),
        "no_ask_dollars": _safe_get(market, "no_ask_dollars"),
        "last_price_dollars": _safe_get(market, "last_price_dollars"),
        "volume_fp": _safe_get(market, "volume_fp"),
        "liquidity_dollars": _safe_get(market, "liquidity_dollars"),
        "close_time": _safe_get(market, "close_time"),
    }


def fetch_event_by_ticker(client, event_ticker: str, with_nested_markets: bool = True) -> dict[str, Any]:
    event_ticker = event_ticker.strip()
    params = {"with_nested_markets": "true" if with_nested_markets else "false"}
    response = client.public_get(f"/trade-api/v2/events/{event_ticker}", params=params)
    return response.json()


def summarize_event_lookup(payload: dict[str, Any], requested_event_ticker: str) -> dict[str, Any]:
    event = payload.get("event", payload)
    markets = payload.get("markets") or event.get("markets") or []

    return {
        "requested_event_ticker": requested_event_ticker,
        "event_ticker": _safe_get(event, "event_ticker", _safe_get(event, "ticker")),
        "series_ticker": _safe_get(event, "series_ticker"),
        "status": _safe_get(event, "status"),
        "title": _safe_get(event, "title"),
        "subtitle": _safe_get(event, "sub_title", _safe_get(event, "subtitle")),
        "market_count": len(markets) if isinstance(markets, list) else 0,
    }


def build_targeted_market_context(
    market_payload: dict[str, Any],
    event_payload: dict[str, Any],
    target_market_ticker: str,
    peer_limit: int = 5,
) -> dict[str, Any]:
    market = market_payload.get("market", market_payload)
    event = event_payload.get("event", event_payload)
    event_markets = event_payload.get("markets") or event.get("markets") or []

    peers = []
    if isinstance(event_markets, list):
        for item in event_markets:
            item_ticker = item.get("ticker")
            if item_ticker == target_market_ticker:
                continue
            peers.append(
                {
                    "ticker": item_ticker,
                    "title": item.get("title"),
                    "subtitle": item.get("sub_title", item.get("subtitle")),
                    "status": item.get("status"),
                    "last_price_dollars": item.get("last_price_dollars"),
                    "yes_bid_dollars": item.get("yes_bid_dollars"),
                    "yes_ask_dollars": item.get("yes_ask_dollars"),
                }
            )

    peers = peers[:peer_limit]

    return {
        "target_market": {
            "ticker": market.get("ticker"),
            "event_ticker": market.get("event_ticker"),
            "title": market.get("title"),
            "subtitle": market.get("sub_title", market.get("subtitle")),
            "status": market.get("status"),
            "last_price_dollars": market.get("last_price_dollars"),
            "yes_bid_dollars": market.get("yes_bid_dollars"),
            "yes_ask_dollars": market.get("yes_ask_dollars"),
            "no_bid_dollars": market.get("no_bid_dollars"),
            "no_ask_dollars": market.get("no_ask_dollars"),
            "volume_fp": market.get("volume_fp"),
            "liquidity_dollars": market.get("liquidity_dollars"),
        },
        "event_context": {
            "event_ticker": event.get("event_ticker", event.get("ticker")),
            "series_ticker": event.get("series_ticker"),
            "title": event.get("title"),
            "subtitle": event.get("sub_title", event.get("subtitle")),
            "status": event.get("status"),
            "peer_market_count_included": len(peers),
            "peer_markets": peers,
        },
    }