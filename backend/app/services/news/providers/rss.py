"""
RSS news provider — fetches and parses multiple economic/financial RSS feeds.

Feeds (all free, no API key):
  Reuters Business    https://feeds.reuters.com/reuters/businessNews
  Reuters Markets     https://feeds.reuters.com/reuters/UKMarkets (or similar)
  MarketWatch         https://feeds.marketwatch.com/marketwatch/marketpulse/
  FT Economy          https://www.ft.com/rss/home/uk  (limited)
  WSJ Economy         https://feeds.content.dowjones.io/public/rss/mw_topstories
  Investing.com       https://www.investing.com/rss/news_25.rss  (general news)
  Bloomberg (limited) https://feeds.bloomberg.com/markets/news.rss
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from defusedxml import ElementTree as ET

from app.core.logger import get_logger

logger = get_logger(__name__)

_FEEDS = [
    ("reuters_business",  "https://feeds.reuters.com/reuters/businessNews"),
    ("reuters_markets",   "https://feeds.reuters.com/reuters/UKmarkets"),
    ("marketwatch",       "https://feeds.marketwatch.com/marketwatch/marketpulse/"),
    ("investing_general", "https://www.investing.com/rss/news_301.rss"),
    ("ft_markets",        "https://www.ft.com/rss/home/uk"),
]

# Keywords that indicate gold/macro relevance
_RELEVANCE_KEYWORDS = [
    "gold", "xau", "fed", "fomc", "powell", "inflation", "cpi", "pce",
    "nfp", "payroll", "rate hike", "rate cut", "yield", "dollar", "dxy",
    "treasury", "bond", "recession", "gdp", "employment", "jobs",
    "central bank", "monetary policy", "ecb", "boe", "boj",
    "commodity", "precious metal", "silver", "oil",
    "geopolitical", "sanctions", "ukraine", "middle east",
]

# Sentiment keywords (positive → bullish gold)
_BULLISH_KEYWORDS = ["gold rises", "gold gains", "gold surges", "safe haven",
                     "rate cut", "dovish", "inflation high", "war", "conflict",
                     "recession", "risk off", "flight to safety"]
_BEARISH_KEYWORDS = ["gold falls", "gold drops", "gold slides", "rate hike",
                     "hawkish", "strong dollar", "risk on", "rally stocks",
                     "tightening", "economic growth"]


def _relevance(title: str, summary: str) -> float:
    text = (title + " " + (summary or "")).lower()
    hits = sum(1 for kw in _RELEVANCE_KEYWORDS if kw in text)
    return min(1.0, round(hits / 4, 2))   # saturate at 4 hits = 1.0


def _sentiment(title: str, summary: str) -> tuple[float, str]:
    text = (title + " " + (summary or "")).lower()
    bull = sum(1 for kw in _BULLISH_KEYWORDS if kw in text)
    bear = sum(1 for kw in _BEARISH_KEYWORDS if kw in text)
    score = (bull - bear) / max(bull + bear, 1) if (bull + bear) > 0 else 0.0
    label = "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"
    return round(score, 3), label


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str).astimezone(UTC).replace(tzinfo=UTC)
    except Exception:
        return None


def _infer_category(title: str) -> str:
    low = title.lower()
    if any(k in low for k in ["fed", "fomc", "central bank", "rate decision", "ecb", "boe"]):
        return "central_bank"
    if any(k in low for k in ["inflation", "cpi", "pce", "ppi"]):
        return "inflation"
    if any(k in low for k in ["payroll", "employment", "unemployment", "jobs"]):
        return "employment"
    if any(k in low for k in ["geopolit", "war", "sanctions", "military", "conflict"]):
        return "geopolitical"
    if any(k in low for k in ["gold", "silver", "oil", "commodity"]):
        return "commodity"
    return "general"


class RSSProvider:

    async def fetch_all(self, max_per_feed: int = 20) -> list[dict]:
        articles: list[dict] = []
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for source, url in _FEEDS:
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                    parsed = self._parse_feed(r.text, source, max_per_feed)
                    articles.extend(parsed)
                except Exception as exc:
                    logger.warning(f"[RSS] {source} failed: {exc}")
        return articles

    def _parse_feed(self, xml_text: str, source: str, limit: int) -> list[dict]:
        results: list[dict] = []
        try:
            root = ET.fromstring(xml_text)
            # Handle both RSS and Atom
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)

            for item in items[:limit]:
                title   = (item.findtext("title") or "").strip()
                link    = item.findtext("link") or item.findtext("atom:link", namespaces=ns) or ""
                summary = (item.findtext("description") or item.findtext("atom:summary", namespaces=ns) or "").strip()
                pub_str = item.findtext("pubDate") or item.findtext("atom:published", namespaces=ns)

                summary = re.sub(r"<[^>]+>", "", summary)[:500]
                if not title:
                    continue

                rel   = _relevance(title, summary)
                sent, sent_label = _sentiment(title, summary)

                results.append({
                    "source":          source,
                    "source_url":      link[:500] if link else None,
                    "title":           title[:400],
                    "summary":         summary or None,
                    "published_at":    _parse_date(pub_str),
                    "category":        _infer_category(title),
                    "relevance_score": rel,
                    "sentiment_score": sent,
                    "sentiment_label": sent_label,
                    "is_alert":        rel >= 0.5 and abs(sent) >= 0.4,
                    "alert_level":     "high" if rel >= 0.75 else "medium" if rel >= 0.5 else None,
                })
        except Exception as exc:
            logger.warning(f"[RSS] parse error ({source}): {exc}")
        return results
