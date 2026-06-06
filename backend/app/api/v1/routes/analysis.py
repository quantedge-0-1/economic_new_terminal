"""
POST /api/v1/analysis/event        — AI analysis for a specific event
POST /api/v1/analysis/news-flash   — Quick take on a news article
GET  /api/v1/analysis/history      — Recent analyses (cached)
GET  /api/v1/analysis/consolidated — Auto-detect + analyze simultaneous releases
POST /api/v1/analysis/consolidated — Manual consolidated analysis for explicit events
"""

from datetime import datetime, timezone
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.logger import get_logger
from app.db.session import get_db
from app.services.ai.engine import analyze_event, analyze_news_flash

logger = get_logger(__name__)
router = APIRouter()

_analysis_history: list[dict[str, Any]] = []


class EventAnalysisRequest(BaseModel):
    event_name: str
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    surprise_pct: float | None = None
    surprise_label: str | None = None
    currency: str = "USD"
    importance: str = "high"
    unit: str | None = None


class NewsFlashRequest(BaseModel):
    title: str
    source: str = ""
    summary: str = ""


@router.post("/event")
async def analyze_event_endpoint(req: EventAnalysisRequest):
    """
    Generate institutional Smart Money analysis for an economic release.
    Called when user clicks an event in the terminal.
    """
    cache_key = f"analysis:event:{req.event_name}:{req.actual}:{req.forecast}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    result = await analyze_event(req.model_dump())
    result["event_name"] = req.event_name
    result["analyzed_at"] = datetime.now(timezone.utc).isoformat()

    if result.get("tokens_used", 0) > 0:
        cache.set(cache_key, result, 600)

    # Keep last 20 analyses in memory for history
    _analysis_history.insert(0, result)
    if len(_analysis_history) > 20:
        _analysis_history.pop()

    return result


@router.post("/news-flash")
async def analyze_news_flash_endpoint(req: NewsFlashRequest):
    """Quick 3-line institutional take on a breaking news article."""
    analysis = await analyze_news_flash(req.model_dump())
    return {
        "analysis": analysis,
        "title": req.title,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/history")
async def get_analysis_history(limit: int = 10):
    """Last N AI analyses generated this session."""
    return {"analyses": _analysis_history[:limit], "count": len(_analysis_history)}


@router.get("/consolidated")
async def get_consolidated_analysis(
    minutes: int = Query(15, ge=5, le=60),
    db: AsyncSession = Depends(get_db),
):
    """
    Auto-fetch high-impact events released in the last N minutes, group by
    5-minute windows, and return consolidated institutional analysis when
    2+ events released simultaneously. Returns consolidated=False otherwise.
    """
    from datetime import UTC, timedelta
    from sqlalchemy import and_, or_, select

    from app.db.models import EconomicEvent
    from app.services.calendar.engine import _event_to_dict
    from app.services.consolidated_analysis_service import (
        analyze_consolidated,
        calculate_weighted_impacts,
        get_event_weight,
        group_simultaneous_events,
    )

    cache_key = f"analysis:consolidated_auto:{minutes}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    now   = datetime.now(UTC)
    since = now - timedelta(minutes=minutes)

    rows = (await db.execute(
        select(EconomicEvent)
        .where(and_(
            EconomicEvent.event_at  >= since,
            EconomicEvent.event_at  <= now,
            EconomicEvent.actual.isnot(None),
            or_(
                EconomicEvent.is_high_impact == True,
                EconomicEvent.importance     == "high",
            ),
        ))
        .order_by(EconomicEvent.event_at.desc())
        .limit(10)
    )).scalars().all()

    if not rows:
        result = {"consolidated": False, "events": [], "event_count": 0}
        cache.set(cache_key, result, 30)
        return result

    events = [_event_to_dict(r) for r in rows]
    groups = group_simultaneous_events(events, window_minutes=5)
    multi  = [g for g in groups if len(g) >= 2]

    if not multi:
        result = {"consolidated": False, "events": events, "event_count": len(events)}
        cache.set(cache_key, result, 30)
        return result

    # Largest simultaneous group
    group = max(multi, key=len)

    # Enrich with weight + inline surprise scores
    for ev in group:
        ev["weight"] = get_event_weight(ev["event_name"])
        actual   = ev.get("actual")
        forecast = ev.get("forecast")
        if actual is not None and forecast is not None and forecast != 0:
            sp = round((actual - forecast) / abs(forecast) * 100, 2)
        else:
            sp = None
        ev["surprise_pct"] = sp
        if sp is None:
            ev["surprise_label"] = "in_line"
        elif sp >= 10:
            ev["surprise_label"] = "large_beat"
        elif sp >= 3:
            ev["surprise_label"] = "beat"
        elif sp <= -10:
            ev["surprise_label"] = "large_miss"
        elif sp <= -3:
            ev["surprise_label"] = "miss"
        else:
            ev["surprise_label"] = "in_line"

    impacts  = calculate_weighted_impacts(group)
    analysis = await analyze_consolidated(group, impacts=impacts)

    result = {
        "consolidated":     True,
        "event_count":      len(group),
        "events":           group,
        "weighted_impacts": impacts,
        "analyzed_at":      datetime.now(UTC).isoformat(),
        **analysis,
    }
    cache.set(cache_key, result, 30)
    return result


@router.get("/briefing")
async def get_daily_briefing(
    force: bool = Query(False, description="Bypass cache and regenerate"),
    db: AsyncSession = Depends(get_db),
):
    """
    Daily macro briefing — 8-line narrative for all today's high-impact events.

    Returns: CONTEXTO / NARRATIVA / CLAVE / HORARIO / CADENA / TRADING / SESGO / ACCIÓN
    Cached for 10 minutes. Use ?force=true to regenerate immediately.
    """
    from datetime import UTC, timedelta
    from sqlalchemy import and_, or_, select

    from app.db.models import EconomicEvent
    from app.services.ai.briefing import generate_daily_briefing
    from app.services.calendar.engine import _event_to_dict
    from app.services.prices.engine import get_all_prices

    # Quick cache check (unless forced)
    latest_key = "analysis:briefing:latest"
    if not force:
        cached = cache.get(latest_key)
        if cached:
            return cached

    now         = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end   = today_start + timedelta(days=1)

    # Upcoming high-impact events today (pending)
    upcoming_rows = (await db.execute(
        select(EconomicEvent)
        .where(and_(
            EconomicEvent.event_at >= now,
            EconomicEvent.event_at <  today_end,
            EconomicEvent.status   == "pending",
            or_(
                EconomicEvent.is_high_impact == True,
                EconomicEvent.importance     == "high",
            ),
        ))
        .order_by(EconomicEvent.event_at)
        .limit(10)
    )).scalars().all()

    # Released in last 8 h (high-impact only)
    recent_rows = (await db.execute(
        select(EconomicEvent)
        .where(and_(
            EconomicEvent.event_at >= now - timedelta(hours=8),
            EconomicEvent.event_at <= now,
            EconomicEvent.actual.isnot(None),
            or_(
                EconomicEvent.is_high_impact == True,
                EconomicEvent.importance     == "high",
            ),
        ))
        .order_by(EconomicEvent.event_at.desc())
        .limit(5)
    )).scalars().all()

    upcoming = [_event_to_dict(r) for r in upcoming_rows]

    released: list[dict] = []
    for r in recent_rows:
        d = _event_to_dict(r)
        fc = d.get("forecast")
        ac = d.get("actual")
        if ac is not None and fc is not None and fc != 0:
            d["surprise_pct"] = round((ac - fc) / abs(fc) * 100, 1)
        released.append(d)

    # Current prices — get_all_prices returns {sym: {price, source, timestamp} | None}
    try:
        raw = await get_all_prices()
        current_prices = {}
        for sym in ("XAUUSD", "DXY", "US10Y"):
            entry = raw.get(sym)
            current_prices[sym] = entry.get("price") if isinstance(entry, dict) else None
    except Exception:
        current_prices = {}

    result = await generate_daily_briefing(upcoming, released, current_prices)

    # Store under "latest" key so repeated non-force calls are instant
    cache.set(latest_key, result, 600)
    return result


class ConsolidatedRequest(BaseModel):
    events: List[EventAnalysisRequest]


@router.post("/consolidated")
async def post_consolidated_analysis(req: ConsolidatedRequest):
    """
    Manual consolidated analysis — pass explicit list of simultaneous events.
    Useful for testing with arbitrary data (e.g. today's NFP batch).
    """
    from app.services.consolidated_analysis_service import (
        analyze_consolidated,
        calculate_weighted_impacts,
        get_event_weight,
    )

    enriched = []
    for ev in req.events:
        d = ev.model_dump()
        d["weight"] = get_event_weight(ev.event_name)
        if ev.actual is not None and ev.forecast is not None and ev.forecast != 0:
            d["surprise_pct"] = round((ev.actual - ev.forecast) / abs(ev.forecast) * 100, 2)
        enriched.append(d)

    impacts  = calculate_weighted_impacts(enriched)
    analysis = await analyze_consolidated(enriched)

    return {
        "consolidated":     True,
        "event_count":      len(enriched),
        "events":           enriched,
        "weighted_impacts": impacts,
        "analyzed_at":      datetime.now(timezone.utc).isoformat(),
        **analysis,
    }
