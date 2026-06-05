"""
In-memory rolling price history for MCS multi-timeframe computation.
Stores timestamped snapshots for the last 30 minutes.
Updated every time /api/v1/prices/live is polled.
"""
import time
from collections import deque

_MAX_SECONDS = 1800  # 30-minute rolling window
_price_history: dict[str, deque] = {}  # symbol → deque of (monotonic_ts, price)


def record_prices(prices: dict) -> None:
    """Store a price snapshot. Called from the prices route on every poll."""
    now = time.monotonic()
    for symbol, data in prices.items():
        if data and isinstance(data, dict) and "price" in data:
            q = _price_history.setdefault(symbol, deque())
            q.append((now, float(data["price"])))
            # Evict entries older than 30 minutes
            while q and (now - q[0][0]) > _MAX_SECONDS:
                q.popleft()


def get_price_change_pct(symbol: str, seconds_back: int) -> float | None:
    """
    % price change from `seconds_back` seconds ago to now.
    Returns None when history is too short.
    """
    q = _price_history.get(symbol)
    if not q or len(q) < 2:
        return None

    current_price = q[-1][1]
    now = time.monotonic()
    target_ts = now - seconds_back

    # Find the recorded price closest to target_ts
    past_price = None
    best_gap = float("inf")
    for ts, price in q:
        gap = abs(ts - target_ts)
        if gap < best_gap:
            best_gap = gap
            past_price = price

    # Reject if closest point is more than 50% further than requested window
    # (avoids phantom changes when history is thin)
    if best_gap > seconds_back * 0.5 + 60:
        return None

    if past_price is None or past_price == 0:
        return None

    return (current_price - past_price) / past_price * 100


def history_depth_seconds() -> dict[str, float]:
    """How many seconds of history we have per symbol."""
    now = time.monotonic()
    return {
        sym: round(now - q[0][0]) if q else 0
        for sym, q in _price_history.items()
    }
