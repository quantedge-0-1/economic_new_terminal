"""
FRED provider — economic release dates + computed actual values.

API flow:
  1. /fred/release/dates?release_id=X   → release dates
  2. /fred/series/observations?series_id=X → raw values

Transforms applied per series:
  yoy   — (current - N_periods_ago) / N_periods_ago * 100
  mom   — current - previous  (level change, e.g. Payrolls in K)
  level — raw value as-is (UNRATE %, UMCSENT index, etc.)
  chg   — first difference (level change)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_BASE = "https://api.stlouisfed.org/fred"
_RELEASE_HOUR_UTC = 13   # 08:30 ET = 13:30 UTC
_RELEASE_MIN_UTC  = 30


# ── Series definitions ─────────────────────────────────────────────────────────
# (release_id, series_id, display_name, unit, importance, category, transform, yoy_periods)
# transform: "yoy" | "mom" | "level" | "chg"
# yoy_periods: how many obs back for the YoY denominator (12=monthly, 4=quarterly)

_SERIES_DEF = [
    # CPI YoY — fetch 14 months to compute YoY from index level
    (10,  "CPIAUCSL",        "US CPI YoY",              "%",     "high",   "inflation",  "yoy",   12),
    # Core PCE YoY
    (54,  "PCEPILFE",        "US Core PCE YoY",         "%",     "high",   "inflation",  "yoy",   12),
    # Nonfarm Payrolls — MoM change in K (thousands of jobs)
    (50,  "PAYEMS",          "US Nonfarm Payrolls",     "K",     "high",   "employment", "chg",    1),
    # Unemployment Rate — raw level (already %)
    (50,  "UNRATE",          "US Unemployment Rate",    "%",     "high",   "employment", "level",  0),
    # Average Hourly Earnings MoM — same NFP release (release_id=50), 1-period % change
    (50,  "AHETPI",          "US Average Hourly Earnings MoM", "%", "high", "employment", "yoy",  1),
    # Real GDP growth — annualised QoQ %, series already in % terms
    (53,  "A191RL1Q225SBEA", "US GDP Growth QoQ",       "%",     "high",   "gdp",        "level",  0),
    # Retail Sales MoM — change vs previous month
    (9,   "RSAFS",           "US Retail Sales MoM",     "%",     "medium", "trade",      "yoy",    1),
    # UMich Consumer Sentiment — index level
    (91,  "UMCSENT",         "UMich Consumer Sentiment","index", "medium", "sentiment",  "level",  0),
    # Industrial Production — index level
    (16,  "INDPRO",          "US Industrial Production","index", "medium", "gdp",        "level",  0),
    # Housing Starts — level in thousands
    (25,  "HOUST",           "US Housing Starts",       "K",     "medium", "housing",    "level",  0),
    # Trade Balance — level in billions USD (BEA monthly, release_id=46)
    (46,  "BOPGSTB",         "US Trade Balance",        "B",     "high",   "trade",      "level",  0),
    # Initial Jobless Claims — weekly, level in thousands
    (167, "ICSA",            "US Initial Jobless Claims","K",    "high",   "employment", "level",  0),
    # Continuing Claims — weekly, level in thousands (same DOL release as ICSA)
    (167, "CCSA",            "US Continuing Claims",    "K",     "medium", "employment", "level",  0),
]

# Map display_name → (series_id, transform, yoy_periods) for the actuals scanner
_NAME_TO_SERIES: dict[str, tuple[str, str, int]] = {
    name: (sid, transform, yoy_p)
    for _, sid, name, _, _, _, transform, yoy_p in _SERIES_DEF
}

# Release IDs that publish daily (FEDFUNDS H.15) — skip, too noisy
_SKIP_RELEASE_IDS: set[int] = {18}


class FREDProvider:
    def __init__(self, api_key: str | None = None):
        self._key = api_key or settings.fred_api_key

    async def fetch_releases(
        self,
        lookback_days: int = 45,
        lookahead_days: int = 30,
    ) -> list[dict]:
        if not self._key:
            logger.warning("[FRED] No API key — calendar will be empty")
            return []

        now   = datetime.now(UTC)
        start = now - timedelta(days=lookback_days)
        end   = now + timedelta(days=lookahead_days)

        sem = asyncio.Semaphore(3)  # FRED free tier: ~12 req/min — cap concurrency

        async def _bounded(coro):
            async with sem:
                return await coro

        async with httpx.AsyncClient(timeout=25.0) as client:
            tasks = [
                _bounded(self._fetch_one(client, rel_id, sid, name, unit, imp, cat, transform, yoy_p, start, end))
                for rel_id, sid, name, unit, imp, cat, transform, yoy_p in _SERIES_DEF
                if rel_id not in _SKIP_RELEASE_IDS
            ]
            batches = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[dict] = []
        for b in batches:
            if isinstance(b, list):
                results.extend(b)
            elif isinstance(b, Exception):
                logger.warning("[FRED] batch error: %s", b)

        logger.info("[FRED] fetched %d events", len(results))
        return results

    # ── Core fetch ─────────────────────────────────────────────────────────────

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        release_id: int,
        series_id: str,
        name: str,
        unit: str,
        importance: str,
        category: str,
        transform: str,
        yoy_periods: int,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        start_s = start.strftime("%Y-%m-%d")
        end_s   = end.strftime("%Y-%m-%d")

        # 1. Release dates
        try:
            r = await client.get(
                f"{_BASE}/release/dates",
                params={
                    "release_id":  release_id,
                    "api_key":     self._key,
                    "file_type":   "json",
                    "realtime_start": start_s,
                    "realtime_end":   end_s,
                    "sort_order":  "asc",
                    "limit":       60,
                    "include_release_dates_with_no_data": "true",
                },
            )
            r.raise_for_status()
            release_dates = [rd["date"] for rd in r.json().get("release_dates", []) if rd.get("date")]
        except Exception as exc:
            logger.warning("[FRED] release %d dates: %s", release_id, exc)
            return []

        if not release_dates:
            return []

        # 2. Observations — fetch extra periods for YoY/ChG calculation
        extra_days = max(yoy_periods * 35, 60)   # ~35 days per period
        obs_start  = (start - timedelta(days=extra_days)).strftime("%Y-%m-%d")
        try:
            obs_r = await client.get(
                f"{_BASE}/series/observations",
                params={
                    "series_id":         series_id,
                    "api_key":           self._key,
                    "file_type":         "json",
                    "observation_start": obs_start,
                    "observation_end":   end_s,
                    "sort_order":        "asc",
                    "limit":             120,
                },
            )
            obs_r.raise_for_status()
            raw_obs = obs_r.json().get("observations", [])
        except Exception as exc:
            logger.warning("[FRED] %s observations: %s", series_id, exc)
            raw_obs = []

        # Parse observations into {date: float}
        obs_map: dict[str, float] = {}
        obs_dates: list[str] = []
        for o in raw_obs:
            v = _parse_val(o.get("value"))
            if v is not None:
                obs_map[o["date"]] = v
                obs_dates.append(o["date"])

        # 3. Build events
        events: list[dict] = []
        for rel_date in release_dates:
            event_at = _to_utc_datetime(rel_date)

            # Find the observation whose reference period is closest to (and on/before) this release date
            matching_date = _latest_obs_before(obs_dates, rel_date)
            actual_raw    = obs_map.get(matching_date) if matching_date else None

            # Compute transformed actual value and "previous"
            actual, previous = _apply_transform(
                transform, yoy_periods, obs_dates, obs_map, matching_date, actual_raw
            )

            is_future = event_at > datetime.now(UTC)
            # For future releases the matched observation is the previous period's
            # data, not the upcoming release — clear it to avoid false actuals
            if is_future:
                actual   = None
                previous = None

            status = "pending" if is_future or actual is None else "released"

            events.append({
                "event_name":     name,
                "source_id":      series_id,
                "currency":       "USD",
                "country":        "United States",
                "category":       category,
                "importance":     importance,
                "event_at":       event_at,
                "actual":         actual,
                "forecast":       None,
                "previous":       previous,
                "unit":           unit,
                "status":         status,
                "is_high_impact": importance == "high",
            })

        return events

    async def fetch_actuals_for_event(
        self, series_id: str, transform: str, yoy_periods: int
    ) -> float | None:
        """
        Directly fetch and compute the most recent actual value for a series.
        Used by the actuals scanner to fill past-pending events without the
        release_dates intermediary (bypasses the timing / rate-limit failure modes).
        """
        if not self._key:
            return None

        needed = max(yoy_periods + 2, 3)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                obs_r = await client.get(
                    f"{_BASE}/series/observations",
                    params={
                        "series_id":  series_id,
                        "api_key":    self._key,
                        "file_type":  "json",
                        "sort_order": "desc",
                        "limit":      needed + 3,
                    },
                )
                obs_r.raise_for_status()
                raw_obs = obs_r.json().get("observations", [])
        except Exception as exc:
            logger.warning("[FRED] direct fetch %s: %s", series_id, exc)
            return None

        obs_map: dict[str, float] = {}
        obs_dates: list[str] = []
        for o in reversed(raw_obs):  # reverse desc→asc for transform helpers
            v = _parse_val(o.get("value"))
            if v is not None:
                obs_map[o["date"]] = v
                obs_dates.append(o["date"])

        if not obs_dates:
            return None

        current_date = obs_dates[-1]
        current_raw  = obs_map[current_date]

        actual, _ = _apply_transform(transform, yoy_periods, obs_dates, obs_map, current_date, current_raw)
        return actual

    async def fetch_latest_value(self, series_id: str) -> float | None:
        if not self._key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{_BASE}/series/observations",
                    params={"series_id": series_id, "api_key": self._key,
                            "file_type": "json", "sort_order": "desc", "limit": 1},
                )
                r.raise_for_status()
                obs = r.json().get("observations", [{}])[0]
                return _parse_val(obs.get("value", "."))
        except Exception as exc:
            logger.warning("[FRED] latest %s: %s", series_id, exc)
            return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_val(raw) -> float | None:
    if raw in (".", "", None):
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def _to_utc_datetime(date_str: str) -> datetime:
    y, m, d = (int(p) for p in date_str.split("-"))
    return datetime(y, m, d, _RELEASE_HOUR_UTC, _RELEASE_MIN_UTC, tzinfo=UTC)


def _latest_obs_before(obs_dates: list[str], cutoff: str) -> str | None:
    """Most recent observation date on or before cutoff."""
    eligible = [d for d in obs_dates if d <= cutoff]
    return eligible[-1] if eligible else None


def _nth_obs_before(obs_dates: list[str], current_date: str, n: int) -> str | None:
    """Observation date that is n periods before current_date in the obs_dates list."""
    try:
        idx = obs_dates.index(current_date)
        target_idx = idx - n
        return obs_dates[target_idx] if target_idx >= 0 else None
    except ValueError:
        return None


def _apply_transform(
    transform: str,
    periods: int,
    obs_dates: list[str],
    obs_map: dict[str, float],
    current_date: str | None,
    current_raw: float | None,
) -> tuple[float | None, float | None]:
    """
    Returns (actual_transformed, previous_transformed) for the given release.
    """
    if current_date is None or current_raw is None:
        return None, None

    if transform == "level":
        # Return raw value and the previous obs as "previous"
        prev_date = _nth_obs_before(obs_dates, current_date, 1)
        previous  = obs_map.get(prev_date) if prev_date else None
        return round(current_raw, 3), (round(previous, 3) if previous is not None else None)

    if transform == "yoy":
        # YoY % change: (current - N_periods_ago) / |N_periods_ago| * 100
        base_date = _nth_obs_before(obs_dates, current_date, periods)
        base_val  = obs_map.get(base_date) if base_date else None
        if base_val is None or base_val == 0:
            return None, None
        actual = round((current_raw - base_val) / abs(base_val) * 100, 2)

        # "previous" = YoY for the prior period
        prev_curr_date = _nth_obs_before(obs_dates, current_date, 1)
        prev_curr_raw  = obs_map.get(prev_curr_date) if prev_curr_date else None
        prev_base_date = _nth_obs_before(obs_dates, current_date, periods + 1)
        prev_base_raw  = obs_map.get(prev_base_date) if prev_base_date else None
        previous = None
        if prev_curr_raw is not None and prev_base_raw and prev_base_raw != 0:
            previous = round((prev_curr_raw - prev_base_raw) / abs(prev_base_raw) * 100, 2)

        return actual, previous

    if transform == "chg":
        # First difference (e.g. Payrolls: jobs added = current - previous month)
        prev_date = _nth_obs_before(obs_dates, current_date, 1)
        prev_raw  = obs_map.get(prev_date) if prev_date else None
        if prev_raw is None:
            return None, None
        actual   = round(current_raw - prev_raw, 1)

        # "previous" = prior period change
        prev2_date = _nth_obs_before(obs_dates, current_date, 2)
        prev2_raw  = obs_map.get(prev2_date) if prev2_date else None
        previous   = None
        if prev2_raw is not None:
            previous = round(prev_raw - prev2_raw, 1)

        return actual, previous

    return current_raw, None
