"""Order-side helpers."""

from __future__ import annotations

from .exceptions import PragmaValidationError


def normalize_side(side: str) -> str:
    side_value = str(side or "").strip().lower()
    mapping = {
        "yes": "buy_yes",
        "buy_yes": "buy_yes",
        "buy-yes": "buy_yes",
        "no": "buy_no",
        "buy_no": "buy_no",
        "buy-no": "buy_no",
        "sell_yes": "sell_yes",
        "sell-yes": "sell_yes",
        "sell_no": "sell_no",
        "sell-no": "sell_no",
    }
    if side_value not in mapping:
        raise PragmaValidationError(
            "side must be one of yes, no, buy_yes, buy_no, sell_yes, or sell_no"
        )
    return mapping[side_value]
