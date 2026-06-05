"""
Real-time price engine — Twelve Data API as primary, yfinance as fallback.
Tracks: XAUUSD, DXY, US10Y yield proxy, SPX.
"""

import asyncio
from datetime import datetime, timezone

import httpx

from app.core import cache
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

TWELVE_BASE = "https://api.twelvedata.com"

# Twelve Data symbols — only symbols confirmed working on free tier
# DXY not available on Twelve Data; falls back to yfinance automatically
TWELVE_SYMBOLS = {
    "XAUUSD": "XAU/USD",
    "DXY":    None,     # not on Twelve Data → yfinance fallback
    "US10Y":  "TLT",   # 20-yr Treasury ETF proxy
    "SPX":    "SPY",   # S&P 500 ETF proxy
    "VIX":    "VXX",   # VIX ETF proxy
}

# yfinance fallback symbols
YF_SYMBOLS = {
    "XAUUSD": "GC=F",
    "DXY":    "DX-Y.NYB",
    "US10Y":  "^TNX",
    "SPX":    "^GSPC",
    "VIX":    "^VIX",
}


async def _fetch_twelve(symbol: str, td_symbol: str) -> dict | None:
    if not settings.twelve_data_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{TWELVE_BASE}/price",
                params={"symbol": td_symbol, "apikey": settings.twelve_data_api_key},
            )
            data = resp.json()
            if "price" in data:
                return {
                    "symbol": symbol,
                    "price": round(float(data["price"]), 4),
                    "source": "twelve_data",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
    except Exception as exc:
        logger.warning("Twelve Data fetch failed for %s: %s", symbol, exc)
    return None


async def _fetch_yfinance(symbol: str, yf_symbol: str) -> dict | None:
    try:
        loop = asyncio.get_running_loop()

        def _sync_fetch():
            import yfinance as yf
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            return None

        price = await loop.run_in_executor(None, _sync_fetch)
        if price is not None:
            return {
                "symbol": symbol,
                "price": round(price, 4),
                "source": "yfinance",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as exc:
        logger.warning("yfinance fetch failed for %s: %s", symbol, exc)
    return None


async def get_price(symbol: str) -> dict | None:
    cache_key = f"price:{symbol}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    td_symbol = TWELVE_SYMBOLS.get(symbol)
    yf_symbol = YF_SYMBOLS.get(symbol)

    result = None
    if td_symbol:
        result = await _fetch_twelve(symbol, td_symbol)
    if result is None and yf_symbol:
        result = await _fetch_yfinance(symbol, yf_symbol)

    if result:
        cache.set(cache_key, result, settings.prices_cache_ttl)
    return result


async def get_all_prices() -> dict:
    tasks = [get_price(sym) for sym in TWELVE_SYMBOLS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    prices = {}
    for sym, res in zip(TWELVE_SYMBOLS.keys(), results):
        if isinstance(res, dict):
            prices[sym] = res
        else:
            prices[sym] = None
    return prices
