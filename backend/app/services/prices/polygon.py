"""
Polygon.io price fetcher for Event Memory Engine.
Fetches OHLC candles at specific timestamps to compute post-event moves.

Tickers used:
  C:XAUUSD — Gold spot (forex endpoint)
  I:DXY    — US Dollar Index (indices endpoint)
  I:TNX    — 10-Year Treasury Yield % (indices endpoint)
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_BASE = "https://api.polygon.io"

_TICKERS: dict[str, str] = {
    "XAUUSD": "C:XAUUSD",
    "DXY":    "I:DXY",
    "US10Y":  "I:TNX",
}

# Minimum delay before fetching (Polygon free tier has ~15-min delay)
_MIN_DELAY_MINUTES = 20


async def get_close_at(symbol: str, ts: datetime, window_minutes: int = 4) -> float | None:
    """
    Return the close price of `symbol` closest to `ts` (UTC).
    Searches [ts-1min, ts+window_minutes] range.
    Returns None when no data is available.
    """
    if not settings.polygon_api_key:
        return None

    ticker = _TICKERS.get(symbol)
    if not ticker:
        return None

    from_ms = int((ts - timedelta(minutes=1)).timestamp() * 1000)
    to_ms   = int((ts + timedelta(minutes=window_minutes)).timestamp() * 1000)

    url = f"{_BASE}/v2/aggs/ticker/{ticker}/range/1/minute/{from_ms}/{to_ms}"
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(url, params={
                "apiKey":   settings.polygon_api_key,
                "limit":    10,
                "sort":     "asc",
                "adjusted": "true",
            })
            if r.status_code == 403:
                logger.warning("[Polygon] 403 for %s — check API key or plan", ticker)
                return None
            if r.status_code != 200:
                logger.debug("[Polygon] %s → HTTP %d", ticker, r.status_code)
                return None
            results = r.json().get("results", [])
            if not results:
                return None
            return float(results[-1]["c"])
    except Exception as exc:
        logger.warning("[Polygon] %s fetch error: %s", symbol, exc)
        return None


def _pct_change(base: float | None, current: float | None) -> float | None:
    if base is None or current is None or base == 0:
        return None
    return round((current - base) / abs(base) * 100, 4)


async def compute_post_event_moves(event_at: datetime) -> dict[str, float | None]:
    """
    Compute price moves at 5m/15m/1h/4h windows after event_at.
    Baseline is T-1 minute. Only fills windows that have passed + delay.

    Returns dict with keys:
      gold_move_5m, gold_move_15m, gold_move_1h, gold_move_4h,
      dxy_move_1h, us10y_move_1h
    """
    now = datetime.now(UTC)
    delay = timedelta(minutes=_MIN_DELAY_MINUTES)

    baseline_ts = event_at - timedelta(minutes=1)

    # Decide which symbols we actually need baselines for
    need_gold  = any(
        now >= event_at + timedelta(minutes=m) + delay
        for m in [5, 15, 60, 240]
    )
    need_macro = now >= event_at + timedelta(minutes=60) + delay

    # Fetch baselines concurrently
    baselines = await asyncio.gather(
        get_close_at("XAUUSD", baseline_ts) if need_gold  else asyncio.sleep(0),
        get_close_at("DXY",    baseline_ts) if need_macro else asyncio.sleep(0),
        get_close_at("US10Y",  baseline_ts) if need_macro else asyncio.sleep(0),
        return_exceptions=True,
    )
    gold_base  = baselines[0] if need_gold  and not isinstance(baselines[0], Exception) else None
    dxy_base   = baselines[1] if need_macro and not isinstance(baselines[1], Exception) else None
    us10y_base = baselines[2] if need_macro and not isinstance(baselines[2], Exception) else None

    moves: dict[str, float | None] = {
        "gold_move_5m":   None,
        "gold_move_15m":  None,
        "gold_move_1h":   None,
        "gold_move_4h":   None,
        "dxy_move_1h":    None,
        "us10y_move_1h":  None,
    }

    # Gold windows — fetch concurrently
    windows = [(5, "gold_move_5m"), (15, "gold_move_15m"), (60, "gold_move_1h"), (240, "gold_move_4h")]
    due_windows = [
        (offset, key) for offset, key in windows
        if now >= event_at + timedelta(minutes=offset) + delay
    ]

    if due_windows and gold_base is not None:
        gold_prices = await asyncio.gather(
            *[get_close_at("XAUUSD", event_at + timedelta(minutes=offset)) for offset, _ in due_windows],
            return_exceptions=True,
        )
        for (offset, key), price in zip(due_windows, gold_prices):
            if not isinstance(price, Exception):
                moves[key] = _pct_change(gold_base, price)

    # DXY + US10Y at 1h
    if need_macro:
        target_1h = event_at + timedelta(minutes=60)
        dxy_1h, us10y_1h = await asyncio.gather(
            get_close_at("DXY",   target_1h),
            get_close_at("US10Y", target_1h),
            return_exceptions=True,
        )
        if not isinstance(dxy_1h, Exception):
            moves["dxy_move_1h"]   = _pct_change(dxy_base, dxy_1h)
        if not isinstance(us10y_1h, Exception):
            moves["us10y_move_1h"] = _pct_change(us10y_base, us10y_1h)

    return moves
