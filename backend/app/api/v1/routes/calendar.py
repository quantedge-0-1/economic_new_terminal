"""
GET  /api/v1/calendar/upcoming     — next N hours of events
GET  /api/v1/calendar/recent       — recently released events
GET  /api/v1/calendar/high-impact  — events in ±N hour window
POST /api/v1/calendar/refresh      — trigger manual refresh
"""

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import settings
from app.core.logger import get_logger
from app.db.session import get_db
from app.services.calendar.engine import CalendarEngine

logger = get_logger(__name__)
router = APIRouter()

_engine = CalendarEngine()


@router.get("/upcoming")
async def get_upcoming(
    hours: int = Query(48, ge=1, le=168),
    currency: str | None = Query(None),
    currencies: str | None = Query(None, description="Comma-separated list, e.g. EUR,USD,GBP"),
    importance: str | None = Query(None, pattern="^(high|medium|low)$"),
    db: AsyncSession = Depends(get_db),
):
    currency_list = [c.strip() for c in currencies.split(",")] if currencies else None
    cache_key = f"cal:upcoming:{hours}:{currencies or currency}:{importance}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    events = await _engine.get_upcoming(
        db, hours=hours, currency=currency, currencies=currency_list, importance=importance
    )
    result = {"events": events, "count": len(events), "hours_lookahead": hours}
    cache.set(cache_key, result, settings.calendar_cache_ttl)
    return result


@router.get("/recent")
async def get_recent(
    hours: int = Query(72, ge=1, le=720),
    currency: str | None = Query(None),
    currencies: str | None = Query(None, description="Comma-separated list, e.g. EUR,USD,GBP"),
    db: AsyncSession = Depends(get_db),
):
    currency_list = [c.strip() for c in currencies.split(",")] if currencies else None
    cache_key = f"cal:recent:{hours}:{currencies or currency}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    events = await _engine.get_recent_releases(db, hours=hours, currency=currency, currencies=currency_list)
    result = {"events": events, "count": len(events)}
    cache.set(cache_key, result, settings.calendar_cache_ttl)
    return result


@router.get("/high-impact")
async def get_high_impact_window(
    hours_before: int = Query(2, ge=0, le=24),
    hours_after: int = Query(2, ge=0, le=24),
    db: AsyncSession = Depends(get_db),
):
    events = await _engine.get_high_impact_window(
        db, hours_before=hours_before, hours_after=hours_after
    )
    return {
        "events": events,
        "count": len(events),
        "in_event_risk": len(events) > 0,
    }


@router.post("/refresh")
async def trigger_refresh(
    lookahead_days: int = Query(14, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate calendar refresh from all providers."""
    cache.clear_prefix("cal:")
    result = await _engine.refresh(db, lookahead_days=lookahead_days)
    return result
