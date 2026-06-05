"""
GET  /api/v1/surprise/recent           — recent surprise events
GET  /api/v1/surprise/history/{name}   — history for specific event
POST /api/v1/surprise/compute          — compute surprise + divergence inline
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import settings
from app.core.logger import get_logger
from app.db.session import get_db
from app.services.divergence.engine import detect_divergence
from app.services.surprise.engine import SurpriseEngine

logger = get_logger(__name__)
router = APIRouter()

_engine = SurpriseEngine()


class ComputeSurpriseRequest(BaseModel):
    event_name: str
    actual: float
    forecast: float
    previous: float | None = None
    currency: str = "USD"
    importance: str = "high"
    unit: str | None = None
    # Optional price changes for divergence detection
    price_changes: dict[str, float] | None = None  # {"XAUUSD": +0.3, "USD": -0.1}


@router.get("/recent")
async def get_recent_surprises(
    limit: int = Query(20, ge=1, le=100),
    currency: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    cache_key = f"surprise:recent:{limit}:{currency}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    surprises = await _engine.get_recent(db, limit=limit, currency=currency)
    result = {"surprises": surprises, "count": len(surprises)}
    cache.set(cache_key, result, settings.surprise_cache_ttl)
    return result


@router.get("/history/{event_name}")
async def get_event_history(
    event_name: str,
    limit: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    history = await _engine.get_history(db, event_name=event_name, limit=limit)
    stats = await _engine.get_summary_stats(db, event_name=event_name)
    return {"event_name": event_name, "history": history, "stats": stats}


@router.post("/compute")
async def compute_surprise(req: ComputeSurpriseRequest):
    """
    Inline surprise computation — no DB required.
    Optionally computes divergence if price_changes provided.
    """
    if req.forecast == 0:
        surprise_pct = 0.0
    else:
        surprise_pct = ((req.actual - req.forecast) / abs(req.forecast)) * 100

    raw = req.actual - req.forecast

    # Label
    if surprise_pct >= 10:
        label = "large_beat"
    elif surprise_pct >= 3:
        label = "beat"
    elif surprise_pct <= -10:
        label = "large_miss"
    elif surprise_pct <= -3:
        label = "miss"
    else:
        label = "in_line"

    # Asset impact scores (-100 to +100)
    impact_multiplier = min(abs(surprise_pct) / 10, 1.0)
    surprise_sign = 1 if surprise_pct > 0 else -1

    asset_impacts = {
        "USD":  round(surprise_sign * impact_multiplier * 100, 1),
        "XAUUSD": round(-surprise_sign * impact_multiplier * 80, 1),
        "Bonds": round(-surprise_sign * impact_multiplier * 70, 1),
        "Risk": round(surprise_sign * impact_multiplier * 60, 1),
    }

    result = {
        "event_name": req.event_name,
        "actual": req.actual,
        "forecast": req.forecast,
        "previous": req.previous,
        "raw_surprise": round(raw, 4),
        "surprise_pct": round(surprise_pct, 2),
        "surprise_label": label,
        "asset_impacts": asset_impacts,
        "currency": req.currency,
    }

    if req.price_changes:
        result["divergence"] = detect_divergence(
            req.event_name, surprise_pct, req.price_changes
        )

    return result
