"""
GDELT provider — queries GDELT 2.0 API for gold/macro-relevant news.

Endpoint: https://api.gdeltproject.org/api/v2/doc/doc
Free, no API key, up to 250 articles per query.

Query: gold OR "central bank" OR "inflation" OR "federal reserve" recent articles.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.core.logger import get_logger

logger = get_logger(__name__)

_GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

_QUERIES = [
    "gold price inflation federal reserve",
    "gold market central bank rate decision",
]


class GDELTProvider:

    async def fetch_articles(self, max_records: int = 50) -> list[dict]:
        articles: list[dict] = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            for query in _QUERIES:
                try:
                    results = await self._query(client, query, max_records // len(_QUERIES))
                    articles.extend(results)
                except Exception as exc:
                    logger.warning(f"[GDELT] query '{query[:40]}' failed: {exc}")
        # Deduplicate by URL
        seen: set[str] = set()
        unique: list[dict] = []
        for a in articles:
            url = a.get("source_url", "")
            if url and url not in seen:
                seen.add(url)
                unique.append(a)
        return unique

    async def _query(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
    ) -> list[dict]:
        r = await client.get(
            _GDELT_DOC_API,
            params={
                "query":     query,
                "mode":      "ArtList",
                "maxrecords": min(limit, 250),
                "format":    "json",
                "timespan":  "1d",   # last 24h
            },
        )
        r.raise_for_status()
        data = r.json()
        arts = data.get("articles", [])

        results: list[dict] = []
        for art in arts:
            title    = (art.get("title") or "").strip()[:400]
            url      = (art.get("url") or "")[:500]
            domain   = art.get("domain", "unknown")
            seendate = art.get("seendate", "")

            if not title or not url:
                continue

            pub_at: datetime | None = None
            try:
                pub_at = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            except Exception:
                pass

            results.append({
                "source":          f"gdelt_{domain[:20]}",
                "source_url":      url,
                "title":           title,
                "summary":         None,
                "published_at":    pub_at,
                "category":        "general",
                "relevance_score": 0.4,    # GDELT already filtered by query
                "sentiment_score": 0.0,
                "sentiment_label": "neutral",
                "is_alert":        False,
                "alert_level":     None,
            })
        return results
