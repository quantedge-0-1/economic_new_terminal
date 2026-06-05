"""
GET /api/v1/pre-release/status

Returns pre-release market discount analysis when a high-impact event
is scheduled within the next 10 minutes (or released in the past 5 min).

Designed for 30-second frontend polling; cached 60 seconds.
No WebSocket required — polling is sufficient for this latency.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.logger import get_logger
from app.db.models import EconomicEvent
from app.db.session import get_db
from app.services.pre_release.analysis import get_ai_analysis
from app.services.pre_release.engine import PreReleaseResult, analyze_pre_release

router = APIRouter()
logger = get_logger(__name__)

_WINDOW_MINUTES   = 10   # pre-release window opens T-10
_POST_MINUTES     = 5    # post-release window closes T+5


@router.get("/status")
async def get_pre_release_status(db: AsyncSession = Depends(get_db)):
    """
    Pre-release scanner endpoint.

    Active states:
      phase=PRE_RELEASE  → event in [now, now+10min]
      phase=POST_RELEASE → event in [now-5min, now]

    Inactive:
      {"active": false, "reason": "no_imminent_event"}
    """
    cache_key = "pre_release:status"
    cached = cache.get(cache_key)
    if cached:
        return cached

    now = datetime.now(UTC)

    # ── Attempt 1: upcoming high-impact event in next 10 min ─────────────────
    upcoming = (await db.execute(
        select(EconomicEvent)
        .where(
            and_(
                EconomicEvent.event_at >= now,
                EconomicEvent.event_at <= now + timedelta(minutes=_WINDOW_MINUTES),
                EconomicEvent.status   == "pending",
                or_(
                    EconomicEvent.is_high_impact == True,
                    EconomicEvent.importance     == "high",
                ),
            )
        )
        .order_by(EconomicEvent.event_at)
        .limit(1)
    )).scalar_one_or_none()

    if upcoming is None:
        # ── Attempt 2: event released in the last 5 min (post-release phase) ─
        recent = (await db.execute(
            select(EconomicEvent)
            .where(
                and_(
                    EconomicEvent.event_at >= now - timedelta(minutes=_POST_MINUTES),
                    EconomicEvent.event_at <= now,
                    or_(
                        EconomicEvent.is_high_impact == True,
                        EconomicEvent.importance     == "high",
                    ),
                )
            )
            .order_by(EconomicEvent.event_at.desc())
            .limit(1)
        )).scalar_one_or_none()

        if recent is None:
            result = {"active": False, "reason": "no_imminent_event"}
            cache.set(cache_key, result, 60)
            return result

        event_at_aware = _ensure_utc(recent.event_at)
        minutes_since  = max(0, int((now - event_at_aware).total_seconds() / 60))
        result = {
            "active":                True,
            "phase":                 "POST_RELEASE",
            "event_name":            recent.event_name,
            "currency":              recent.currency,
            "importance":            recent.importance,
            "minutes_since_release": minutes_since,
            "actual":                recent.actual,
            "forecast":              recent.forecast,
            "unit":                  recent.unit,
        }
        cache.set(cache_key, result, 30)
        return result

    # ── Pre-release window active ─────────────────────────────────────────────
    event_at_aware  = _ensure_utc(upcoming.event_at)
    delta_s         = (event_at_aware - now).total_seconds()
    minutes_left    = max(0, int(delta_s / 60))
    seconds_left    = max(0, int(delta_s))
    event_at_str    = upcoming.event_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Run signal engine (pure in-memory, no API calls)
    signals: PreReleaseResult = analyze_pre_release("XAUUSD")

    # Claude Haiku analysis — one call per event window, cached 5 min
    ai_text = await get_ai_analysis(
        event_name=upcoming.event_name,
        event_at_str=event_at_str,
        signals=signals,
        minutes_to_release=minutes_left,
    )

    data_quality = (
        "HIGH"   if signals.history_depth_s >= 600  else
        "MEDIUM" if signals.history_depth_s >= 180  else
        "LOW"
    )

    result = {
        "active":   True,
        "phase":    "PRE_RELEASE",

        # Event metadata
        "event_name":           upcoming.event_name,
        "currency":             upcoming.currency,
        "importance":           upcoming.importance,
        "event_at":             event_at_str,
        "forecast":             upcoming.forecast,
        "previous":             upcoming.previous,
        "unit":                 upcoming.unit,

        # Countdown
        "minutes_to_release":  minutes_left,
        "seconds_to_release":  seconds_left,

        # Price signals
        "instrument":          signals.symbol,
        "current_price":       signals.current_price,
        "bsl":                 signals.bsl,
        "ssl":                 signals.ssl,
        "equilibrium":         signals.equilibrium,
        "price_zone":          signals.price_zone,
        "is_consolidating":    signals.is_consolidating,
        "displacement_10m_pct": signals.displacement_10m_pct,
        "displacement_30m_pct": signals.displacement_30m_pct,
        "range_30m_pct":       signals.range_30m_pct,
        "directional_bias":    signals.directional_bias,
        "bsl_swept":           signals.bsl_swept,
        "ssl_swept":           signals.ssl_swept,
        "history_depth_s":     signals.history_depth_s,

        # Scores
        "discount_score":      signals.discount_score,
        "displacement_score":  signals.displacement_score,
        "sweep_score":         signals.sweep_score,
        "structure_score":     signals.structure_score,
        "consolidation_score": signals.consolidation_score,

        # Classification
        "institutional_state": signals.institutional_state,
        "state_label":         signals.state_label,
        "state_color":         signals.state_color,
        "smc_note":            signals.smc_note,
        "trader_action":       signals.trader_action,

        # AI analysis
        "ai_analysis":         ai_text,

        # Data quality flag for UI
        "data_quality":        data_quality,
    }

    cache.set(cache_key, result, 60)
    return result


def _ensure_utc(dt: datetime) -> datetime:
    """Return a UTC-aware datetime regardless of how SQLite stored it."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
