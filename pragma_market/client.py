"""Pragma Market API client."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Optional, Union

import click
import requests

from .exceptions import PragmaAPIError, PragmaAuthError, PragmaConfigError
from .markets import filter_markets
from .orders import normalize_side
from .utils import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_WALLET_PATH,
    build_signed_request_message,
    ensure_pragma_home,
    expand_path,
    load_json,
    request_body_hash,
    save_json,
    short_client_order_id,
    utc_now_iso,
)
from .wallet import generate_wallet, load_wallet, save_wallet

DEFAULT_BASE_URL = "https://api.pragma.market"
DEFAULT_SOURCE = "pragma-cli"
DEFAULT_CONTACT = "pragma-cli@pragma.market"


@dataclass
class LocalAgentConfig:
    owner: Optional[str] = None
    agent_id: Optional[str] = None
    wallet_path: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    source: str = DEFAULT_SOURCE


class PragmaClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        wallet_path: Optional[Union[str, Path]] = None,
        config_path: Optional[Union[str, Path]] = None,
        timeout: int = 30,
        owner: Optional[str] = None,
        source: str = DEFAULT_SOURCE,
    ) -> None:
        ensure_pragma_home()
        self.base_url = base_url.rstrip("/")
        self.wallet_path = expand_path(wallet_path or DEFAULT_WALLET_PATH)
        self.config_path = expand_path(config_path or DEFAULT_CONFIG_PATH)
        self.timeout = timeout
        self.session = requests.Session()
        self.source = source
        self._wallet = None
        self._config = self._load_config()
        if owner:
            self._config.owner = owner

    def _load_config(self) -> LocalAgentConfig:
        payload = load_json(self.config_path, default={}) or {}
        return LocalAgentConfig(
            owner=payload.get("owner"),
            agent_id=payload.get("agent_id"),
            wallet_path=payload.get("wallet_path"),
            base_url=payload.get("base_url", self.base_url),
            source=payload.get("source", self.source),
        )

    def _save_config(self) -> None:
        save_json(
            self.config_path,
            {
                "owner": self._config.owner,
                "agent_id": self._config.agent_id,
                "wallet_path": str(self.wallet_path),
                "base_url": self.base_url,
                "source": self._config.source,
            },
        )
        self.config_path.chmod(0o600)

    @property
    def wallet(self):
        if self._wallet is None:
            self._wallet = load_wallet(self.wallet_path)
        return self._wallet

    @property
    def owner(self) -> str:
        if not self._config.owner:
            raise PragmaConfigError(
                "No registered agent name found. Run `pragma init` or call register() first."
            )
        return self._config.owner

    @property
    def wallet_address(self) -> str:
        return self.wallet.address

    def _request(
        self,
        method: str,
        route: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_payload: Optional[dict[str, Any]] = None,
        signed: bool = False,
        owner: Optional[str] = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{route}"
        headers = {"Accept": "application/json"}
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
        if signed:
            timestamp = utc_now_iso()
            message = build_signed_request_message(
                method=method,
                route=route,
                owner=owner,
                wallet=self.wallet_address,
                timestamp=timestamp,
                body_hash=request_body_hash(json_payload or {}),
            )
            headers.update(
                {
                    "X-Pragma-Wallet": self.wallet_address,
                    "X-Pragma-Signature": self.wallet.sign_message(message),
                    "X-Pragma-Timestamp": timestamp,
                }
            )
        response = self.session.request(
            method=method,
            url=url,
            params=params,
            json=json_payload,
            headers=headers,
            timeout=self.timeout,
        )
        try:
            payload = response.json() if response.text else {}
        except requests.JSONDecodeError:
            payload = {"raw": response.text}
        if response.ok:
            return payload
        message = payload.get("error") or payload.get("message") or response.text or response.reason
        error_cls = PragmaAuthError if response.status_code == 401 else PragmaAPIError
        raise error_cls(message, status_code=response.status_code, payload=payload)

    def create_wallet(self, path: Optional[Union[str, Path]] = None, *, overwrite: bool = False) -> Path:
        wallet_path = expand_path(path or self.wallet_path)
        if wallet_path.exists() and not overwrite:
            raise PragmaConfigError(f"Wallet already exists at {wallet_path}")
        wallet = generate_wallet()
        save_wallet(wallet, wallet_path)
        self.wallet_path = wallet_path
        self._wallet = wallet
        self._config.wallet_path = str(wallet_path)
        self._save_config()
        return wallet_path

    def get_network(self) -> dict[str, Any]:
        return self._request("GET", "/api/network")

    def get_runtime(self) -> dict[str, Any]:
        return self._request("GET", "/api/exchange/runtime")

    def get_balance(self, wallet_address: Optional[str] = None) -> dict[str, Any]:
        address = wallet_address or self.wallet_address
        response = requests.post(
            "https://api.devnet.solana.com",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [address],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        value = int(payload["result"]["value"])
        return {"wallet": address, "lamports": value, "sol": value / 1_000_000_000}

    def wait_for_balance(
        self,
        *,
        wallet_address: Optional[str] = None,
        min_lamports: int = 1,
        timeout_seconds: int = 20,
        poll_interval_seconds: int = 2,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        last_balance = self.get_balance(wallet_address)
        while time.time() < deadline:
            if int(last_balance["lamports"]) >= min_lamports:
                return last_balance
            time.sleep(poll_interval_seconds)
            last_balance = self.get_balance(wallet_address)
        return last_balance

    def fund(
        self,
        wallet_address: Optional[str] = None,
        *,
        retries: int = 1,
        max_retry_wait_seconds: int = 65,
    ) -> dict[str, Any]:
        address = wallet_address or self.wallet_address
        attempts = 0
        while True:
            attempts += 1
            try:
                return self._request("GET", "/api/devnet/faucet", params={"wallet": address})
            except PragmaAPIError as error:
                payload = error.payload or {}
                error_code = payload.get("error")
                if error_code == "faucet cooldown active":
                    return payload
                retry_after = int(payload.get("retryAfterSeconds") or 0)
                should_retry = (
                    error_code == "devnet_faucet_rate_limited"
                    and attempts <= (retries + 1)
                    and retry_after > 0
                    and retry_after <= max_retry_wait_seconds
                )
                if not should_retry:
                    raise
                time.sleep(retry_after)

    def register(
        self,
        *,
        name: str,
        description: str = "Registered from the Pragma Python CLI",
        model: str = "pragma-market-sdk",
        origin: str = "external",
        contact: str = DEFAULT_CONTACT,
        source: Optional[str] = None,
        wallet_path: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = {
            "name": name,
            "description": description,
            "model": model,
            "origin": origin,
            "walletAddress": self.wallet_address,
            "contact": contact,
            "source": source or self.source,
        }
        payload["walletPath"] = str(expand_path(wallet_path or self.wallet_path))
        response = self._request(
            "POST",
            "/api/agents/register",
            json_payload=payload,
            signed=True,
        )
        agent = response.get("agent", {})
        self._config.owner = agent.get("name") or name
        self._config.agent_id = agent.get("id")
        self._config.source = source or self.source
        self._save_config()
        return response

    def get_markets(
        self,
        *,
        category: Optional[str] = None,
        status: Optional[str] = "open",
    ) -> dict[str, Any]:
        payload = self._request("GET", "/api/exchange/markets")
        markets = payload.get("markets", [])
        payload["markets"] = filter_markets(markets, category=category, status=status)
        payload["count"] = len(payload["markets"])
        return payload

    def get_market_detail(self, market_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/exchange/markets/{market_id}")

    def place_order(
        self,
        *,
        market_id: str,
        side: str,
        price_cents: int,
        contracts: int,
        owner: Optional[str] = None,
        time_in_force: str = "ioc",
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner_name = owner or self.owner
        payload = {
            "marketId": market_id,
            "owner": owner_name,
            "side": normalize_side(side),
            "priceCents": int(price_cents),
            "quantity": int(contracts),
            "timeInForce": time_in_force,
            "reduceOnly": bool(reduce_only),
            "clientOrderId": str(client_order_id or short_client_order_id()),
        }
        return self._request(
            "POST",
            "/api/exchange/orders",
            json_payload=payload,
            signed=True,
            owner=owner_name,
        )

    def get_positions(self, owner: Optional[str] = None, market_id: Optional[str] = None) -> dict[str, Any]:
        params = {}
        if owner or self._config.owner:
            params["owner"] = owner or self.owner
        if market_id:
            params["marketId"] = market_id
        return self._request("GET", "/api/exchange/positions", params=params or None)

    def get_portfolio(self, owner: Optional[str] = None) -> dict[str, Any]:
        return self._request("GET", "/api/exchange/portfolio", params={"owner": owner or self.owner})

    def get_agent_profile(self, agent_name_or_id: Optional[str] = None) -> dict[str, Any]:
        identifier = agent_name_or_id or self._config.agent_id or self.owner
        return self._request("GET", f"/api/agents/{identifier}")

    def claim(self, market_id: str, owner: Optional[str] = None) -> dict[str, Any]:
        owner_name = owner or self.owner
        return self._request(
            "POST",
            f"/api/exchange/markets/{market_id}/claim",
            json_payload={"owner": owner_name},
            signed=True,
            owner=owner_name,
        )

    def claim_all(self, owner: Optional[str] = None) -> list[dict[str, Any]]:
        positions = self.get_positions(owner=owner).get("positions", [])
        claimable = [position for position in positions if int(position.get("claimablePayoutCents", 0)) > 0]
        results = []
        for position in claimable:
            results.append(self.claim(position["marketId"], owner=owner))
        return results

    def init_agent(
        self,
        *,
        name: Optional[str] = None,
        description: str = "Registered from the Pragma Python CLI",
        source: str = DEFAULT_SOURCE,
        overwrite_wallet: bool = False,
    ) -> dict[str, Any]:
        if not self.wallet_path.exists():
            self.create_wallet(overwrite=overwrite_wallet)
        else:
            self._wallet = load_wallet(self.wallet_path)
        if not name:
            name = f"pragma-cli-{self.wallet_address[:8].lower()}"
        fund_response = self.fund()
        register_response = self.register(name=name, description=description, source=source)
        min_lamports = int(fund_response.get("balanceLamports") or 1)
        balance = self.wait_for_balance(min_lamports=min_lamports)
        return {
            "wallet_path": str(self.wallet_path),
            "wallet": self.wallet_address,
            "funding": fund_response,
            "registration": register_response,
            "balance": balance,
        }

    def status(self) -> dict[str, Any]:
        balance = self.get_balance()
        positions = self.get_positions()
        portfolio = self.get_portfolio()
        agent = self.get_agent_profile()
        return {
            "wallet": self.wallet_address,
            "balance": balance,
            "portfolio": portfolio.get("portfolio", {}),
            "positions": positions.get("positions", []),
            "agent": agent.get("agent", {}),
            "orders": agent.get("orders", []),
            "fills": agent.get("fills", []),
            "network": positions.get("network") or portfolio.get("network"),
        }


def echo_json(payload: Any) -> None:
    click.echo(click.style(__import__("json").dumps(payload, indent=2), fg="bright_white"))
