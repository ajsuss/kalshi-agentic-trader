from __future__ import annotations

from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_markets_page(
    client,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    response = client.public_get("/trade-api/v2/markets", params=params)
    return response.json()


def summarize_markets_page(payload: dict[str, Any]) -> dict[str, Any]:
    markets = payload.get("markets", [])
    summaries = []

    if isinstance(markets, list):
        for market in markets:
            summaries.append(
                {
                    "ticker": market.get("ticker"),
                    "event_ticker": market.get("event_ticker"),
                    "status": market.get("status"),
                    "title": market.get("title"),
                    "subtitle": market.get("sub_title", market.get("subtitle")),
                    "market_type": market.get("market_type"),
                    "close_time": market.get("close_time"),
                    "yes_bid_dollars": market.get("yes_bid_dollars"),
                    "yes_ask_dollars": market.get("yes_ask_dollars"),
                    "no_bid_dollars": market.get("no_bid_dollars"),
                    "no_ask_dollars": market.get("no_ask_dollars"),
                    "last_price_dollars": market.get("last_price_dollars"),
                    "volume_fp": market.get("volume_fp"),
                    "liquidity_dollars": market.get("liquidity_dollars"),
                    "yes_bid_size_fp": market.get("yes_bid_size_fp"),
                    "yes_ask_size_fp": market.get("yes_ask_size_fp"),
                    "no_bid_size_fp": market.get("no_bid_size_fp"),
                    "no_ask_size_fp": market.get("no_ask_size_fp"),
                }
            )

    return {
        "cursor": payload.get("cursor"),
        "market_count": len(summaries),
        "markets": summaries,
    }


def _is_reasonably_tradable(market: dict[str, Any]) -> bool:
    status = market.get("status")
    market_type = market.get("market_type")

    yes_bid = _to_float(market.get("yes_bid_dollars"), default=-1.0)
    yes_ask = _to_float(market.get("yes_ask_dollars"), default=-1.0)
    no_bid = _to_float(market.get("no_bid_dollars"), default=-1.0)
    no_ask = _to_float(market.get("no_ask_dollars"), default=-1.0)

    if status != "active":
        return False

    if market_type != "binary":
        return False

    dead_zero_book = yes_bid == 0.0 and yes_ask == 0.0
    dead_one_book = no_bid == 1.0 and no_ask == 1.0
    if dead_zero_book and dead_one_book:
        return False

    has_yes_quote = 0.0 < yes_ask < 1.0
    has_no_quote = 0.0 < no_bid < 1.0 or 0.0 < no_ask < 1.0

    return has_yes_quote or has_no_quote


def _score_market(market: dict[str, Any]) -> float:
    score = 0.0

    liquidity = _to_float(market.get("liquidity_dollars"))
    volume = _to_float(market.get("volume_fp"))
    yes_bid = _to_float(market.get("yes_bid_dollars"), default=-1.0)
    yes_ask = _to_float(market.get("yes_ask_dollars"), default=-1.0)
    no_bid = _to_float(market.get("no_bid_dollars"), default=-1.0)
    no_ask = _to_float(market.get("no_ask_dollars"), default=-1.0)
    last_price = _to_float(market.get("last_price_dollars"), default=-1.0)
    yes_ask_size = _to_float(market.get("yes_ask_size_fp"))
    no_bid_size = _to_float(market.get("no_bid_size_fp"))

    if market.get("status") == "active":
        score += 25.0

    if market.get("market_type") == "binary":
        score += 10.0

    if 0.0 < last_price < 1.0:
        score += 10.0

    if 0.0 < yes_ask < 1.0:
        score += 8.0

    if 0.0 < no_bid < 1.0:
        score += 8.0

    score += min(liquidity, 5000.0) / 25.0
    score += min(volume, 5000.0) / 50.0
    score += min(yes_ask_size, 1000.0) / 100.0
    score += min(no_bid_size, 1000.0) / 100.0

    if 0.0 <= yes_bid <= yes_ask <= 1.0:
        score -= (yes_ask - yes_bid) * 30.0

    if 0.0 <= no_bid <= no_ask <= 1.0:
        score -= (no_ask - no_bid) * 30.0

    return round(score, 4)


def rank_market_candidates(
    market_summaries: list[dict[str, Any]],
    top_n: int = 10,
) -> list[dict[str, Any]]:
    filtered = [m for m in market_summaries if _is_reasonably_tradable(m)]

    ranked = []
    for market in filtered:
        scored = dict(market)
        scored["scan_score"] = _score_market(market)
        ranked.append(scored)

    ranked.sort(
        key=lambda item: (
            item.get("scan_score", 0.0),
            _to_float(item.get("liquidity_dollars")),
            _to_float(item.get("volume_fp")),
            _to_float(item.get("yes_ask_size_fp")),
            _to_float(item.get("no_bid_size_fp")),
        ),
        reverse=True,
    )

    return ranked[:top_n]


def scan_market_universe(
    client,
    pages: int = 5,
    limit_per_page: int = 25,
    top_n: int = 15,
) -> dict[str, Any]:
    cursor: str | None = None
    pages_scanned = 0
    raw_market_count = 0
    by_ticker: dict[str, dict[str, Any]] = {}

    for _ in range(pages):
        payload = fetch_markets_page(client, limit=limit_per_page, cursor=cursor)
        page = summarize_markets_page(payload)

        for market in page["markets"]:
            ticker = market.get("ticker")
            if ticker:
                by_ticker[ticker] = market

        raw_market_count += page["market_count"]
        pages_scanned += 1

        cursor = page.get("cursor")
        if not cursor:
            break

    deduped_markets = list(by_ticker.values())
    ranked = rank_market_candidates(deduped_markets, top_n=top_n)

    return {
        "pages_scanned": pages_scanned,
        "raw_market_count": raw_market_count,
        "deduped_market_count": len(deduped_markets),
        "top_candidates": ranked,
    }