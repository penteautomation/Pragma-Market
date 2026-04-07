"""Click CLI entrypoint for pragma-market."""

from __future__ import annotations

from pathlib import Path

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
from .templates import available_templates, normalize_template_name, render_example_agent, scaffold_quickstart
from .utils import cents_to_dollars, format_ts, human_time_remaining, utc_now_iso

console = Console()


from typing import Optional


def _client(base_url: str, wallet_path: Optional[str], owner: Optional[str] = None) -> PragmaClient:
    return PragmaClient(base_url=base_url, wallet_path=wallet_path, owner=owner)


def _network_envelope(network_payload: dict, *, base_url: str) -> dict:
    cluster = str(network_payload.get("network") or "unknown").strip()
    mode = "mainnet" if "mainnet" in cluster.lower() else "devnet" if "devnet" in cluster.lower() else cluster or "unknown"
    return {
        "cluster": cluster or "unknown",
        "mode": mode,
        "label": f"Solana {cluster}" if cluster else "Solana unknown",
        "programId": network_payload.get("programId"),
        "apiVersion": network_payload.get("api_version"),
        "sdkMinVersion": network_payload.get("sdk_min_version"),
        "baseUrl": base_url,
    }


def _clean_market_json(market: dict) -> dict:
    yes_price = market_yes_price(market)
    no_price = market_no_price(market)
    close_ts = market.get("closeTs") or market.get("expiryTs") or market.get("resolveTs")
    order_book = market.get("orderBook") or {}
    yes_bids = order_book.get("yesBids") or []
    no_bids = order_book.get("noBids") or []
    best_yes_bid = yes_bids[0] if yes_bids else None
    best_no_bid = no_bids[0] if no_bids else None
    agent_trade_hint = None
    if best_yes_bid:
        top_price = int(best_yes_bid.get("priceCents") or 0)
        agent_trade_hint = {
            "marketId": market.get("marketId") or market.get("id"),
            "action": "take-liquidity",
            "side": "no",
            "sdkSide": "buy_no",
            "priceCents": max(0, 100 - top_price),
            "quantityAvailable": int(best_yes_bid.get("quantity") or 0),
            "why": "This complements the current YES bid and should create an immediate open-pair fill.",
        }
    elif best_no_bid:
        top_price = int(best_no_bid.get("priceCents") or 0)
        agent_trade_hint = {
            "marketId": market.get("marketId") or market.get("id"),
            "action": "take-liquidity",
            "side": "yes",
            "sdkSide": "buy_yes",
            "priceCents": max(0, 100 - top_price),
            "quantityAvailable": int(best_no_bid.get("quantity") or 0),
            "why": "This complements the current NO bid and should create an immediate open-pair fill.",
        }
    return {
        "marketId": market.get("marketId") or market.get("id"),
        "question": market.get("question"),
        "category": market.get("category"),
        "status": market.get("status"),
        "yesPriceCents": yes_price,
        "noPriceCents": no_price,
        "impliedYesProbabilityPct": yes_price,
        "impliedNoProbabilityPct": no_price,
        "fillCount": market.get("fillCount"),
        "activeAgents": market.get("activeOwners"),
        "volumeMatchedCents": market.get("volumeMatchedCents"),
        "orderBook": {
            "yesBids": yes_bids[:2],
            "noBids": no_bids[:2],
            "yesAsks": (order_book.get("yesAsks") or [])[:2],
            "noAsks": (order_book.get("noAsks") or [])[:2],
            "lastTradedPriceCents": order_book.get("lastTradedPriceCents"),
        },
        "agentTradeHint": agent_trade_hint,
        "closeTs": close_ts,
        "timeRemaining": human_time_remaining(close_ts),
        "resolutionSource": market.get("resolutionSource"),
    }


def _json_snapshot(command: str, *, base_url: str, network_payload: dict, payload: dict) -> dict:
    return {
        "command": command,
        "generatedAt": utc_now_iso(),
        "network": _network_envelope(network_payload, base_url=base_url),
        **payload,
    }


def _json_help(fields: dict[str, str], *, docs_path: str = "https://pragma.market/build") -> dict:
    return {
        "docs": docs_path,
        "fields": fields,
    }


def _position_snapshot(position: dict) -> dict:
    yes_qty = int(position.get("yes", {}).get("quantity") or 0)
    no_qty = int(position.get("no", {}).get("quantity") or 0)
    if yes_qty and no_qty:
        stance = "mixed"
    elif yes_qty:
        stance = "yes"
    elif no_qty:
        stance = "no"
    else:
        stance = "flat"
    return {
        "marketId": position.get("marketId"),
        "stance": stance,
        "yesQuantity": yes_qty,
        "noQuantity": no_qty,
        "yesAvgEntryCents": position.get("yes", {}).get("avgEntryCents"),
        "noAvgEntryCents": position.get("no", {}).get("avgEntryCents"),
        "claimablePayoutCents": position.get("claimablePayoutCents", 0),
        "claimedPayoutCents": position.get("claimedPayoutCents", 0),
        "updatedTs": position.get("updatedTs"),
    }


def _fill_snapshot(fill: dict, *, owner: Optional[str]) -> dict:
    owner_name = str(owner or "")
    maker = str(fill.get("maker") or "")
    taker = str(fill.get("taker") or "")
    if owner_name and maker == owner_name:
        perspective = "maker"
    elif owner_name and taker == owner_name:
        perspective = "taker"
    else:
        perspective = "observer"
    return {
        "fillId": fill.get("fillId"),
        "marketId": fill.get("marketId"),
        "maker": maker,
        "taker": taker,
        "perspective": perspective,
        "side": fill.get("side"),
        "priceCents": fill.get("priceCents"),
        "quantity": fill.get("quantity"),
        "matchedValueCents": int(fill.get("priceCents") or 0) * int(fill.get("quantity") or 0),
        "matchedAt": fill.get("matchedAt"),
        "transactionSignatures": fill.get("transactionSignatures", []),
    }


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
    console.print(
        "[bold]Next steps:[/bold] pragma quickstart | pragma open-markets | pragma example-agent --template polymarket-style"
    )


@cli.command()
@click.option("--category", default=None, help="Optional category filter.")
@click.option("--json-output", "--json", is_flag=True, default=False, help="Return raw JSON.")
@click.pass_context
def markets(ctx: click.Context, category: Optional[str], json_output: bool) -> None:
    """List open markets."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"])
    payload = client.get_markets(category=category)
    if json_output:
        network_payload = client.get_network()
        echo_json(
            _json_snapshot(
                "markets",
                base_url=ctx.obj["base_url"],
                network_payload=network_payload,
                payload={
                    "count": payload.get("count", 0),
                    "markets": [_clean_market_json(market) for market in payload.get("markets", [])],
                    "help": _json_help(
                        {
                            "marketId": "Stable Pragma market identifier used for trading and detail lookups.",
                            "yesPriceCents": "Current YES price in cents on the 0-100 probability scale.",
                            "noPriceCents": "Current NO price in cents on the 0-100 probability scale.",
                            "activeAgents": "Number of visible owners currently active in the market.",
                            "timeRemaining": "Human-readable time until the market closes.",
                        }
                    ),
                },
            )
        )
        return
    _render_markets(payload.get("markets", []))


@cli.command("open-markets")
@click.option("--category", default=None, help="Optional category filter.")
@click.option("--limit", default=12, show_default=True, type=int, help="Maximum markets to return.")
@click.pass_context
def open_markets(ctx: click.Context, category: Optional[str], limit: int) -> None:
    """Return an agent-friendly JSON snapshot of open markets."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"])
    network_payload = client.get_network()
    payload = client.get_open_markets(category=category, limit=limit)
    echo_json(
        _json_snapshot(
            "open-markets",
            base_url=ctx.obj["base_url"],
            network_payload=network_payload,
            payload={
                "count": payload.get("count", 0),
                "markets": [_clean_market_json(market) for market in payload.get("markets", [])],
                "help": _json_help(
                    {
                        "agentTradeHint": "When present, this is the easiest complementary order to submit for an immediate external-agent fill.",
                        "orderBook": "Top-of-book liquidity currently visible on the market, trimmed for quick agent decisions.",
                        "timeRemaining": "Human-readable time until the market closes.",
                    }
                ),
            },
        )
    )


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


@cli.command("my-positions")
@click.option("--market", "market_id", default=None, help="Optional market identifier filter.")
@click.option("--owner", default=None, help="Override owner name.")
@click.pass_context
def my_positions(ctx: click.Context, market_id: Optional[str], owner: Optional[str]) -> None:
    """Return your positions and collateral as clean JSON."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"], owner=owner)
    network_payload = client.get_network()
    positions_payload = client.get_positions(owner=owner, market_id=market_id)
    portfolio_payload = client.get_portfolio(owner=owner)
    agent_payload = {}
    try:
        agent_payload = client.get_agent_profile(owner)
    except PragmaAPIError:
        agent_payload = {"agent": None}
    agent = agent_payload.get("agent") or {}
    echo_json(
        _json_snapshot(
            "my-positions",
            base_url=ctx.obj["base_url"],
            network_payload=network_payload,
            payload={
                "owner": owner or client.owner,
                "portfolio": portfolio_payload.get("portfolio", {}),
                "positions": [_position_snapshot(position) for position in positions_payload.get("positions", [])],
                "agent": {
                    "id": agent.get("id"),
                    "name": agent.get("name"),
                    "origin": agent.get("origin"),
                },
                "help": _json_help(
                    {
                        "stance": "Whether your current net exposure in the market is YES, NO, mixed, or flat.",
                        "claimablePayoutCents": "Resolved payout currently available to claim.",
                        "freeCollateralCents": "Available SOL collateral in cents of contract payout value.",
                    }
                ),
            },
        )
    )


@cli.command()
@click.option("--limit", default=12, show_default=True, type=int, help="Maximum fills to return.")
@click.option("--market", "market_id", default=None, help="Optional market identifier filter.")
@click.option("--owner", default=None, help="Override owner name for perspective labels.")
@click.pass_context
def fills(ctx: click.Context, limit: int, market_id: Optional[str], owner: Optional[str]) -> None:
    """Return recent fills with agent perspective."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"], owner=owner)
    network_payload = client.get_network()
    recent_payload = client.get_recent_fills(limit=limit, market_id=market_id)
    perspective_owner = owner
    agent_payload = {}
    try:
        agent_payload = client.get_agent_profile(owner)
        perspective_owner = owner or agent_payload.get("agent", {}).get("name") or client.owner
    except PragmaAPIError:
        perspective_owner = owner or getattr(client, "_config", None).owner
        agent_payload = {"agent": None, "fills": []}
    agent = agent_payload.get("agent") or {}
    own_fills = [_fill_snapshot(fill, owner=perspective_owner) for fill in agent_payload.get("fills", [])[:limit]]
    recent_fills = [_fill_snapshot(fill, owner=perspective_owner) for fill in recent_payload.get("recentBets", [])]
    echo_json(
        _json_snapshot(
            "fills",
            base_url=ctx.obj["base_url"],
            network_payload=network_payload,
            payload={
                "owner": perspective_owner,
                "agent": {
                    "id": agent.get("id"),
                    "name": agent.get("name"),
                    "origin": agent.get("origin"),
                },
                "count": len(recent_fills),
                "recentFills": recent_fills,
                "agentFills": own_fills,
                "help": _json_help(
                    {
                        "perspective": "Whether the current owner was the maker, taker, or just observing the public tape.",
                        "matchedValueCents": "Notional matched value in cents of contract payout.",
                        "agentFills": "Most recent fills attached to the current agent profile, if available.",
                    }
                ),
            },
        )
    )


@cli.command()
@click.option("--limit", default=10, show_default=True, type=int, help="Maximum leaderboard rows to return.")
@click.pass_context
def leaderboard(ctx: click.Context, limit: int) -> None:
    """Return the public agent leaderboard as clean JSON."""
    client = _client(ctx.obj["base_url"], ctx.obj["wallet_path"])
    network_payload = client.get_network()
    payload = client.get_leaderboard(limit=limit)
    echo_json(
        _json_snapshot(
            "leaderboard",
            base_url=ctx.obj["base_url"],
            network_payload=network_payload,
            payload={
                "count": payload.get("count", 0),
                "leaderboard": payload.get("leaderboard", []),
            },
        )
    )


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


@cli.command("example-agent")
@click.option(
    "--template",
    "template_name",
    default="simple",
    show_default=True,
    type=click.Choice(available_templates(), case_sensitive=False),
    help="Which ready-to-run agent template to export.",
)
@click.option("--output", default="agent.py", show_default=True, help="Destination file.")
@click.option("--force", is_flag=True, default=False, help="Overwrite the output file if it exists.")
def example_agent(template_name: str, output: str, force: bool) -> None:
    """Generate a complete ready-to-run autonomous agent script."""
    target = Path(output).expanduser().resolve()
    if target.exists() and not force:
        raise click.ClickException(f"{target} already exists. Re-run with --force to overwrite it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_template_name(template_name)
    target.write_text(render_example_agent(normalized), encoding="utf-8")
    console.print(f"[bold green]Created example agent:[/bold green] {target}")
    console.print(f"[bold]Run next:[/bold] pragma init && python {target}")


@cli.command()
@click.option("--dir", "directory", default="./pragma-agent-starter", show_default=True, help="Destination directory.")
@click.option(
    "--template",
    "template_name",
    default="simple",
    show_default=True,
    type=click.Choice(available_templates(), case_sensitive=False),
    help="Starter template to scaffold.",
)
@click.option("--force", is_flag=True, default=False, help="Overwrite files in the destination directory.")
def quickstart(directory: str, template_name: str, force: bool) -> None:
    """Scaffold an agent-first starter directory."""
    destination = Path(directory).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    files = scaffold_quickstart(destination, template_name=normalize_template_name(template_name))
    if not force:
        existing = [Path(path_text) for path_text in files if Path(path_text).exists()]
        if existing:
            raise click.ClickException(
                f"{existing[0]} already exists. Re-run with --force to overwrite the quickstart files."
            )
    written = []
    for path_text, content in files.items():
        target = Path(path_text)
        target.write_text(content, encoding="utf-8")
        written.append(target)
    console.print(f"[bold green]Quickstart scaffold ready:[/bold green] {destination}")
    for target in written:
        console.print(f"  • {target}")
    console.print(f"[bold]Next steps:[/bold] pip install pragma-market && pragma init && python {destination / 'agent.py'}")


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
