"""
AlertEngine — generates structured alerts for economic events.

Triggers:
  - Event surprise (actual vs forecast)
  - Upcoming high-impact event (pre-event warning)
  - Rate decision
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.db.models import Alert, EconomicEvent, EventSurprise

logger = get_logger(__name__)

_SURPRISE_THRESHOLDS = {
    "large_beat": "critical",
    "large_miss": "critical",
    "beat":        "high",
    "miss":        "high",
    "in_line":     "low",
}

_PRE_EVENT_HOURS = [24, 2, 0.5]  # alert 24h, 2h, 30min before high-impact events


class AlertEngine:

    async def generate_surprise_alert(
        self,
        db: AsyncSession,
        surprise: EventSurprise,
    ) -> Alert | None:
        """Create an alert when a surprise is computed."""
        level = _SURPRISE_THRESHOLDS.get(surprise.surprise_label, "medium")
        if level == "low":
            return None   # in-line results don't generate alerts

        sign   = "+" if surprise.raw_surprise > 0 else ""
        z_str  = f" (z={surprise.surprise_std:+.2f})" if surprise.surprise_std is not None else ""
        title  = (
            f"{surprise.event_name} {surprise.surprise_label.replace('_', ' ').upper()}: "
            f"actual={surprise.actual} vs forecast={surprise.forecast} "
            f"({sign}{surprise.raw_surprise:.3f}){z_str}"
        )

        alert = Alert(
            alert_type  = "event_surprise",
            level       = level,
            title       = title[:200],
            body        = self._surprise_body(surprise),
            currency    = surprise.currency,
            event_id    = surprise.event_id,
            expires_at  = datetime.now(UTC) + timedelta(hours=4),
        )
        db.add(alert)
        await db.flush()
        logger.info(f"[alert] {level.upper()} surprise alert: {title[:80]}")
        return alert

    async def generate_pre_event_alerts(self, db: AsyncSession) -> list[Alert]:
        """
        Scan upcoming high-impact events and create pre-event alerts
        at 24h, 2h, and 30min before event_at.
        """
        now   = datetime.now(UTC)
        end   = now + timedelta(hours=25)

        events = (await db.execute(
            select(EconomicEvent)
            .where(EconomicEvent.is_high_impact == True)
            .where(EconomicEvent.event_at >= now)
            .where(EconomicEvent.event_at <= end)
            .where(EconomicEvent.status == "pending")
        )).scalars().all()

        created: list[Alert] = []
        for event in events:
            for hours_before in _PRE_EVENT_HOURS:
                alert_time = event.event_at - timedelta(hours=hours_before)
                if abs((alert_time - now).total_seconds()) > 900:  # 15-min window
                    continue

                # Check if this alert already exists for this event+horizon
                label = f"pre_{int(hours_before * 60)}min"
                existing = (await db.execute(
                    select(Alert)
                    .where(Alert.event_id   == event.id)
                    .where(Alert.alert_type == f"pre_event_{label}")
                )).scalar_one_or_none()
                if existing:
                    continue

                horizon_label = f"{int(hours_before)}h" if hours_before >= 1 else "30min"
                alert = Alert(
                    alert_type = f"pre_event_{label}",
                    level      = "high" if hours_before <= 2 else "medium",
                    title      = f"⚠ {event.event_name} in {horizon_label} — {event.currency} high-impact",
                    body       = (
                        f"Scheduled: {event.event_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
                        f"Forecast: {event.forecast} {event.unit or ''}\n"
                        f"Previous: {event.previous} {event.unit or ''}"
                    ),
                    currency   = event.currency,
                    event_id   = event.id,
                    expires_at = event.event_at + timedelta(minutes=30),
                )
                db.add(alert)
                created.append(alert)

        if created:
            await db.flush()
        return created

    async def get_alerts(
        self,
        db: AsyncSession,
        *,
        limit: int = 50,
        level: str | None = None,
        unread_only: bool = False,
    ) -> list[dict]:
        q = (
            select(Alert)
            .order_by(Alert.triggered_at.desc())
            .limit(limit)
        )
        if level:
            q = q.where(Alert.level == level)
        if unread_only:
            q = q.where(Alert.is_read == False)  # noqa: E712
        rows = (await db.execute(q)).scalars().all()
        return [_alert_to_dict(r) for r in rows]

    async def mark_read(self, db: AsyncSession, *, alert_id: int) -> bool:
        row = (await db.execute(
            select(Alert).where(Alert.id == alert_id)
        )).scalar_one_or_none()
        if row:
            row.is_read = True
            await db.commit()
            return True
        return False

    def _surprise_body(self, s: EventSurprise) -> str:  # noqa: D401
        lines = [
            f"Event:    {s.event_name}",
            f"Released: {s.event_at.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Actual:   {s.actual}",
            f"Forecast: {s.forecast}",
            f"Previous: {s.previous}",
            f"Raw diff: {s.raw_surprise:+.4f}",
        ]
        if s.surprise_std is not None:
            lines.append(f"Z-score:  {s.surprise_std:+.2f} ({s.lookback_n} historical releases)")
        return "\n".join(lines)


def _alert_to_dict(a: Alert) -> dict:
    return {
        "id":           a.id,
        "alert_type":   a.alert_type,
        "level":        a.level,
        "title":        a.title,
        "body":         a.body,
        "currency":     a.currency,
        "asset":        a.asset,
        "triggered_at": a.triggered_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_read":      a.is_read,
        "expires_at":   a.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ") if a.expires_at else None,
        "event_id":     a.event_id,
        "article_id":   a.article_id,
    }
