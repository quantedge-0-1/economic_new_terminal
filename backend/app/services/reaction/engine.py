"""
ReactionEngine — captures and analyzes historical price reactions
to economic events.

Data source: yfinance (free, no API key).
Assets tracked: XAUUSD, DXY, US10Y, SPX.

Pipeline (per event release):
  1. Fetch T-5min, T+0, T+1h, T+4h, T+24h prices via yfinance
  2. Compute returns and directional labels
  3. Persist to price_reactions table

Analysis:
  - aggregate_reactions(event_name): given this event + surprise label,
    how does XAUUSD typically react?
  - Returns win_rate, avg_return, median_return, n for each horizon
"""

from __future__ import annotations

import asyncio
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

import yfinance as yf
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.db.models import EventSurprise, PriceReaction

logger = get_logger(__name__)

# yfinance tickers for each tracked asset
_ASSET_TICKERS: dict[str, str] = {
    "XAUUSD": "GC=F",    # Gold futures (CME)
    "DXY":    "DX-Y.NYB",
    "US10Y":  "^TNX",
    "SPX":    "^GSPC",
    "XAGUSD": "SI=F",    # Silver
}

_HORIZONS = [
    ("1h",  60),
    ("4h",  240),
    ("24h", 1440),
]


class ReactionEngine:

    async def capture_reactions(
        self,
        db: AsyncSession,
        surprise: EventSurprise,
        assets: list[str] | None = None,
    ) -> list[dict]:
        """
        Capture price reactions for a given surprise event.
        Runs after event_at has passed — fetches historical 1-min data.
        Returns list of captured reaction dicts.
        """
        assets = assets or ["XAUUSD", "DXY", "US10Y"]
        results: list[dict] = []

        for asset in assets:
            try:
                reaction = await self._capture_one(db, surprise, asset)
                if reaction:
                    results.append(_reaction_to_dict(reaction))
            except Exception as exc:
                logger.warning(f"[reaction] {asset} @ {surprise.event_name}: {exc}")

        await db.commit()
        return results

    async def _capture_one(
        self,
        db: AsyncSession,
        surprise: EventSurprise,
        asset: str,
    ) -> PriceReaction | None:
        # Check if already captured
        existing = (await db.execute(
            select(PriceReaction)
            .where(PriceReaction.event_id == surprise.event_id)
            .where(PriceReaction.asset    == asset)
            .where(PriceReaction.horizon_label == "24h")
        )).scalar_one_or_none()
        if existing:
            return existing

        ticker_sym = _ASSET_TICKERS.get(asset)
        if not ticker_sym:
            return None

        event_dt = surprise.event_at
        prices   = await asyncio.get_running_loop().run_in_executor(
            None, _fetch_prices, ticker_sym, event_dt
        )

        if not prices or prices.get("t0") is None:
            logger.warning(f"[reaction] no price data for {asset} around {event_dt}")
            return None

        price_pre = prices.get("pre")
        price_t0  = prices["t0"]
        price_1h  = prices.get("1h")
        price_4h  = prices.get("4h")
        price_24h = prices.get("24h")

        def ret(p_end, p_start=price_t0):
            if p_end is None or p_start is None or p_start == 0:
                return None
            return round((p_end - p_start) / p_start * 100, 4)

        def direction(r):
            if r is None:   return None
            if r > 0.05:    return "up"
            if r < -0.05:   return "down"
            return "flat"

        r_1h  = ret(price_1h)
        r_4h  = ret(price_4h)
        r_24h = ret(price_24h)
        r_5min = ret(price_t0, price_pre) if price_pre else None

        reaction = PriceReaction(
            event_id       = surprise.event_id,
            event_name     = surprise.event_name,
            asset          = asset,
            surprise_label = surprise.surprise_label,
            price_pre      = price_pre,
            price_t0       = price_t0,
            price_1h       = price_1h,
            price_4h       = price_4h,
            price_24h      = price_24h,
            ret_5min       = r_5min,
            ret_1h         = r_1h,
            ret_4h         = r_4h,
            ret_24h        = r_24h,
            direction_1h   = direction(r_1h),
            direction_24h  = direction(r_24h),
            horizon_label  = "24h",
        )
        db.add(reaction)
        await db.flush()
        return reaction

    # ── Historical analysis ────────────────────────────────────────────────────

    async def aggregate_reactions(
        self,
        db: AsyncSession,
        event_name: str,
        asset: str = "XAUUSD",
        surprise_label: str | None = None,
    ) -> dict:
        """
        Statistical summary of how 'asset' reacted to past 'event_name' releases.

        If surprise_label is provided, filter by that label (e.g. "large_beat").
        Returns per-horizon win_rate, avg_return, n.
        """
        q = (
            select(PriceReaction)
            .where(PriceReaction.event_name.ilike(f"%{event_name}%"))
            .where(PriceReaction.asset == asset)
        )
        if surprise_label:
            q = q.where(PriceReaction.surprise_label == surprise_label)

        rows = (await db.execute(q)).scalars().all()
        if not rows:
            return {
                "event_name":     event_name,
                "asset":          asset,
                "surprise_label": surprise_label,
                "n":              0,
                "available":      False,
            }

        def _horizon_stats(vals: list[float | None]) -> dict:
            clean = [v for v in vals if v is not None]
            if not clean:
                return {"n": 0}
            pos  = sum(1 for v in clean if v > 0)
            return {
                "n":          len(clean),
                "up_rate":    round(pos / len(clean), 3),
                "avg_return": round(statistics.mean(clean), 4),
                "median_return": round(statistics.median(clean), 4),
                "std_return": round(statistics.stdev(clean), 4) if len(clean) > 1 else 0.0,
            }

        return {
            "event_name":     event_name,
            "asset":          asset,
            "surprise_label": surprise_label,
            "n":              len(rows),
            "available":      True,
            "1h":  _horizon_stats([r.ret_1h  for r in rows]),
            "4h":  _horizon_stats([r.ret_4h  for r in rows]),
            "24h": _horizon_stats([r.ret_24h for r in rows]),
        }

    async def get_event_reactions(
        self,
        db: AsyncSession,
        event_id: int,
    ) -> list[dict]:
        rows = (await db.execute(
            select(PriceReaction).where(PriceReaction.event_id == event_id)
        )).scalars().all()
        return [_reaction_to_dict(r) for r in rows]


# ── yfinance price fetcher (synchronous — run in executor) ────────────────────

def _fetch_prices(ticker_sym: str, event_dt: datetime) -> dict[str, float | None]:
    """
    Fetch 1-min OHLCV data around event_dt and return prices at key horizons.
    Must be called in an executor (yfinance is synchronous).
    """
    try:
        pre_start  = event_dt - timedelta(minutes=10)
        post_end   = event_dt + timedelta(hours=25)

        ticker = yf.Ticker(ticker_sym)
        hist   = ticker.history(
            start=pre_start.strftime("%Y-%m-%d"),
            end=post_end.strftime("%Y-%m-%d"),
            interval="1h",
            auto_adjust=True,
        )
        if hist.empty:
            return {}

        # Make index tz-aware
        if hist.index.tz is None:
            hist.index = hist.index.tz_localize("UTC")
        else:
            hist.index = hist.index.tz_convert("UTC")

        def price_at(target: datetime) -> float | None:
            # Find nearest bar within 90 min
            delta = abs(hist.index - target)
            idx   = delta.argmin()
            if delta[idx].total_seconds() > 90 * 60:
                return None
            return float(hist["Close"].iloc[idx])

        return {
            "pre": price_at(event_dt - timedelta(minutes=5)),
            "t0":  price_at(event_dt),
            "1h":  price_at(event_dt + timedelta(hours=1)),
            "4h":  price_at(event_dt + timedelta(hours=4)),
            "24h": price_at(event_dt + timedelta(hours=24)),
        }
    except Exception as exc:
        logger.warning(f"[reaction] yfinance fetch failed for {ticker_sym}: {exc}")
        return {}


def _reaction_to_dict(r: PriceReaction) -> dict:
    return {
        "id":            r.id,
        "event_id":      r.event_id,
        "event_name":    r.event_name,
        "asset":         r.asset,
        "surprise_label": r.surprise_label,
        "price_pre":     r.price_pre,
        "price_t0":      r.price_t0,
        "price_1h":      r.price_1h,
        "price_4h":      r.price_4h,
        "price_24h":     r.price_24h,
        "ret_5min":      r.ret_5min,
        "ret_1h":        r.ret_1h,
        "ret_4h":        r.ret_4h,
        "ret_24h":       r.ret_24h,
        "direction_1h":  r.direction_1h,
        "direction_24h": r.direction_24h,
        "captured_at":   r.captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
