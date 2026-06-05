"""
In-memory TTL cache — replaces Redis for local setup.
Thread-safe for asyncio (single-threaded event loop).
"""

import time
from typing import Any

_store: dict[str, tuple[Any, float]] = {}


def get(key: str) -> Any | None:
    entry = _store.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        del _store[key]
        return None
    return value


def set(key: str, value: Any, ttl: int) -> None:
    _store[key] = (value, time.monotonic() + ttl)


def delete(key: str) -> None:
    _store.pop(key, None)


def clear_prefix(prefix: str) -> int:
    keys = [k for k in list(_store.keys()) if k.startswith(prefix)]
    for k in keys:
        del _store[k]
    return len(keys)


def clear_all() -> None:
    _store.clear()
