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


@router.get("/just-released")
async def get_just_released(
    minutes: int = Query(15, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
):
    """
    High-impact events released in the last N minutes with actual values.
    Short cache (30s) — used by frontend for auto-analysis triggering.
    """
    from datetime import UTC, datetime, timedelta
    from sqlalchemy import and_, or_, select
    from app.db.models import EconomicEvent

    cache_key = f"cal:just_released:{minutes}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    now   = datetime.now(UTC)
    since = now - timedelta(minutes=minutes)

    rows = (await db.execute(
        select(EconomicEvent)
        .where(
            and_(
                EconomicEvent.event_at  >= since,
                EconomicEvent.event_at  <= now,
                EconomicEvent.actual.isnot(None),
                or_(
                    EconomicEvent.is_high_impact == True,
                    EconomicEvent.importance     == "high",
                ),
            )
        )
        .order_by(EconomicEvent.event_at.desc())
        .limit(5)
    )).scalars().all()

    from app.services.calendar.engine import _event_to_dict
    events = [_event_to_dict(r) for r in rows]
    result = {"events": events, "count": len(events)}
    cache.set(cache_key, result, 30)  # 30s cache — needs to be fresh for auto-trigger
    return result


@router.post("/refresh")
async def trigger_refresh(
    lookahead_days: int = Query(14, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate calendar refresh from all providers."""
    cache.clear_prefix("cal:")
    result = await _engine.refresh(db, lookahead_days=lookahead_days)
    return result


@router.post("/mark-released")
async def mark_event_released(
    event_name: str = Query(..., description="Partial event name to match (case-insensitive)"),
    event_date: str = Query(..., description="Release date YYYY-MM-DD"),
    actual: float = Query(...),
    forecast: float | None = Query(None),
    previous: float | None = Query(None),
    unit: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin override: mark an event as released with real values.
    Use when all providers fail to capture the release automatically.
    Clears news and calendar caches so the Agenda sees updated data immediately.
    """
    from datetime import UTC, datetime
    from fastapi import HTTPException
    from sqlalchemy import and_
    from app.db.models import EconomicEvent

    y, m, d = (int(p) for p in event_date.split("-"))
    day_start = datetime(y, m, d, 0,  0,  0, tzinfo=UTC)
    day_end   = datetime(y, m, d, 23, 59, 59, tzinfo=UTC)

    rows = (await db.execute(
        select(EconomicEvent)
        .where(
            and_(
                EconomicEvent.event_name.ilike(f"%{event_name}%"),
                EconomicEvent.event_at >= day_start,
                EconomicEvent.event_at <= day_end,
            )
        )
    )).scalars().all()

    if not rows:
        raise HTTPException(404, f"No event matching '{event_name}' on {event_date}")

    for ev in rows:
        ev.actual  = actual
        ev.status  = "released"
        if forecast is not None:
            ev.forecast = forecast
        if previous is not None:
            ev.previous = previous
        if unit is not None:
            ev.unit = unit

    await db.commit()
    cache.clear_prefix("news:")
    cache.clear_prefix("cal:")

    return {
        "marked_released": len(rows),
        "events": [r.event_name for r in rows],
        "actual": actual,
    }
