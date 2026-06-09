"""
CalendarEngine — aggregates FRED + Investing.com scraper into the DB.

Responsibilities:
  - Upsert events (unique on event_name + event_at)
  - Merge forecasts from scraper with actuals from FRED
  - Detect newly released events (actual became non-null)
  - Return structured event lists for API consumption
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.db.models import EconomicEvent
from app.services.calendar.providers.fred import FREDProvider, _NAME_TO_SERIES
from app.services.calendar.providers.forexfactory_scraper import ForexFactoryCalendarScraper

logger = get_logger(__name__)


class CalendarEngine:

    def __init__(self):
        self._fred     = FREDProvider()
        self._scraper  = ForexFactoryCalendarScraper()

    # ── Refresh pipeline ───────────────────────────────────────────────────────

    async def refresh(self, db: AsyncSession, *, lookahead_days: int = 14) -> dict:
        """
        Fetch from all providers, merge, and upsert into economic_events.
        Returns a summary of inserted/updated rows.
        """
        fred_events    = await self._fred.fetch_releases(lookback_days=60, lookahead_days=lookahead_days)
        scraper_events = await self._scraper.fetch_calendar(lookahead_days=lookahead_days)

        merged = _merge_providers(fred_events, scraper_events)

        # Deduplicate by (event_name, event_at) — last one wins within this batch
        deduped: dict[tuple, dict] = {}
        for ev in merged:
            key = (ev["event_name"], ev["event_at"])
            deduped[key] = ev
        unique_events = list(deduped.values())

        inserted = updated = skipped = 0
        for ev in unique_events:
            try:
                result = await self._upsert_event(db, ev)
                if result == "inserted":
                    inserted += 1
                elif result == "updated":
                    updated += 1
                # Flush after each insert so next SELECT sees it
                await db.flush()
            except Exception as exc:
                logger.warning("[calendar] skipping event %s: %s", ev.get("event_name"), exc)
                await db.rollback()
                skipped += 1

        await db.commit()

        # After the normal merge/upsert, scan for past high-impact events still pending
        # and try to fill their actuals directly from FRED (bypasses scraper/timing failures)
        filled = await self._scan_and_fill_actuals(db)

        logger.info(
            "[calendar] refresh: %d inserted, %d updated, %d skipped, %d filled from %d events",
            inserted, updated, skipped, filled, len(unique_events),
        )
        return {
            "inserted": inserted, "updated": updated,
            "skipped": skipped, "total": len(unique_events), "filled": filled,
        }

    async def _upsert_event(self, db: AsyncSession, ev: dict) -> str:
        existing = (await db.execute(
            select(EconomicEvent)
            .where(EconomicEvent.event_name == ev["event_name"])
            .where(EconomicEvent.event_at   == ev["event_at"])
        )).scalar_one_or_none()

        if existing is None:
            db.add(EconomicEvent(**ev))
            return "inserted"

        # Update mutable fields if changed
        changed = False
        for field in ("actual", "forecast", "previous", "revised", "status"):
            new_val = ev.get(field)
            if new_val is not None and getattr(existing, field) != new_val:
                setattr(existing, field, new_val)
                changed = True
        return "updated" if changed else "noop"

    async def _scan_and_fill_actuals(self, db: AsyncSession) -> int:
        """
        For high-impact events that are past-due (pending + event_at < now + actual=None),
        attempt a direct FRED observation fetch. This catches events the normal pipeline
        missed due to rate limiting, scraper blocking, or timing issues.
        """
        now = datetime.now(UTC)

        rows = (await db.execute(
            select(EconomicEvent)
            .where(
                and_(
                    EconomicEvent.event_at < now,
                    EconomicEvent.actual.is_(None),
                    EconomicEvent.status == "pending",
                    or_(
                        EconomicEvent.is_high_impact == True,
                        EconomicEvent.importance     == "high",
                    ),
                )
            )
            .order_by(EconomicEvent.event_at.desc())
            .limit(10)
        )).scalars().all()

        if not rows:
            return 0

        # Build a normalized lookup so "Nonfarm Payrolls (MoM)" matches "US Nonfarm Payrolls"
        norm_series = {_normalize_name(k): v for k, v in _NAME_TO_SERIES.items()}

        filled = 0
        for ev in rows:
            series_info = norm_series.get(_normalize_name(ev.event_name))
            if series_info is None:
                continue
            series_id, transform, yoy_periods = series_info

            actual = await self._fred.fetch_actuals_for_event(series_id, transform, yoy_periods)
            if actual is None:
                continue

            ev.actual = actual
            ev.status = "released"
            filled += 1
            logger.info("[actuals_scanner] %s → actual=%s", ev.event_name, actual)

        if filled:
            await db.commit()

        return filled

    # ── Query helpers ──────────────────────────────────────────────────────────

    async def get_upcoming(
        self,
        db: AsyncSession,
        *,
        hours: int = 48,
        currency: str | None = None,
        currencies: list[str] | None = None,
        importance: str | None = None,
    ) -> list[dict]:
        now    = datetime.now(UTC)
        cutoff = now + timedelta(hours=hours)

        q = (
            select(EconomicEvent)
            .where(EconomicEvent.event_at >= now)
            .where(EconomicEvent.event_at <= cutoff)
            .where(EconomicEvent.status   == "pending")
            .order_by(EconomicEvent.event_at)
        )
        if currencies:
            q = q.where(EconomicEvent.currency.in_([c.upper() for c in currencies]))
        elif currency:
            q = q.where(EconomicEvent.currency == currency.upper())
        if importance:
            q = q.where(EconomicEvent.importance == importance.lower())

        rows = (await db.execute(q)).scalars().all()
        return [_event_to_dict(r) for r in rows]

    async def get_recent_releases(
        self,
        db: AsyncSession,
        *,
        hours: int = 72,
        currency: str | None = None,
        currencies: list[str] | None = None,
    ) -> list[dict]:
        now   = datetime.now(UTC)
        since = now - timedelta(hours=hours)

        q = (
            select(EconomicEvent)
            .where(EconomicEvent.event_at >= since)
            .where(EconomicEvent.event_at <= now)
            .where(EconomicEvent.status   == "released")
            .order_by(EconomicEvent.event_at.desc())
        )
        if currencies:
            q = q.where(EconomicEvent.currency.in_([c.upper() for c in currencies]))
        elif currency:
            q = q.where(EconomicEvent.currency == currency.upper())

        rows = (await db.execute(q)).scalars().all()
        return [_event_to_dict(r) for r in rows]

    async def get_newly_released(self, db: AsyncSession, since_minutes: int = 20) -> list[EconomicEvent]:
        """Return events that just got their actual in the last N minutes."""
        cutoff = datetime.now(UTC) - timedelta(minutes=since_minutes)
        rows = (await db.execute(
            select(EconomicEvent)
            .where(EconomicEvent.actual.isnot(None))
            .where(EconomicEvent.updated_at >= cutoff)
            .where(EconomicEvent.status == "released")
        )).scalars().all()
        return list(rows)

    async def get_high_impact_window(
        self,
        db: AsyncSession,
        *,
        hours_before: int = 2,
        hours_after: int = 2,
    ) -> list[dict]:
        """Events in the ±N-hour window around 'now' — useful for risk dashboards."""
        now    = datetime.now(UTC)
        start  = now - timedelta(hours=hours_before)
        end    = now + timedelta(hours=hours_after)

        rows = (await db.execute(
            select(EconomicEvent)
            .where(EconomicEvent.event_at >= start)
            .where(EconomicEvent.event_at <= end)
            .where(EconomicEvent.is_high_impact == True)
            .order_by(EconomicEvent.event_at)
        )).scalars().all()
        return [_event_to_dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """Normalize event name for fuzzy deduplication across providers."""
    import re
    n = name.lower().strip()
    n = re.sub(r"^us\s+", "", n)               # strip "US " prefix (FRED)
    n = re.sub(r"\s*\([^)]*\)\s*$", "", n)     # strip trailing "(May)", "(YoY)", etc.
    n = re.sub(r"\s+", " ", n)
    return n.strip()


def _merge_providers(fred: list[dict], scraper: list[dict]) -> list[dict]:
    """
    Merge two event lists keyed on (normalized_name, event_at date).
    FRED provides actuals; scraper provides forecasts.
    Scraper events take priority for metadata; FRED fills in actuals.
    """
    # Deduplicate scraper events first (Investing.com sometimes returns duplicates).
    # Keep the entry with the most data (prefer one with forecast).
    scraper_deduped: dict[tuple, dict] = {}
    for ev in scraper:
        key = (_normalize_name(ev["event_name"]), ev["event_at"].date())
        existing = scraper_deduped.get(key)
        if existing is None or (ev.get("forecast") is not None and existing.get("forecast") is None):
            scraper_deduped[key] = ev
    scraper = list(scraper_deduped.values())

    # Index scraper events by (normalized_name, date)
    scraper_idx: dict[tuple, dict] = {}
    for ev in scraper:
        key = (_normalize_name(ev["event_name"]), ev["event_at"].date())
        scraper_idx[key] = ev

    merged: list[dict] = list(scraper)

    for fev in fred:
        key = (_normalize_name(fev["event_name"]), fev["event_at"].date())
        if key in scraper_idx:
            # Enrich scraper event with FRED actual and correct timestamp
            target = scraper_idx[key]
            # Only copy actual + mark released when FRED confirms the event has passed
            if (target.get("actual") is None
                    and fev.get("actual") is not None
                    and fev.get("status") == "released"):
                target["actual"] = fev["actual"]
                target["status"] = "released"
            if target.get("source_id") is None:
                target["source_id"] = fev["source_id"]
            # FRED timestamp is authoritative (always UTC-correct)
            target["event_at"] = fev["event_at"]
        else:
            merged.append(fev)

    return merged


def _event_to_dict(ev: EconomicEvent) -> dict:
    return {
        "id":           ev.id,
        "event_name":   ev.event_name,
        "currency":     ev.currency,
        "country":      ev.country,
        "category":     ev.category,
        "importance":   ev.importance,
        "event_at":     ev.event_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "forecast":     ev.forecast,
        "actual":       ev.actual,
        "previous":     ev.previous,
        "revised":      ev.revised,
        "unit":         ev.unit,
        "status":       ev.status,
        "is_high_impact": ev.is_high_impact,
    }
