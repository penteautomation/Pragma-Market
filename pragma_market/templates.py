"""Template helpers for the Pragma CLI."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent


TEMPLATE_ALIASES = {
    "simple": "simple",
    "starter": "simple",
    "strategy": "strategy",
    "signal": "strategy",
    "polymarket": "polymarket_style",
    "polymarket-style": "polymarket_style",
    "bot": "polymarket_style",
}


def normalize_template_name(name: str | None) -> str:
    return TEMPLATE_ALIASES.get(str(name or "simple").strip().lower(), str(name or "simple").strip().lower())


def available_templates() -> list[str]:
    return ["simple", "strategy", "polymarket-style"]


def _simple_agent() -> str:
    return dedent(
        '''\
        """Quickstart Pragma agent.

        Run:
          pragma init
          python agent.py
        """

        from __future__ import annotations

        import time

        from pragma_market import PragmaClient

        POLL_INTERVAL = 300


        def complementary_trade(market: dict) -> tuple[str, str, int] | None:
            order_book = market.get("orderBook") or {}
            yes_bids = order_book.get("yesBids") or []
            no_bids = order_book.get("noBids") or []
            if yes_bids:
                best_yes_bid = yes_bids[0]
                return market["marketId"], "no", 100 - int(best_yes_bid["priceCents"])
            if no_bids:
                best_no_bid = no_bids[0]
                return market["marketId"], "yes", 100 - int(best_no_bid["priceCents"])
            return None


        def ensure_initialized(client: PragmaClient) -> None:
            if client.wallet_path.exists():
                try:
                    _ = client.owner
                    return
                except Exception:
                    pass
            result = client.init_agent(source="pragma-quickstart-template")
            agent = result["registration"]["agent"]["name"]
            print(f"Initialized {agent} on {result['wallet']}")


        def choose_trade(markets: list[dict]) -> tuple[str, str, int] | None:
            for market in markets:
                trade = complementary_trade(market)
                if trade:
                    return trade
            return None


        def main() -> None:
            client = PragmaClient()
            ensure_initialized(client)
            while True:
                payload = client.get_markets(status="open")
                trade = choose_trade(payload.get("markets", []))
                if trade:
                    market_id, side, price_cents = trade
                    response = client.place_order(
                        market_id=market_id,
                        side=side,
                        price_cents=price_cents,
                        contracts=1,
                    )
                    fills = response.get("fills", [])
                    print("Placed", side, "order", response.get("order", {}).get("orderId"), "on", market_id)
                    if fills:
                        print("Immediate fill:", fills[0]["fillId"], "kind=", fills[0]["kind"])
                else:
                    print("No crossable market found. Sleeping.")
                time.sleep(POLL_INTERVAL)


        if __name__ == "__main__":
            main()
        '''
    )


def _strategy_agent() -> str:
    return dedent(
        '''\
        """Category-aware Pragma strategy agent."""

        from __future__ import annotations

        import time

        from pragma_market import PragmaClient

        POLL_INTERVAL = 300
        TARGET_CATEGORIES = {"AI", "CRYPTO", "ECONOMICS", "TECH"}


        def ensure_initialized(client: PragmaClient) -> None:
            if client.wallet_path.exists():
                try:
                    _ = client.owner
                    return
                except Exception:
                    pass
            client.init_agent(source="pragma-example-agent")


        def select_trade(markets: list[dict]) -> tuple[str, str, int] | None:
            for market in markets:
                category = str(market.get("category") or "").upper()
                if category not in TARGET_CATEGORIES:
                    continue
                order_book = market.get("orderBook") or {}
                yes_bids = order_book.get("yesBids") or []
                no_bids = order_book.get("noBids") or []
                if yes_bids:
                    return market["marketId"], "no", 100 - int(yes_bids[0]["priceCents"])
                if no_bids:
                    return market["marketId"], "yes", 100 - int(no_bids[0]["priceCents"])
            return None


        def main() -> None:
            client = PragmaClient()
            ensure_initialized(client)
            while True:
                payload = client.get_markets(status="open")
                choice = select_trade(payload.get("markets", []))
                if not choice:
                    print("No qualifying trade this cycle.")
                    time.sleep(POLL_INTERVAL)
                    continue
                market_id, side, price_cents = choice
                response = client.place_order(
                    market_id=market_id,
                    side=side,
                    price_cents=price_cents,
                    contracts=1,
                )
                print("Placed", side, "order", response.get("order", {}).get("orderId"), "on", market_id)
                time.sleep(POLL_INTERVAL)


        if __name__ == "__main__":
            main()
        '''
    )


def _polymarket_style_agent() -> str:
    return dedent(
        '''\
        """Polymarket-style loop for Pragma.

        Fastest onboarding:
          pip install pragma-market
          pragma init
          python agent.py
        """

        from __future__ import annotations

        import logging
        import os
        import time
        from pathlib import Path

        from pragma_market import PragmaClient

        LOG_PATH = Path(os.environ.get("PRAGMA_LOG_PATH", "pragma-agent.log"))
        BASE_URL = os.environ.get("PRAGMA_BASE_URL", "https://api.pragma.market")
        WALLET_PATH = os.environ.get("PRAGMA_WALLET_PATH", "~/.pragma/wallet.json")
        BET_SIZE = int(os.environ.get("PRAGMA_BET_SIZE", "1"))
        POLL_INTERVAL = int(os.environ.get("PRAGMA_POLL_INTERVAL", "300"))
        SOURCE = os.environ.get("PRAGMA_SOURCE", "pragma-quickstart")

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
            payload = client.get_open_markets(limit=20)
            actions = []
            for market in payload.get("markets", []):
                order_book = market.get("orderBook") or {}
                yes_bids = order_book.get("yesBids") or []
                no_bids = order_book.get("noBids") or []
                if yes_bids:
                    actions.append((market["marketId"], "no", 100 - int(yes_bids[0]["priceCents"])))
                elif no_bids:
                    actions.append((market["marketId"], "yes", 100 - int(no_bids[0]["priceCents"])))
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
                    for market_id, side, price_cents in select_trades(client):
                        response = client.place_order(
                            market_id=market_id,
                            side=side,
                            price_cents=price_cents,
                            contracts=BET_SIZE,
                        )
                        order_id = response.get("order", {}).get("orderId")
                        logging.info(
                            "placed order market=%s side=%s price=%s order=%s",
                            market_id,
                            side,
                            price_cents,
                            order_id,
                        )
                    backoff = 5
                    time.sleep(POLL_INTERVAL)
                except Exception as error:
                    logging.exception("bot cycle failed: %s", error)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 300)


        if __name__ == "__main__":
            run()
        '''
    )


def render_example_agent(template_name: str) -> str:
    normalized = normalize_template_name(template_name)
    if normalized == "simple":
        return _simple_agent()
    if normalized == "strategy":
        return _strategy_agent()
    if normalized == "polymarket_style":
        return _polymarket_style_agent()
    raise ValueError(f"Unknown template: {template_name}")


def render_quickstart_readme(template_name: str) -> str:
    label = normalize_template_name(template_name).replace("_", "-")
    return dedent(
        f'''\
        # Pragma Agent Quickstart

        This starter is built for autonomous agents. It stays on the Pragma HTTP abstraction layer, so the same request flow survives the move from Solana devnet to mainnet.

        ## Fastest onboarding

        ```bash
        pip install pragma-market
        pragma init
        python agent.py
        ```

        ## Useful helper commands

        ```bash
        pragma open-markets
        pragma leaderboard
        pragma my-positions
        pragma network
        ```

        ## Included template

        - Template: `{label}`
        - Agent source tag: `pragma-quickstart`
        - Base docs: `https://pragma.market/docs`

        ## Notes

        - The CLI reports whether you are on devnet or mainnet.
        - The Python client keeps using Pragma's network abstraction layer instead of a hard-coded program ID or raw RPC integration.
        - Devnet means no real SOL is at risk. When Pragma switches to mainnet, the `network` metadata will show it.
        '''
    )


def render_env_example() -> str:
    return dedent(
        '''\
        PRAGMA_BASE_URL=https://api.pragma.market
        PRAGMA_WALLET_PATH=~/.pragma/wallet.json
        PRAGMA_BET_SIZE=1
        PRAGMA_YES_THRESHOLD=45
        PRAGMA_NO_THRESHOLD=65
        PRAGMA_POLL_INTERVAL=300
        '''
    )


def scaffold_quickstart(directory: Path, *, template_name: str) -> dict[str, str]:
    return {
        str(directory / "agent.py"): render_example_agent(template_name),
        str(directory / "README.md"): render_quickstart_readme(template_name),
        str(directory / ".env.example"): render_env_example(),
        str(directory / ".gitignore"): "__pycache__/\n*.pyc\n.env\npragma-agent.log\n",
    }
