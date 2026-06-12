"""
FinnHub economic calendar provider.

Free tier: 60 calls/min — one call per refresh is well within limits.
Covers events FRED misses: FOMC, PPI, ECB, BOE, CAD, EUR, GBP releases.

API: GET /api/v1/calendar/economic?token=X&from=YYYY-MM-DD&to=YYYY-MM-DD
Times returned are UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_BASE = "https://finnhub.io/api/v1"

_ALLOWED_CURRENCIES = {"USD", "EUR", "GBP", "CAD"}

_CURRENCY_COUNTRY = {
    "USD": "United States",
    "EUR": "Eurozone",
    "GBP": "United Kingdom",
    "CAD": "Canada",
}

_CATEGORY_MAP = [
    (["cpi", "inflation", "pce", "ppi", "rpi", "hicp"],                              "inflation"),
    (["nfp", "payroll", "unemployment", "jobless", "employment", "labor", "labour"], "employment"),
    (["gdp", "growth"],                                                               "gdp"),
    (["rate", "fomc", "fed", "boe", "ecb", "boj", "rba", "rbnz", "snb", "interest", "decision", "minutes"], "rates"),
    (["retail", "trade balance", "import", "export", "current account"],             "trade"),
    (["housing", "home sales", "building permit", "construction permit", "permit"],  "housing"),
    (["pmi", "ism", "manufacturing", "services", "composite", "sentiment", "confidence"], "sentiment"),
]


def _infer_category(name: str) -> str:
    low = name.lower()
    for keywords, cat in _CATEGORY_MAP:
        if any(k in low for k in keywords):
            return cat
    return "general"


def _parse_val(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return None if f != f else f   # guard against NaN
    except (ValueError, TypeError):
        return None


class FinnHubCalendarProvider:
    """
    Fetches medium/high-impact economic events from FinnHub.
    Returns [] gracefully when API key is absent or request fails.
    """

    def __init__(self, api_key: str | None = None):
        self._key = api_key or settings.finnhub_api_key

    async def fetch_calendar(
        self,
        lookback_days: int = 7,
        lookahead_days: int = 14,
    ) -> list[dict]:
        if not self._key:
            logger.debug("[FinnHub] No API key configured — skipping")
            return []

        now       = datetime.now(UTC)
        from_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        to_date   = (now + timedelta(days=lookahead_days)).strftime("%Y-%m-%d")

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(
                    f"{_BASE}/calendar/economic",
                    params={"token": self._key, "from": from_date, "to": to_date},
                )
                r.raise_for_status()
                raw = r.json().get("economicCalendar", [])
        except Exception as exc:
            logger.warning("[FinnHub] fetch failed: %s", exc)
            return []

        events: list[dict] = []
        for item in raw:
            try:
                currency = (item.get("currency") or "").upper()
                if currency not in _ALLOWED_CURRENCIES:
                    continue

                impact     = (item.get("impact") or "low").lower()
                importance = impact if impact in ("high", "medium") else "low"
                if importance == "low":
                    continue

                time_str = item.get("time") or ""
                if not time_str:
                    continue
                # FinnHub returns UTC: "2026-06-18 18:00:00"
                try:
                    event_at = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                except ValueError:
                    continue

                name = (item.get("event") or "").strip()
                if not name:
                    continue

                actual   = _parse_val(item.get("actual"))
                forecast = _parse_val(item.get("estimate"))
                previous = _parse_val(item.get("prev"))
                unit     = item.get("unit") or None

                events.append({
                    "event_name":     name,
                    "source_id":      None,
                    "currency":       currency,
                    "country":        _CURRENCY_COUNTRY.get(currency, "Unknown"),
                    "category":       _infer_category(name),
                    "importance":     importance,
                    "event_at":       event_at,
                    "actual":         actual,
                    "forecast":       forecast,
                    "previous":       previous,
                    "unit":           unit,
                    "status":         "released" if actual is not None else "pending",
                    "is_high_impact": importance == "high",
                })
            except Exception:
                continue

        logger.info("[FinnHub] %d events (%s → %s)", len(events), from_date, to_date)
        return events
