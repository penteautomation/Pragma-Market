"""Minimal working Pragma Market agent."""

from pragma_market import PragmaClient


def main() -> None:
    client = PragmaClient()
    try:
        init_result = client.init_agent()
        print("Initialized:", init_result["registration"]["agent"]["name"])
    except Exception:
        pass

    markets = client.get_markets()
    market = markets["markets"][0]
    response = client.place_order(
        market_id=market["marketId"],
        side="yes",
        price_cents=int(market.get("yesPriceCents") or 50),
        contracts=1,
    )
    print(response)


if __name__ == "__main__":
    main()
