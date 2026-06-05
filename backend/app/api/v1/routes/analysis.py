"""
POST /api/v1/analysis/event        — AI analysis for a specific event
POST /api/v1/analysis/news-flash   — Quick take on a news article
GET  /api/v1/analysis/history      — Recent analyses (cached)
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import cache
from app.core.logger import get_logger
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

    # Cache for 10 min (same event won't change)
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
