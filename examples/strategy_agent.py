"""Example strategy agent using a simple price threshold."""

from pragma_market import PragmaClient


def main() -> None:
    client = PragmaClient()
    markets = client.get_markets()["markets"]
    for market in markets:
        yes_price = int(market.get("yesPriceCents") or 50)
        if yes_price < 40:
            response = client.place_order(
                market_id=market["marketId"],
                side="yes",
                price_cents=yes_price,
                contracts=1,
            )
            print("Placed order:", response.get("order", {}).get("orderId"))
            break
    else:
        print("No qualifying markets found.")


if __name__ == "__main__":
    main()
