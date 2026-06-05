"""
Event Memory Engine — persistence and pattern analysis for ISS events.

Lifecycle:
  1. save_event_memory()  — called on every ISS computation, upserts EventMemory row
  2. fill_pending_moves() — background task, fills price moves via Polygon when windows pass
  3. compute_historical_confidence() — pattern matching for predictive confidence
  4. compute_patterns()   — aggregate statistics across all stored memories
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.db.models import EventMemory
from app.services.prices.polygon import compute_post_event_moves

logger = get_logger(__name__)


async def save_event_memory(
    db: AsyncSession,
    event_data: dict,
    iss_result: dict,
) -> EventMemory | None:
    """
    Upsert EventMemory when ISS is computed for an event.
    On conflict (same event_name + event_at) updates ISS fields, preserves price moves.
    """
    event_name  = event_data.get("event_name", "")
    event_at_in = event_data.get("event_at")

    if isinstance(event_at_in, datetime):
        event_at = event_at_in
    elif isinstance(event_at_in, str):
        try:
            event_at = datetime.fromisoformat(event_at_in.replace("Z", "+00:00"))
        except ValueError:
            event_at = datetime.now(UTC).replace(second=0, microsecond=0)
    else:
        event_at = datetime.now(UTC).replace(second=0, microsecond=0)

    nss = iss_result.get("nss", {})
    mcs = iss_result.get("mcs", {})

    try:
        existing = (await db.execute(
            select(EventMemory)
            .where(EventMemory.event_name == event_name)
            .where(EventMemory.event_at   == event_at)
        )).scalar_one_or_none()

        if existing is not None:
            existing.nss        = nss.get("score")
            existing.mcs        = mcs.get("score")
            existing.iss        = iss_result.get("iss")
            existing.confidence = nss.get("confidence")
            existing.sentiment  = nss.get("sentiment")
            existing.bull_prob  = nss.get("bull_probability")
            existing.bear_prob  = nss.get("bear_probability")
            await db.commit()
            logger.debug("[Memory] updated existing id=%d for %s", existing.id, event_name)
            return existing

        row = EventMemory(
            event_name   = event_name,
            event_at     = event_at,
            actual       = event_data.get("actual"),
            forecast     = event_data.get("forecast"),
            previous     = event_data.get("previous"),
            surprise_pct = event_data.get("surprise_pct"),
            unit         = event_data.get("unit"),
            nss          = nss.get("score"),
            mcs          = mcs.get("score"),
            iss          = iss_result.get("iss"),
            confidence   = nss.get("confidence"),
            sentiment    = nss.get("sentiment"),
            bull_prob    = nss.get("bull_probability"),
            bear_prob    = nss.get("bear_probability"),
            status       = "pending_fill",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("[Memory] saved id=%d for %s @ %s", row.id, event_name, event_at.isoformat())
        return row

    except Exception as exc:
        logger.warning("[Memory] save failed for %s: %s", event_name, exc)
        await db.rollback()
        return None


async def fill_pending_moves(db: AsyncSession) -> int:
    """
    Find pending EventMemory rows and fill in Polygon price moves
    for windows that have sufficiently passed.
    """
    now = datetime.now(UTC)
    rows = (await db.execute(
        select(EventMemory)
        .where(EventMemory.status != "complete")
        .where(EventMemory.event_at <= now - timedelta(minutes=5))
        .order_by(EventMemory.event_at.desc())
        .limit(20)
    )).scalars().all()

    if not rows:
        return 0

    updated = 0
    for row in rows:
        try:
            moves = await compute_post_event_moves(row.event_at)

            changed = False
            for field, value in moves.items():
                if value is not None and getattr(row, field) is None:
                    setattr(row, field, value)
                    changed = True

            # Determine completeness
            four_h_due = row.event_at <= now - timedelta(minutes=260)
            if four_h_due:
                row.status = "complete"
            elif row.gold_move_5m is not None:
                row.status = "partial"

            if changed:
                await db.commit()
                updated += 1
                logger.info(
                    "[Memory] filled moves for %s id=%d status=%s gold_1h=%s",
                    row.event_name, row.id, row.status, row.gold_move_1h,
                )
        except Exception as exc:
            logger.warning("[Memory] fill error id=%d: %s", row.id, exc)
            await db.rollback()

    return updated


def compute_historical_confidence(
    event_name: str,
    surprise_pct: float | None,
    nss_score: float | None,
    memories: list[EventMemory],
) -> dict[str, Any]:
    """
    Historical Confidence Score: given current event context, look up
    similar past events and compute predictive win rate for gold direction.

    Similarity: same event_name + surprise_pct within ±15 percentage points.
    Falls back to any event of same name if no close surprise matches.
    """
    surprise_pct = surprise_pct or 0.0
    nss_score    = nss_score or 50.0
    bullish      = nss_score > 50

    def is_similar(m: EventMemory) -> bool:
        return (
            m.event_name == event_name
            and m.gold_move_1h is not None
            and m.surprise_pct is not None
            and abs((m.surprise_pct or 0) - surprise_pct) <= 15
        )

    similar = [m for m in memories if is_similar(m)]
    if not similar:
        # Broader: any event of same name with known gold_move_1h
        similar = [
            m for m in memories
            if m.event_name == event_name and m.gold_move_1h is not None
        ]

    if not similar:
        return {
            "score":         50,
            "based_on":      0,
            "avg_gold_1h":   None,
            "gold_up_pct":   None,
            "gold_down_pct": None,
            "best_nss_pct":  None,
            "message":       "Sin historial disponible para este evento",
        }

    gold_moves = [m.gold_move_1h for m in similar]
    gold_up    = sum(1 for v in gold_moves if v > 0)
    gold_down  = len(gold_moves) - gold_up
    avg_move   = sum(gold_moves) / len(gold_moves)

    win_rate = (gold_up / len(similar)) if bullish else (gold_down / len(similar))

    # Sample weight: ramp from 0.5 at 1 sample → 1.0 at 10+ samples
    sample_weight = min(1.0, len(similar) / 10)
    raw_score = win_rate * 100 * sample_weight + 50 * (1 - sample_weight)
    score = max(0, min(100, round(raw_score)))

    # NSS accuracy: when past NSS was high, did gold actually go up?
    high_nss_events = [m for m in similar if (m.nss or 0) > 70]
    best_nss_pct = None
    if high_nss_events:
        best_nss_pct = round(
            sum(1 for m in high_nss_events if (m.gold_move_1h or 0) > 0)
            / len(high_nss_events) * 100, 1
        )

    return {
        "score":         score,
        "based_on":      len(similar),
        "avg_gold_1h":   round(avg_move, 3),
        "gold_up_pct":   round(gold_up   / len(similar) * 100, 1),
        "gold_down_pct": round(gold_down / len(similar) * 100, 1),
        "best_nss_pct":  best_nss_pct,
        "message":       f"Basado en {len(similar)} eventos similares",
    }


def compute_patterns(memories: list[EventMemory]) -> dict[str, Any]:
    """
    Aggregate pattern statistics across all stored memories with known gold_move_1h.
    """
    complete = [m for m in memories if m.gold_move_1h is not None]

    if not complete:
        return {
            "total_events":     0,
            "message":          "Sin suficientes datos históricos aún",
            "by_event":         {},
        }

    moves_1h = [m.gold_move_1h for m in complete]
    avg_1h   = sum(moves_1h) / len(moves_1h)
    gold_up  = sum(1 for v in moves_1h if v > 0)

    high_nss = [m for m in complete if (m.nss or 0) > 70]
    high_iss = [m for m in complete if (m.iss or 0) > 70]

    high_nss_up_pct = (
        round(sum(1 for m in high_nss if (m.gold_move_1h or 0) > 0) / len(high_nss) * 100, 1)
        if high_nss else None
    )
    high_iss_up_pct = (
        round(sum(1 for m in high_iss if (m.gold_move_1h or 0) > 0) / len(high_iss) * 100, 1)
        if high_iss else None
    )

    # Per-event aggregation
    by_event: dict[str, list] = {}
    for m in complete:
        by_event.setdefault(m.event_name, []).append(m)

    event_stats = {}
    for name, evs in by_event.items():
        ev_moves = [e.gold_move_1h for e in evs]
        ev_up    = sum(1 for v in ev_moves if v > 0)
        event_stats[name] = {
            "count":      len(evs),
            "avg_1h":     round(sum(ev_moves) / len(evs), 3),
            "up_pct":     round(ev_up / len(evs) * 100, 1),
            "avg_iss":    round(sum((e.iss or 0) for e in evs) / len(evs), 1),
        }

    return {
        "total_events":       len(complete),
        "avg_gold_move_1h":   round(avg_1h, 3),
        "gold_up_1h_pct":     round(gold_up / len(complete) * 100, 1),
        "high_nss_accuracy":  high_nss_up_pct,
        "high_iss_accuracy":  high_iss_up_pct,
        "high_nss_count":     len(high_nss),
        "high_iss_count":     len(high_iss),
        "by_event":           event_stats,
    }
