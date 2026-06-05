"""
GET /api/v1/prices/live        — current prices for all tracked assets
GET /api/v1/prices/{symbol}    — price for a single asset
"""

from fastapi import APIRouter, HTTPException

from app.core.logger import get_logger
from app.services.prices.engine import get_all_prices, get_price
from app.services.prices.history import record_prices

logger = get_logger(__name__)
router = APIRouter()

VALID_SYMBOLS = {"XAUUSD", "DXY", "US10Y", "SPX", "VIX"}


@router.get("/live")
async def get_live_prices():
    """Current prices for XAUUSD, DXY, US10Y, SPX, VIX."""
    prices = await get_all_prices()
    # Record snapshot for MCS multi-timeframe analysis
    record_prices(prices)
    return {
        "prices": prices,
        "symbols": list(VALID_SYMBOLS),
    }


@router.get("/{symbol}")
async def get_single_price(symbol: str):
    symbol = symbol.upper()
    if symbol not in VALID_SYMBOLS:
        raise HTTPException(
            status_code=404,
            detail=f"Symbol '{symbol}' not tracked. Valid: {sorted(VALID_SYMBOLS)}",
        )
    result = await get_price(symbol)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail=f"Price unavailable for {symbol}. Check API key configuration.",
        )
    return result
