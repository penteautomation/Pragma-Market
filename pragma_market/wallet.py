"""Solana wallet helpers for Pragma authentication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

import base58
from nacl.signing import SigningKey

from .exceptions import PragmaConfigError
from .utils import DEFAULT_WALLET_PATH, expand_path


@dataclass
class PragmaWallet:
    secret_key: bytes

    @property
    def signing_key(self) -> SigningKey:
        if len(self.secret_key) < 32:
            raise PragmaConfigError("Wallet secret key is invalid.")
        return SigningKey(self.secret_key[:32])

    @property
    def verify_key(self):
        return self.signing_key.verify_key

    @property
    def address(self) -> str:
        return base58.b58encode(bytes(self.verify_key)).decode("utf-8")

    def to_secret_key_array(self) -> list[int]:
        return list(self.secret_key)

    def sign_message(self, message: str) -> str:
        signed = self.signing_key.sign(message.encode("utf-8")).signature
        return base58.b58encode(bytes(signed)).decode("utf-8")


def generate_wallet() -> PragmaWallet:
    signing_key = SigningKey.generate()
    verify_key = bytes(signing_key.verify_key)
    return PragmaWallet(secret_key=bytes(signing_key.encode()) + verify_key)


def wallet_from_secret_key(secret_key: Iterable[int]) -> PragmaWallet:
    secret_bytes = bytes(secret_key)
    if len(secret_bytes) < 64:
        raise PragmaConfigError("Wallet file must contain a 64-byte Solana secret key array.")
    return PragmaWallet(secret_key=secret_bytes[:64])


def load_wallet(path: Optional[Union[str, Path]] = None) -> PragmaWallet:
    wallet_path = expand_path(path or DEFAULT_WALLET_PATH)
    if not wallet_path.exists():
        raise PragmaConfigError(f"Wallet file not found: {wallet_path}")
    import json

    raw = json.loads(wallet_path.read_text(encoding="utf-8"))
    return wallet_from_secret_key(raw)


def save_wallet(wallet: PragmaWallet, path: Optional[Union[str, Path]] = None) -> Path:
    wallet_path = expand_path(path or DEFAULT_WALLET_PATH)
    wallet_path.parent.mkdir(parents=True, exist_ok=True)
    wallet_path.write_text(
        __import__("json").dumps(wallet.to_secret_key_array(), indent=2) + "\n",
        encoding="utf-8",
    )
    wallet_path.chmod(0o600)
    return wallet_path
