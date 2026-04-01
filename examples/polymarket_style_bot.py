"""Autonomous Pragma Market trading bot template."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from pragma_market import PragmaClient

LOG_PATH = Path(os.environ.get("PRAGMA_LOG_PATH", "pragma-bot.log"))
BASE_URL = os.environ.get("PRAGMA_BASE_URL", "https://api.pragma.market")
WALLET_PATH = os.environ.get("PRAGMA_WALLET_PATH", "~/.pragma/wallet.json")
BET_SIZE = int(os.environ.get("PRAGMA_BET_SIZE", "1"))
YES_THRESHOLD = int(os.environ.get("PRAGMA_YES_THRESHOLD", "45"))
NO_THRESHOLD = int(os.environ.get("PRAGMA_NO_THRESHOLD", "65"))
POLL_INTERVAL = int(os.environ.get("PRAGMA_POLL_INTERVAL", "300"))
SOURCE = os.environ.get("PRAGMA_SOURCE", "pragma-bot-template")


logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def ensure_initialized(client: PragmaClient) -> None:
    if client.wallet_path.exists():
        try:
            _ = client.owner
            return
        except Exception:
            pass
    result = client.init_agent(source=SOURCE)
    logging.info("initialized wallet=%s agent=%s", result["wallet"], result["registration"]["agent"]["name"])


def select_trades(client: PragmaClient) -> list[tuple[str, str, int]]:
    payload = client.get_markets()
    actions = []
    for market in payload.get("markets", []):
        market_id = market["marketId"]
        yes_price = int(market.get("yesPriceCents") or 50)
        if yes_price < YES_THRESHOLD:
            actions.append((market_id, "yes", yes_price))
        elif yes_price > NO_THRESHOLD:
            no_price = int(market.get("noPriceCents") or (100 - yes_price))
            actions.append((market_id, "no", no_price))
    return actions


def claim_available(client: PragmaClient) -> None:
    results = client.claim_all()
    if results:
        logging.info("claimed payouts count=%s", len(results))


def run() -> None:
    client = PragmaClient(base_url=BASE_URL, wallet_path=WALLET_PATH, source=SOURCE)
    ensure_initialized(client)
    backoff = 5
    while True:
        try:
            claim_available(client)
            trades = select_trades(client)
            for market_id, side, price_cents in trades:
                response = client.place_order(
                    market_id=market_id,
                    side=side,
                    price_cents=price_cents,
                    contracts=BET_SIZE,
                )
                order_id = response.get("order", {}).get("orderId")
                logging.info("placed order market=%s side=%s price=%s order=%s", market_id, side, price_cents, order_id)
            backoff = 5
            time.sleep(POLL_INTERVAL)
        except Exception as error:
            logging.exception("bot cycle failed: %s", error)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)


if __name__ == "__main__":
    run()
