"""
NewsEngine — aggregates RSS + GDELT, persists articles, generates alerts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.db.models import Alert, NewsArticle
from app.services.news.providers.gdelt import GDELTProvider
from app.services.news.providers.rss import RSSProvider

logger = get_logger(__name__)


class NewsEngine:

    def __init__(self):
        self._rss   = RSSProvider()
        self._gdelt = GDELTProvider()

    async def refresh(self, db: AsyncSession) -> dict:
        """Fetch all sources, upsert articles, generate alerts."""
        rss_arts   = await self._rss.fetch_all()
        gdelt_arts = await self._gdelt.fetch_articles()

        all_arts = rss_arts + gdelt_arts
        inserted = alerts = 0

        for art in all_arts:
            new_article = await self._upsert_article(db, art)
            if new_article:
                inserted += 1
                if art.get("is_alert") and art.get("relevance_score", 0) >= 0.5:
                    await self._create_alert(db, new_article)
                    alerts += 1

        await db.commit()
        logger.info(f"[news] refresh: {inserted} new articles, {alerts} alerts")
        return {"inserted": inserted, "alerts": alerts, "total": len(all_arts)}

    async def _upsert_article(
        self,
        db: AsyncSession,
        art: dict,
    ) -> NewsArticle | None:
        url = art.get("source_url")
        if not url:
            return None

        existing = (await db.execute(
            select(NewsArticle).where(NewsArticle.source_url == url)
        )).scalar_one_or_none()
        if existing:
            return None

        article = NewsArticle(
            source          = art["source"],
            source_url      = url,
            title           = art["title"],
            summary         = art.get("summary"),
            published_at    = art.get("published_at"),
            category        = art.get("category"),
            relevance_score = art.get("relevance_score"),
            sentiment_score = art.get("sentiment_score"),
            sentiment_label = art.get("sentiment_label"),
            is_alert        = art.get("is_alert", False),
            alert_level     = art.get("alert_level"),
        )
        db.add(article)
        await db.flush()
        return article

    async def _create_alert(self, db: AsyncSession, article: NewsArticle) -> None:
        level = article.alert_level or "medium"
        alert = Alert(
            alert_type  = "news_flash",
            level       = level,
            title       = article.title[:200],
            body        = article.summary,
            article_id  = article.id,
            expires_at  = datetime.now(UTC) + timedelta(hours=6),
        )
        db.add(alert)

    async def get_latest(
        self,
        db: AsyncSession,
        *,
        limit: int = 30,
        category: str | None = None,
        min_relevance: float = 0.0,
    ) -> list[dict]:
        q = (
            select(NewsArticle)
            .where(NewsArticle.relevance_score >= min_relevance)
            .order_by(NewsArticle.fetched_at.desc())
            .limit(limit)
        )
        if category:
            q = q.where(NewsArticle.category == category)
        rows = (await db.execute(q)).scalars().all()
        return [_article_to_dict(r) for r in rows]

    async def get_alerts(
        self,
        db: AsyncSession,
        *,
        unread_only: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        q = (
            select(Alert)
            .order_by(Alert.triggered_at.desc())
            .limit(limit)
        )
        if unread_only:
            q = q.where(Alert.is_read == False)
        rows = (await db.execute(q)).scalars().all()
        return [_alert_to_dict(r) for r in rows]

    async def mark_alert_read(self, db: AsyncSession, alert_id: int) -> bool:
        row = (await db.execute(
            select(Alert).where(Alert.id == alert_id)
        )).scalar_one_or_none()
        if row:
            row.is_read = True
            await db.commit()
            return True
        return False


def _article_to_dict(a: NewsArticle) -> dict:
    return {
        "id":             a.id,
        "source":         a.source,
        "source_url":     a.source_url,
        "title":          a.title,
        "summary":        a.summary,
        "published_at":   a.published_at.strftime("%Y-%m-%dT%H:%M:%SZ") if a.published_at else None,
        "fetched_at":     a.fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "category":       a.category,
        "relevance_score": a.relevance_score,
        "sentiment_score": a.sentiment_score,
        "sentiment_label": a.sentiment_label,
        "is_alert":       a.is_alert,
        "alert_level":    a.alert_level,
    }


def _alert_to_dict(a: Alert) -> dict:
    return {
        "id":           a.id,
        "alert_type":   a.alert_type,
        "level":        a.level,
        "title":        a.title,
        "body":         a.body,
        "currency":     a.currency,
        "triggered_at": a.triggered_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_read":      a.is_read,
        "expires_at":   a.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ") if a.expires_at else None,
        "event_id":     a.event_id,
        "article_id":   a.article_id,
    }
