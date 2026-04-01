"""Utility helpers for formatting, config, and canonical signing."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

PRAGMA_HOME = Path(os.path.expanduser("~/.pragma"))
DEFAULT_WALLET_PATH = PRAGMA_HOME / "wallet.json"
DEFAULT_CONFIG_PATH = PRAGMA_HOME / "config.json"


def ensure_pragma_home() -> Path:
    PRAGMA_HOME.mkdir(parents=True, exist_ok=True)
    return PRAGMA_HOME


def stable_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def request_body_hash(body: Any) -> str:
    return hashlib.sha256(stable_json(body).encode("utf-8")).hexdigest()


def build_signed_request_message(
    *,
    method: str,
    route: str,
    wallet: str,
    timestamp: str,
    body_hash: str,
    owner: Optional[str] = None,
) -> str:
    lines = [
        "Pragma Market signed request",
        f"method:{str(method or '').upper()}",
        f"route:{route}",
    ]
    if owner:
        lines.append(f"owner:{owner}")
    lines.extend(
        [
            f"wallet:{wallet}",
            f"timestamp:{timestamp}",
            f"body_sha256:{body_hash}",
        ]
    )
    return "\n".join(lines)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cents_to_dollars(cents: Optional[Union[int, float]]) -> str:
    value = float(cents or 0) / 100.0
    return f"${value:,.2f}"


def lamports_to_sol(lamports: Optional[Union[int, float]]) -> float:
    return float(lamports or 0) / 1_000_000_000


def format_ts(ts: Optional[Union[int, float, str]]) -> str:
    if ts is None:
        return "-"
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            return ts
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def human_time_remaining(ts: Optional[Union[int, float]]) -> str:
    if ts is None:
        return "-"
    now = datetime.now(timezone.utc).timestamp()
    delta = int(float(ts) - now)
    overdue = delta < 0
    delta = abs(delta)
    days, remainder = divmod(delta, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    text = " ".join(parts)
    return f"overdue by {text}" if overdue else text


def expand_path(path: Union[str, os.PathLike]) -> Path:
    return Path(os.path.expanduser(str(path))).expanduser()


def short_client_order_id(prefix: str = "pm") -> str:
    return f"{prefix}-{int(time.time() * 1000):x}"[:32]
