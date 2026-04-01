"""Market helpers and display shaping."""

from __future__ import annotations

from typing import Any


def open_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [market for market in markets if str(market.get("status", "")).lower() == "open"]


def filter_markets(
    markets: list[dict[str, Any]],
    *,
    category: str | None = None,
    status: str | None = "open",
) -> list[dict[str, Any]]:
    result = markets
    if status:
        result = [market for market in result if str(market.get("status", "")).lower() == status.lower()]
    if category:
        result = [market for market in result if str(market.get("category", "")).lower() == category.lower()]
    return result


def market_yes_price(market: dict[str, Any]) -> int:
    return int(
        market.get("yesPriceCents")
        or market.get("consensusPriceCents")
        or market.get("lastTradedPriceCents")
        or 0
    )


def market_no_price(market: dict[str, Any]) -> int:
    return int(
        market.get("noPriceCents")
        or market.get("consensusNoPriceCents")
        or (100 - market_yes_price(market))
    )
