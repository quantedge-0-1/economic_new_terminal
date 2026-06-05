"""
ORM models for Economic News Terminal.

Tables:
  economic_events    — calendar events (upcoming + historical)
  event_surprises    — surprise score per release
  price_reactions    — how assets reacted after each event
  news_articles      — scraped/parsed news with sentiment
  alerts             — triggered alert records
"""

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.base import Base


class EconomicEvent(Base):
    """
    One row per scheduled economic release.
    Updated in-place when the actual value becomes available.
    """
    __tablename__ = "economic_events"

    id           = Column(Integer,  primary_key=True, autoincrement=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Identity
    event_name   = Column(String(120), nullable=False)     # "US CPI YoY", "FOMC Rate Decision"
    source_id    = Column(String(80),  nullable=True)      # provider-specific ID (FRED series etc.)
    currency     = Column(String(10),  nullable=False)     # "USD", "EUR"
    country      = Column(String(50),  nullable=False)     # "United States"
    category     = Column(String(40),  nullable=False)     # "inflation" | "employment" | "gdp" | "rates" | "trade" | "housing"
    importance   = Column(String(10),  nullable=False)     # "high" | "medium" | "low"

    # Timing
    event_at     = Column(DateTime(timezone=True), nullable=False, index=True)
    release_window_min = Column(Integer, default=5)        # minutes after scheduled time before marking delayed

    # Values
    forecast     = Column(Float, nullable=True)            # consensus estimate
    actual       = Column(Float, nullable=True)            # released value (NULL until published)
    previous     = Column(Float, nullable=True)            # prior period value
    revised      = Column(Float, nullable=True)            # revised prior value if any
    unit         = Column(String(20), nullable=True)       # "%" | "K" | "B" | "index"

    # Status
    status       = Column(String(20), nullable=False, default="pending")
    # pending | released | revised | cancelled
    is_high_impact = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("event_name", "event_at", name="uq_event_name_at"),
        Index("idx_events_at", "event_at"),
        Index("idx_events_currency", "currency"),
        Index("idx_events_importance", "importance"),
        Index("idx_events_status", "status"),
    )


class EventSurprise(Base):
    """
    Surprise score computed at the moment actual > forecast is confirmed.

    surprise_std = (actual - forecast) / rolling_std(last_N_surprises)
    surprise_pct = (actual - forecast) / abs(forecast)  when forecast != 0
    """
    __tablename__ = "event_surprises"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    event_id        = Column(Integer, nullable=False, index=True)  # FK → economic_events.id
    computed_at     = Column(DateTime(timezone=True), server_default=func.now())

    event_name      = Column(String(120), nullable=False)
    currency        = Column(String(10),  nullable=False)
    event_at        = Column(DateTime(timezone=True), nullable=False)

    actual          = Column(Float, nullable=False)
    forecast        = Column(Float, nullable=False)
    previous        = Column(Float, nullable=True)

    raw_surprise    = Column(Float, nullable=False)    # actual - forecast
    surprise_pct    = Column(Float, nullable=True)     # raw / |forecast|
    surprise_std    = Column(Float, nullable=True)     # z-score vs rolling window
    surprise_label  = Column(String(20), nullable=False)
    # "large_beat" | "beat" | "in_line" | "miss" | "large_miss"

    lookback_n      = Column(Integer, nullable=True)   # how many past surprises used for std

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_surprise_event"),
        Index("idx_surprise_event_name", "event_name"),
        Index("idx_surprise_at", "event_at"),
    )


class PriceReaction(Base):
    """
    Price reaction of an asset after an economic event.
    Captured at multiple horizons post-release.

    One row per (event_id, asset, horizon).
    Written by the capture_price_reactions Celery task.
    """
    __tablename__ = "price_reactions"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    event_id       = Column(Integer, nullable=False, index=True)
    captured_at    = Column(DateTime(timezone=True), server_default=func.now())

    event_name     = Column(String(120), nullable=False)
    asset          = Column(String(20),  nullable=False)    # "XAUUSD", "DXY", "US10Y"
    surprise_label = Column(String(20),  nullable=True)     # copied from EventSurprise

    # Prices at key horizons
    price_pre      = Column(Float, nullable=True)    # T-5min
    price_t0       = Column(Float, nullable=True)    # T+0 (at release)
    price_1h       = Column(Float, nullable=True)    # T+1h
    price_4h       = Column(Float, nullable=True)    # T+4h
    price_24h      = Column(Float, nullable=True)    # T+24h

    # Returns (pct)
    ret_5min       = Column(Float, nullable=True)    # T+0 vs T-5min
    ret_1h         = Column(Float, nullable=True)
    ret_4h         = Column(Float, nullable=True)
    ret_24h        = Column(Float, nullable=True)

    # Direction
    direction_1h   = Column(String(5), nullable=True)    # "up" | "down" | "flat"
    direction_24h  = Column(String(5), nullable=True)

    __table_args__ = (
        UniqueConstraint("event_id", "asset", "horizon_label",
                         name="uq_reaction_event_asset_horizon"),
        Index("idx_reaction_event_id", "event_id"),
        Index("idx_reaction_asset", "asset"),
        Index("idx_reaction_event_name", "event_name"),
    )

    # horizon label stored as virtual (derived from which prices are set)
    horizon_label  = Column(String(10), nullable=False, default="24h")


class EventMemory(Base):
    """
    One row per analyzed economic event — ISS snapshot + post-event price moves.
    Filled progressively by background task using Polygon.io historical data.
    Enables historical pattern analysis and Historical Confidence Score.
    """
    __tablename__ = "event_memories"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Event identity
    event_name   = Column(String(120), nullable=False, index=True)
    event_at     = Column(DateTime(timezone=True), nullable=False, index=True)
    actual       = Column(Float, nullable=True)
    forecast     = Column(Float, nullable=True)
    previous     = Column(Float, nullable=True)
    surprise_pct = Column(Float, nullable=True)
    unit         = Column(String(20), nullable=True)

    # ISS snapshot at moment of analysis
    nss        = Column(Float, nullable=True)   # News Sentiment Score 0-100
    mcs        = Column(Float, nullable=True)   # Market Confirmation Score 0-100
    iss        = Column(Float, nullable=True)   # Composite ISS 0-100
    confidence = Column(Float, nullable=True)   # Claude confidence 0-100
    sentiment  = Column(String(20), nullable=True)  # bullish_gold | bearish_gold | neutral
    bull_prob  = Column(Float, nullable=True)
    bear_prob  = Column(Float, nullable=True)

    # Post-event price moves (% change from pre-event baseline)
    gold_move_5m  = Column(Float, nullable=True)
    gold_move_15m = Column(Float, nullable=True)
    gold_move_1h  = Column(Float, nullable=True)
    gold_move_4h  = Column(Float, nullable=True)
    dxy_move_1h   = Column(Float, nullable=True)
    us10y_move_1h = Column(Float, nullable=True)

    # Fill lifecycle
    status = Column(String(20), nullable=False, default="pending_fill")
    # pending_fill | partial | complete

    __table_args__ = (
        UniqueConstraint("event_name", "event_at", name="uq_memory_event"),
        Index("idx_memory_event_name", "event_name"),
        Index("idx_memory_event_at", "event_at"),
        Index("idx_memory_status", "status"),
    )


class NewsArticle(Base):
    """
    News article parsed from RSS feeds or GDELT.
    Stored for alert generation and trend analysis.
    """
    __tablename__ = "news_articles"

    id            = Column(Integer,  primary_key=True, autoincrement=True)
    fetched_at    = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    published_at  = Column(DateTime(timezone=True), nullable=True)

    source        = Column(String(60),  nullable=False)    # "reuters_rss" | "gdelt" | "ft_rss"
    source_url    = Column(String(500), nullable=True)
    title         = Column(Text, nullable=False)
    summary       = Column(Text, nullable=True)

    # Classification
    category      = Column(String(40), nullable=True)
    # "central_bank" | "inflation" | "employment" | "geopolitical" | "commodity" | "general"
    relevance_score = Column(Float, nullable=True)         # 0-1, relevance to gold/macro
    sentiment_score = Column(Float, nullable=True)         # -1 (bearish) to +1 (bullish for gold)
    sentiment_label = Column(String(15), nullable=True)    # "bullish" | "bearish" | "neutral"

    # Alert flag
    is_alert      = Column(Boolean, default=False)
    alert_level   = Column(String(10), nullable=True)      # "critical" | "high" | "medium"

    __table_args__ = (
        UniqueConstraint("source_url", name="uq_article_url"),
        Index("idx_articles_fetched_at", "fetched_at"),
        Index("idx_articles_alert", "is_alert"),
        Index("idx_articles_category", "category"),
    )


class Alert(Base):
    """
    Triggered alert — event surprise, news flash, or threshold breach.
    Consumed via GET /alerts or SSE stream.
    """
    __tablename__ = "alerts"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    triggered_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    alert_type   = Column(String(30), nullable=False)
    # "event_surprise" | "news_flash" | "rate_decision" | "data_release" | "threshold_breach"

    level        = Column(String(10), nullable=False)     # "critical" | "high" | "medium" | "low"
    title        = Column(String(200), nullable=False)
    body         = Column(Text, nullable=True)

    currency     = Column(String(10), nullable=True)
    asset        = Column(String(20), nullable=True)

    # Source reference
    event_id     = Column(Integer, nullable=True)         # → economic_events.id
    article_id   = Column(Integer, nullable=True)         # → news_articles.id

    is_read      = Column(Boolean, default=False)
    expires_at   = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_alerts_triggered_at", "triggered_at"),
        Index("idx_alerts_level", "level"),
        Index("idx_alerts_type", "alert_type"),
        Index("idx_alerts_read", "is_read"),
    )
