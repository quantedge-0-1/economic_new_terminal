"""
GET /api/v1/market/session-bias  — USD/XAU/session bias from recent event data
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.logger import get_logger
from app.db.models import EconomicEvent, EventSurprise
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


def _current_session() -> str:
    h = datetime.now(UTC).hour
    if 8  <= h < 13: return "LONDON"
    if 13 <= h < 18: return "NEW_YORK"
    if h >= 23 or h < 2: return "TOKYO"
    return "OFF"


def _bias_label(score: float) -> str:
    if score >= 15:  return "ALCISTA"
    if score <= -15: return "BAJISTA"
    return "NEUTRAL"


@router.get("/session-bias")
async def get_session_bias(db: AsyncSession = Depends(get_db)):
    """
    Rule-based USD/XAU bias from last 24h of high-impact USD releases.
    Positive surprise → USD ALCISTA / XAU BAJISTA (no AI call).
    Cached 5 minutes.
    """
    cache_key = "market:session_bias"
    cached = cache.get(cache_key)
    if cached:
        return cached

    now   = datetime.now(UTC)
    since = now - timedelta(hours=24)

    # Prefer EventSurprise rows (pre-computed) — fall back to raw EconomicEvent
    surprise_rows = (await db.execute(
        select(EventSurprise)
        .where(
            and_(
                EventSurprise.event_at  >= since,
                EventSurprise.event_at  <= now,
                EventSurprise.currency  == "USD",
            )
        )
        .order_by(EventSurprise.event_at.desc())
        .limit(5)
    )).scalars().all()

    if surprise_rows:
        weighted_score = 0.0
        total_weight   = 0.0
        for i, row in enumerate(surprise_rows):
            if row.surprise_pct is None:
                continue
            w = 1.0 / (i + 1)
            weighted_score += row.surprise_pct * 100 * w
            total_weight   += w
        score = (weighted_score / total_weight) if total_weight > 0 else 0.0
    else:
        # Fallback: compute from raw events
        event_rows = (await db.execute(
            select(EconomicEvent)
            .where(
                and_(
                    EconomicEvent.event_at  >= since,
                    EconomicEvent.event_at  <= now,
                    EconomicEvent.actual.isnot(None),
                    EconomicEvent.currency  == "USD",
                    or_(
                        EconomicEvent.is_high_impact == True,
                        EconomicEvent.importance     == "high",
                    ),
                )
            )
            .order_by(EconomicEvent.event_at.desc())
            .limit(5)
        )).scalars().all()

        weighted_score = 0.0
        total_weight   = 0.0
        for i, ev in enumerate(event_rows):
            if ev.actual is None or ev.forecast is None or ev.forecast == 0:
                continue
            sp = (ev.actual - ev.forecast) / abs(ev.forecast) * 100
            w  = 1.0 / (i + 1)
            weighted_score += sp * w
            total_weight   += w
        score = (weighted_score / total_weight) if total_weight > 0 else 0.0

    usd_bias = _bias_label(score)
    xau_bias = (
        "BAJISTA" if usd_bias == "ALCISTA" else
        "ALCISTA" if usd_bias == "BAJISTA" else
        "NEUTRAL"
    )
    session     = _current_session()
    session_bias = xau_bias if session in ("LONDON", "NEW_YORK") else "NEUTRAL"

    result = {
        "usd_bias":     usd_bias,
        "xau_bias":     xau_bias,
        "session_bias": session_bias,
        "session":      session,
        "score":        round(score, 2),
        "events_used":  len(surprise_rows),
        "calculated_at": now.isoformat(),
    }
    cache.set(cache_key, result, 300)
    return result
