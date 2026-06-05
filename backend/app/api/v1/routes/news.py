"""
GET  /api/v1/news/latest    — latest news articles
POST /api/v1/news/refresh   — trigger RSS + GDELT refresh
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import settings
from app.core.logger import get_logger
from app.db.session import get_db
from app.services.news.engine import NewsEngine

logger = get_logger(__name__)
router = APIRouter()

_engine = NewsEngine()


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
