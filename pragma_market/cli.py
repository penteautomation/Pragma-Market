"""Click CLI entrypoint for pragma-market."""

from __future__ import annotations

import json
import click
from rich.console import Console
from rich.table import Table

from .client import DEFAULT_BASE_URL, PragmaClient, echo_json
from .exceptions import (
    PragmaAPIError,
    PragmaConfigError,
    PragmaError,
    PragmaNotRegisteredError,
    PragmaOutdatedError,
)
from .markets import market_no_price, market_yes_price
from .utils import cents_to_dollars, format_ts, human_time_remaining

console = Console()


from typing import Optional


def _client(base_url: str, wallet_path: Optional[str], owner: Optional[str] = None) -> PragmaClient:
    return PragmaClient(base_url=base_url, wallet_path=wallet_path, owner=owner)


def _render_markets(markets: list[dict]) -> None:
    table = Table(title="Pragma Markets", show_lines=False)
    table.add_column("ID", overflow="fold")
    table.add_column("Question", overflow="fold", max_width=44)
    table.add_column("YES", justify="right")
    table.add_column("NO", justify="right")
    table.add_column("Volume", justify="right")
    table.add_column("Closes", justify="left")
    table.add_column("Time Left", justify="left")
    for market in markets:
        close_ts = market.get("expiryTs") or market.get("closeTs") or market.get("resolveTs")
        table.add_row(
            str(market.get("marketId") or market.get("id") or "-"),
            str(market.get("question") or "-"),
            f"{market_yes_price(market)}c",
            f"{market_no_price(market)}c",
            cents_to_dollars(market.get("volumeMatchedCents")),
            format_ts(close_ts),
            human_time_remaining(close_ts),
        )
    console.print(table)


def _render_status(status_payload: dict) -> None:
    balance = status_payload["balance"]
    portfolio = status_payload["portfolio"]
    positions = status_payload["positions"]
    orders = status_payload["orders"]
    console.print(f"[bold]Wallet:[/bold] {status_payload['wallet']}")
    console.print(f"[bold]Balance:[/bold] {balance['sol']:.6f} SOL")
    console.print(
        f"[bold]Collateral:[/bold] free {cents_to_dollars(portfolio.get('freeCollateralCents'))} | "
        f"locked {cents_to_dollars(portfolio.get('lockedCollateralCents'))}"
    )

    positions_table = Table(title="Positions")
    positions_table.add_column("Market")
    positions_table.add_column("YES Qty", justify="right")
    positions_table.add_column("NO Qty", justify="right")
    positions_table.add_column("Claimable", justify="right")
    positions_table.add_column("Updated")
    for position in positions:
        positions_table.add_row(
            position.get("marketId", "-"),
            str(position.get("yes", {}).get("quantity", 0)),
            str(position.get("no", {}).get("quantity", 0)),
            cents_to_dollars(position.get("claimablePayoutCents")),
            format_ts(position.get("updatedTs")),
        )
    console.print(positions_table)

    orders_table = Table(title="Orders")
    orders_table.add_column("Order")
    orders_table.add_column("Market")
    orders_table.add_column("Side")
    orders_table.add_column("Price", justify="right")
    orders_table.add_column("Qty", justify="right")
    orders_table.add_column("Status")
    for order in orders:
        orders_table.add_row(
            str(order.get("orderId", "-")),
            str(order.get("marketId", "-")),
            str(order.get("side", "-")),
            f"{order.get('priceCents', '-')}" + ("c" if order.get("priceCents") is not None else ""),
            str(order.get("quantity", "-")),
            str(order.get("status", "unknown")),
        )
    console.print(orders_table)


@click.group()
@click.option("--base-url", default=DEFAULT_BASE_URL, show_default=True)
@click.option("--wallet-path", default=None, help="Override wallet path.")
@click.pass_context
def cli(ctx: click.Context, base_url: str, wallet_path: str | None) -> None:
    """Pragma Market CLI."""
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = base_url
    ctx.obj["wallet_path"] = wallet_path


@cli.command()
@click.option("--name", default=None, help="Agent name. Defaults to pragma-cli-<wallet>.")
@click.option("--source", default="pragma-cli", show_default=True)
@click.option("--overwrite-wallet", is_flag=True, default=False)
@click.pass_context
def init(ctx: click.Context, name: Optional[str], source: str, overwrite_wallet: bool) -> None:
    """Generate wallet, fund it, and register the agent."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"])
    result = client.init_agent(name=name, source=source, overwrite_wallet=overwrite_wallet)
    console.print(f"[bold green]Wallet created:[/bold green] {result['wallet']}")
    console.print(f"[bold green]Wallet path:[/bold green] {result['wallet_path']}")
    console.print(f"[bold green]Balance:[/bold green] {result['balance']['sol']:.6f} SOL")
    console.print(f"[bold green]Agent:[/bold green] {result['registration']['agent']['name']}")
    console.print("[bold]Next steps:[/bold] pragma markets | pragma bet --market MARKET_ID --side yes --price 56 --contracts 1")


@cli.command()
@click.option("--category", default=None, help="Optional category filter.")
@click.option("--json-output", "--json", is_flag=True, default=False, help="Return raw JSON.")
@click.pass_context
def markets(ctx: click.Context, category: Optional[str], json_output: bool) -> None:
    """List open markets."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"])
    payload = client.get_markets(category=category)
    if json_output:
        echo_json(payload)
        return
    _render_markets(payload.get("markets", []))


@cli.command()
@click.option("--market", "market_id", required=True, help="Market identifier.")
@click.option("--side", required=True, type=click.Choice(["yes", "no", "buy_yes", "buy_no", "sell_yes", "sell_no"], case_sensitive=False))
@click.option("--price", "price_cents", required=True, type=int)
@click.option("--contracts", required=True, type=int)
@click.option("--owner", default=None, help="Override registered owner name.")
@click.option("--time-in-force", default="ioc", type=click.Choice(["gtc", "ioc", "fok"], case_sensitive=False))
@click.pass_context
def bet(
    ctx: click.Context,
    market_id: str,
    side: str,
    price_cents: int,
    contracts: int,
    owner: Optional[str],
    time_in_force: str,
) -> None:
    """Place a signed order."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"], owner=owner)
    payload = client.place_order(
        market_id=market_id,
        side=side,
        price_cents=price_cents,
        contracts=contracts,
        owner=owner,
        time_in_force=time_in_force,
    )
    order = payload.get("order", {})
    signatures = payload.get("transactionSignatures", [])
    console.print(f"[bold green]Order accepted:[/bold green] {order.get('orderId', '-')}")
    console.print(f"[bold]Market:[/bold] {order.get('marketId')}")
    console.print(f"[bold]Side:[/bold] {order.get('side')} @ {order.get('priceCents')}c x {order.get('quantity')}")
    console.print(f"[bold]Transaction signatures:[/bold] {', '.join(signatures) if signatures else 'none returned'}")
    if payload.get("fills"):
        console.print("[bold green]Fills matched immediately.[/bold green]")


@cli.command()
@click.option("--json-output", "--json", is_flag=True, default=False, help="Return raw JSON.")
@click.pass_context
def status(ctx: click.Context, json_output: bool) -> None:
    """Show wallet, positions, open orders, and claimable payouts."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"])
    payload = client.status()
    if json_output:
        echo_json(payload)
        return
    _render_status(payload)


@cli.command()
@click.option("--market", "market_id", default=None, help="Claim one market.")
@click.option("--all", "claim_all_flag", is_flag=True, default=False, help="Claim all available payouts.")
@click.pass_context
def claim(ctx: click.Context, market_id: Optional[str], claim_all_flag: bool) -> None:
    """Claim resolved payouts."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"])
    if claim_all_flag:
        results = client.claim_all()
        echo_json(results)
        return
    if not market_id:
        raise click.UsageError("Provide --market MARKET_ID or use --all")
    echo_json(client.claim(market_id))


@cli.command()
@click.pass_context
def network(ctx: click.Context) -> None:
    """Show current network metadata."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"])
    echo_json(client.get_network())


@cli.command()
@click.pass_context
def fund(ctx: click.Context) -> None:
    """Request more devnet SOL."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"])
    echo_json(client.fund())


def main() -> int:
    try:
        cli(obj={})
    except PragmaNotRegisteredError:
        console.print("❌ No registered agent found.")
        console.print("Run pragma init first to create your wallet and register your agent.")
        return 1
    except PragmaOutdatedError as error:
        console.print(f"[bold red]Error:[/bold red] {error}")
        console.print("Run: pip install --upgrade pragma-market")
        return 1
    except (PragmaError, PragmaAPIError, PragmaConfigError) as error:
        if isinstance(error, PragmaConfigError) and 'Wallet file not found' in str(error):
            console.print("❌ No registered agent found.")
            console.print("Run pragma init first to create your wallet and register your agent.")
            return 1
        console.print(f"[bold red]Error:[/bold red] {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
