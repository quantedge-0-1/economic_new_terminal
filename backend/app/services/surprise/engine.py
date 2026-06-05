"""
SurpriseEngine — computes and stores economic surprise scores.

Surprise metrics:
  raw_surprise   = actual - forecast
  surprise_pct   = raw / |forecast|        (% deviation from consensus)
  surprise_std   = raw / std(last_N_raws)  (z-score: how unusual is this?)

Labels:
  surprise_std >= +1.5  → "large_beat"
  surprise_std >= +0.5  → "beat"
  -0.5 < std < +0.5    → "in_line"
  surprise_std <= -0.5  → "miss"
  surprise_std <= -1.5  → "large_miss"

The rolling window uses the last 24 releases of the same event name.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.db.models import EconomicEvent, EventSurprise

logger = get_logger(__name__)

_LOOKBACK_N   = 24    # rolling window for std computation
_LABEL_THRESHOLDS = [
    (+1.5, "large_beat"),
    (+0.5, "beat"),
    (-0.5, "in_line"),
    (-1.5, "miss"),
]


def _label(z: float | None) -> str:
    if z is None:
        return "in_line"
    for threshold, lab in _LABEL_THRESHOLDS:
        if z >= threshold:
            return lab
    return "large_miss"


def _std(values: list[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance) if variance > 0 else None


class SurpriseEngine:

    async def compute_for_event(
        self,
        db: AsyncSession,
        event: EconomicEvent,
    ) -> EventSurprise | None:
        """
        Compute surprise for a released event and persist it.
        Returns None if event has no forecast or actual.
        """
        if event.actual is None or event.forecast is None:
            return None

        # Check if already computed
        existing = (await db.execute(
            select(EventSurprise).where(EventSurprise.event_id == event.id)
        )).scalar_one_or_none()
        if existing:
            return existing

        raw = event.actual - event.forecast
        surprise_pct = (raw / abs(event.forecast)) if event.forecast != 0 else None

        # Historical surprises for same event name
        history_rows = (await db.execute(
            select(EventSurprise.raw_surprise)
            .where(EventSurprise.event_name == event.event_name)
            .order_by(EventSurprise.event_at.desc())
            .limit(_LOOKBACK_N)
        )).scalars().all()

        historical = list(history_rows)
        std  = _std(historical) if len(historical) >= 3 else None
        z    = (raw / std) if std and std > 0 else None

        surprise = EventSurprise(
            event_id       = event.id,
            event_name     = event.event_name,
            currency       = event.currency,
            event_at       = event.event_at,
            actual         = event.actual,
            forecast       = event.forecast,
            previous       = event.previous,
            raw_surprise   = round(raw, 4),
            surprise_pct   = round(surprise_pct, 4) if surprise_pct is not None else None,
            surprise_std   = round(z, 3) if z is not None else None,
            surprise_label = _label(z),
            lookback_n     = len(historical),
        )
        db.add(surprise)
        await db.flush()
        z_str = f"{z:.2f}" if z is not None else "N/A"
        logger.info(
            "[surprise] %s | actual=%s forecast=%s raw=%+.4f z=%s → %s",
            event.event_name, event.actual, event.forecast, raw, z_str, surprise.surprise_label,
        )
        return surprise

    async def get_recent(
        self,
        db: AsyncSession,
        *,
        limit: int = 20,
        currency: str | None = None,
    ) -> list[dict]:
        q = (
            select(EventSurprise)
            .order_by(EventSurprise.event_at.desc())
            .limit(limit)
        )
        if currency:
            q = q.where(EventSurprise.currency == currency.upper())
        rows = (await db.execute(q)).scalars().all()
        return [_surprise_to_dict(r) for r in rows]

    async def get_history(
        self,
        db: AsyncSession,
        event_name: str,
        *,
        limit: int = 36,
    ) -> list[dict]:
        rows = (await db.execute(
            select(EventSurprise)
            .where(EventSurprise.event_name.ilike(f"%{event_name}%"))
            .order_by(EventSurprise.event_at.desc())
            .limit(limit)
        )).scalars().all()
        return [_surprise_to_dict(r) for r in rows]

    async def get_summary_stats(
        self,
        db: AsyncSession,
        event_name: str,
    ) -> dict:
        """Statistical summary for a specific event across its history."""
        rows = (await db.execute(
            select(EventSurprise)
            .where(EventSurprise.event_name.ilike(f"%{event_name}%"))
            .order_by(EventSurprise.event_at.desc())
            .limit(48)
        )).scalars().all()

        if not rows:
            return {"event_name": event_name, "n": 0, "available": False}

        raws = [r.raw_surprise for r in rows]
        beat_count = sum(1 for r in rows if r.surprise_label in ("beat", "large_beat"))
        miss_count = sum(1 for r in rows if r.surprise_label in ("miss", "large_miss"))
        n = len(rows)

        return {
            "event_name":    event_name,
            "n":             n,
            "available":     True,
            "beat_rate":     round(beat_count / n, 3),
            "miss_rate":     round(miss_count / n, 3),
            "inline_rate":   round((n - beat_count - miss_count) / n, 3),
            "avg_raw":       round(sum(raws) / n, 4),
            "std_raw":       round(_std(raws) or 0, 4),
            "max_beat":      round(max(raws), 4),
            "max_miss":      round(min(raws), 4),
            "label_dist":    _label_distribution(rows),
        }


def _label_distribution(rows) -> dict:
    dist: dict[str, int] = {}
    for r in rows:
        dist[r.surprise_label] = dist.get(r.surprise_label, 0) + 1
    return dist


def _surprise_to_dict(s: EventSurprise) -> dict:
    return {
        "id":             s.id,
        "event_id":       s.event_id,
        "event_name":     s.event_name,
        "currency":       s.currency,
        "event_at":       s.event_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actual":         s.actual,
        "forecast":       s.forecast,
        "previous":       s.previous,
        "raw_surprise":   s.raw_surprise,
        "surprise_pct":   s.surprise_pct,
        "surprise_std":   s.surprise_std,
        "surprise_label": s.surprise_label,
        "lookback_n":     s.lookback_n,
    }
