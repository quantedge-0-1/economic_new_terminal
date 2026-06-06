"""
GET  /api/v1/news/live      — most recent high-impact USD release (for PWA companion)
GET  /api/v1/news/latest    — latest news articles
POST /api/v1/news/refresh   — trigger RSS + GDELT refresh
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import settings
from app.core.logger import get_logger
from app.db.models import EconomicEvent
from app.db.session import get_db
from app.services.news.engine import NewsEngine

logger = get_logger(__name__)
router = APIRouter()

_engine = NewsEngine()

# ── Rule-based market impact by event category ────────────────────────────────
# Multipliers applied to the surprise_pct (capped ±100) to produce
# directional scores for USD, Gold, Bonds, and Risk sentiment.
_IMPACT_MULT: dict[str, dict[str, float]] = {
    "employment": {"usd":  1.0, "gold": -0.8, "bond": -0.7, "risk":  0.6},
    "inflation":  {"usd":  0.8, "gold":  0.3, "bond": -0.9, "risk": -0.5},
    "gdp":        {"usd":  0.9, "gold": -0.6, "bond": -0.7, "risk":  0.7},
    "rates":      {"usd":  0.7, "gold": -0.9, "bond": -0.8, "risk": -0.6},
    "trade":      {"usd":  0.5, "gold": -0.3, "bond": -0.2, "risk":  0.4},
    "housing":    {"usd":  0.4, "gold": -0.3, "bond": -0.3, "risk":  0.5},
    "sentiment":  {"usd":  0.3, "gold":  0.2, "bond":  0.1, "risk":  0.5},
}
_DEFAULT_MULT = {"usd": 0.5, "gold": -0.3, "bond": -0.3, "risk": 0.3}


def _compute_impact(surprise_pct: float | None, category: str | None) -> dict:
    """
    Compute rule-based impact scores (-100 to +100) from surprise_pct and category.
    NFP employment +102% surprise → USD +100, Gold -80, Bond -70, Risk +60.
    """
    if surprise_pct is None:
        return {
            "usd_impact_score": None, "gold_impact_score": None,
            "bond_impact_score": None, "risk_sentiment_score": None,
        }
    base = max(-100.0, min(100.0, float(surprise_pct)))
    m = _IMPACT_MULT.get(category or "", _DEFAULT_MULT)
    return {
        "usd_impact_score":     round(base * m["usd"]),
        "gold_impact_score":    round(base * m["gold"]),
        "bond_impact_score":    round(base * m["bond"]),
        "risk_sentiment_score": round(base * m["risk"]),
    }


@router.get("/live")
async def get_live_release(db: AsyncSession = Depends(get_db)):
    """
    Returns the most recent released high-impact event (last 48 hours).
    Designed for 60-second polling by the PWA mobile companion.
    Returns {events: [...]} with impact scores — empty list when nothing released.
    """
    cache_key = "news:live"
    cached = cache.get(cache_key)
    if cached:
        return cached

    now   = datetime.now(UTC)
    since = now - timedelta(hours=48)

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
        .limit(3)
    )).scalars().all()

    events = []
    for ev in rows:
        surprise_pct = None
        surprise_label = "in_line"
        if ev.actual is not None and ev.forecast is not None and ev.forecast != 0:
            surprise_pct = round((ev.actual - ev.forecast) / abs(ev.forecast) * 100, 1)
            if surprise_pct >= 10:    surprise_label = "large_beat"
            elif surprise_pct >= 3:   surprise_label = "beat"
            elif surprise_pct <= -10: surprise_label = "large_miss"
            elif surprise_pct <= -3:  surprise_label = "miss"

        impact = _compute_impact(surprise_pct, ev.category)

        events.append({
            "id":            ev.id,
            "event_name":    ev.event_name,
            "currency":      ev.currency,
            "category":      ev.category,
            "importance":    ev.importance,
            "is_high_impact": bool(ev.is_high_impact or ev.importance == "high"),
            "event_at":      ev.event_at.isoformat() if ev.event_at else None,
            "actual":        ev.actual,
            "forecast":      ev.forecast,
            "previous":      ev.previous,
            "unit":          ev.unit,
            "surprise_pct":  surprise_pct,
            "surprise_label": surprise_label,
            **impact,
        })

    result = {"events": events, "count": len(events), "as_of": now.isoformat()}
    cache.set(cache_key, result, 60)
    return result


@router.get("/latest")
async def get_latest_news(
    limit: int = Query(30, ge=1, le=100),
    category: str | None = Query(None),
    min_relevance: float = Query(0.3, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    cache_key = f"news:latest:{limit}:{category}:{min_relevance}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    articles = await _engine.get_latest(
        db, limit=limit, category=category, min_relevance=min_relevance
    )
    result = {"articles": articles, "count": len(articles)}
    cache.set(cache_key, result, settings.news_cache_ttl)
    return result


@router.post("/refresh")
async def refresh_news(db: AsyncSession = Depends(get_db)):
    cache.clear_prefix("news:")
    result = await _engine.refresh(db)
    return result
