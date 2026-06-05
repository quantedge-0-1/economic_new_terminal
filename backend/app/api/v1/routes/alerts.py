"""
GET   /api/v1/alerts/          — all active alerts
PATCH /api/v1/alerts/{id}/read — mark alert as read
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import settings
from app.core.logger import get_logger
from app.db.session import get_db
from app.services.alerts.engine import AlertEngine

logger = get_logger(__name__)
router = APIRouter()

_engine = AlertEngine()


@router.get("/")
async def get_alerts(
    limit: int = Query(50, ge=1, le=200),
    level: str | None = Query(None, pattern="^(critical|high|medium|low)$"),
    unread_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    cache_key = f"alerts:{limit}:{level}:{unread_only}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    alerts = await _engine.get_alerts(db, limit=limit, level=level, unread_only=unread_only)
    result = {"alerts": alerts, "count": len(alerts)}
    cache.set(cache_key, result, settings.alerts_cache_ttl)
    return result


@router.patch("/{alert_id}/read")
async def mark_alert_read(alert_id: int, db: AsyncSession = Depends(get_db)):
    cache.clear_prefix("alerts:")
    await _engine.mark_read(db, alert_id=alert_id)
    return {"status": "ok", "alert_id": alert_id}
