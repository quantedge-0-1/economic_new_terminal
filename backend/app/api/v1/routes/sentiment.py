"""
Sentiment ISS routes + Event Memory Engine.

POST /api/v1/sentiment/analyze            — Full ISS (NSS + MCS) + saves to memory
GET  /api/v1/sentiment/current            — Latest ISS result
GET  /api/v1/sentiment/mcs                — Market Confirmation Score only
GET  /api/v1/sentiment/event-memory       — Historical events + patterns + hist confidence
GET  /api/v1/sentiment/event-memory/patterns — Aggregate pattern stats
POST /api/v1/sentiment/event-memory/fill  — Trigger Polygon fill for pending rows
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.logger import get_logger
from app.db.models import EventMemory
from app.db.session import get_db
from app.services.sentiment.engine import compute_iss, compute_mcs
from app.services.sentiment.memory import (
    compute_historical_confidence,
    compute_patterns,
    fill_pending_moves,
    save_event_memory,
)

logger = get_logger(__name__)
router = APIRouter()

_latest_iss: dict[str, Any] = {}


class SentimentRequest(BaseModel):
    event_name: str
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    surprise_pct: float | None = None
    currency: str = "USD"
    importance: str = "high"
    unit: str | None = None
    event_at: str | None = None  # ISO datetime of the event (optional)


# ── ISS endpoints ──────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze_sentiment(req: SentimentRequest, db: AsyncSession = Depends(get_db)):
    """
    Compute full ISS for an economic event.
    NSS via Claude Haiku + MCS from live price history.
    Persists result to EventMemory for historical analysis.
    """
    global _latest_iss

    cache_key = f"iss:{req.event_name}:{req.actual}:{req.forecast}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    result = await compute_iss(req.model_dump())
    result["computed_at"] = datetime.now(timezone.utc).isoformat()

    cache.set(cache_key, result, 300)
    _latest_iss = result

    # Persist to EventMemory (non-blocking — failure doesn't affect response)
    try:
        event_data = req.model_dump()
        if req.event_at:
            event_data["event_at"] = datetime.fromisoformat(
                req.event_at.replace("Z", "+00:00")
            )
        await save_event_memory(db, event_data, result)
    except Exception as exc:
        logger.warning("[Memory] non-critical save error: %s", exc)

    logger.info(
        "ISS | event=%s | ISS=%d | %s | NSS=%d | MCS=%d",
        req.event_name, result["iss"], result["classification"]["label"],
        result["nss"]["score"], result["mcs"]["score"],
    )
    return result


@router.get("/current")
async def get_current_sentiment():
    """Return the most recently computed ISS (no Claude call)."""
    if not _latest_iss:
        return {
            "available": False,
            "message": "No hay análisis de sentimiento aún. Analiza un evento primero.",
        }
    return {**_latest_iss, "available": True}


@router.get("/mcs")
async def get_mcs_only(sentiment: str = Query("neutral")):
    """
    Compute Market Confirmation Score for a given sentiment direction.
    No Claude call — fast real-time endpoint.
    sentiment: bullish_gold | bearish_gold | neutral
    """
    valid = {"bullish_gold", "bearish_gold", "neutral"}
    if sentiment not in valid:
        sentiment = "neutral"
    mcs = compute_mcs(sentiment)
    mcs["computed_at"] = datetime.now(timezone.utc).isoformat()
    return mcs


# ── Event Memory endpoints ─────────────────────────────────────────────────────

@router.get("/event-memory")
async def get_event_memory(
    event_name: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    Return stored EventMemory rows with pattern analysis and Historical Confidence Score.

    Filters:
      event_name — filter to a specific event type (e.g. "US Nonfarm Payrolls")

    Response includes:
      memories             — list of stored events with ISS + price moves
      patterns             — aggregate statistics across all memories
      historical_confidence — predictive win-rate for the queried/latest event
    """
    # Filtered query
    q = (
        select(EventMemory)
        .order_by(EventMemory.event_at.desc())
        .limit(limit)
    )
    if event_name:
        q = q.where(EventMemory.event_name == event_name)

    rows = (await db.execute(q)).scalars().all()

    # Full dataset for patterns + confidence (up to 500 rows)
    all_rows = (await db.execute(
        select(EventMemory).order_by(EventMemory.event_at.desc()).limit(500)
    )).scalars().all()

    patterns = compute_patterns(list(all_rows))

    # Historical Confidence for the target event
    hist_confidence = None
    target_name     = event_name or _latest_iss.get("event_name")
    if target_name:
        # Use latest surprise_pct + NSS for the target event from memory or _latest_iss
        latest_surprise = None
        latest_nss      = None
        if event_name:
            match = next((m for m in all_rows if m.event_name == event_name), None)
            if match:
                latest_surprise = match.surprise_pct
                latest_nss      = match.nss
        elif _latest_iss:
            latest_nss      = _latest_iss.get("nss", {}).get("score")
            latest_surprise = None  # not stored in _latest_iss at top level

        hist_confidence = compute_historical_confidence(
            target_name, latest_surprise, latest_nss, list(all_rows)
        )

    return {
        "memories":              [_memory_to_dict(m) for m in rows],
        "total":                 len(rows),
        "patterns":              patterns,
        "historical_confidence": hist_confidence,
    }


@router.get("/event-memory/patterns")
async def get_memory_patterns(db: AsyncSession = Depends(get_db)):
    """
    Aggregate pattern statistics across all stored EventMemory records.
    Answers: NSS accuracy, ISS accuracy, per-event breakdown.
    """
    rows = (await db.execute(
        select(EventMemory).order_by(EventMemory.event_at.desc()).limit(500)
    )).scalars().all()
    return compute_patterns(list(rows))


@router.post("/event-memory/fill")
async def trigger_memory_fill(db: AsyncSession = Depends(get_db)):
    """
    Manually trigger Polygon price fill for pending EventMemory rows.
    Normally run by background task every 10 minutes.
    """
    updated = await fill_pending_moves(db)
    return {
        "updated": updated,
        "message": f"Rellenados {updated} registro(s) con datos de Polygon",
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _memory_to_dict(m: EventMemory) -> dict:
    return {
        "id":            m.id,
        "event_name":    m.event_name,
        "event_at":      m.event_at.strftime("%Y-%m-%dT%H:%M:%SZ") if m.event_at else None,
        "actual":        m.actual,
        "forecast":      m.forecast,
        "previous":      m.previous,
        "surprise_pct":  m.surprise_pct,
        "unit":          m.unit,
        "nss":           m.nss,
        "mcs":           m.mcs,
        "iss":           m.iss,
        "confidence":    m.confidence,
        "sentiment":     m.sentiment,
        "bull_prob":     m.bull_prob,
        "bear_prob":     m.bear_prob,
        "gold_move_5m":  m.gold_move_5m,
        "gold_move_15m": m.gold_move_15m,
        "gold_move_1h":  m.gold_move_1h,
        "gold_move_4h":  m.gold_move_4h,
        "dxy_move_1h":   m.dxy_move_1h,
        "us10y_move_1h": m.us10y_move_1h,
        "status":        m.status,
        "created_at":    m.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if m.created_at else None,
    }
