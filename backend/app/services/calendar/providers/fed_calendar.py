"""
Federal Reserve FOMC calendar provider.

Scrapes federalreserve.gov/monetarypolicy/fomccalendars.htm directly.
No API key required — official government website with no bot protection.

FOMC decisions are announced at 2:00 PM ET on the last day of each meeting.
Press conferences follow immediately at 2:30 PM ET (all meetings since 2024).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from app.core.logger import get_logger

logger = get_logger(__name__)

_FED_URL  = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_HEADERS  = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/136.0.0.0"}

# FOMC decision: 2:00 PM ET; press conference: 2:30 PM ET
_DECISION_HOUR_ET = 14
_DECISION_MIN_ET  = 0
_PC_HOUR_ET       = 14
_PC_MIN_ET        = 30

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _et_offset(dt: datetime) -> timezone:
    """DST-aware Eastern Time offset for the given date."""
    y = dt.year
    march1    = datetime(y, 3, 1)
    dst_start = march1 + timedelta(days=(6 - march1.weekday()) % 7 + 7)
    nov1      = datetime(y, 11, 1)
    dst_end   = nov1   + timedelta(days=(6 - nov1.weekday()) % 7)
    if dst_start.date() <= dt.date() < dst_end.date():
        return timezone(timedelta(hours=-4))   # EDT
    return timezone(timedelta(hours=-5))       # EST


def _to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    naive = datetime(year, month, day, hour, minute)
    return naive.replace(tzinfo=_et_offset(naive)).astimezone(UTC)


class FedCalendarProvider:
    """
    Parses FOMC meeting dates from the Federal Reserve website.
    Returns rate decision + press conference events for current and future meetings.
    Degrades gracefully on any network or parse failure.
    """

    async def fetch_calendar(
        self,
        lookahead_days: int = 90,
    ) -> list[dict]:
        try:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=15.0) as client:
                r = await client.get(_FED_URL)
                r.raise_for_status()
                html = r.text
        except Exception as exc:
            logger.warning("[Fed] fetch failed: %s", exc)
            return []

        try:
            events = _parse_fomc_dates(html, lookahead_days)
        except Exception as exc:
            logger.warning("[Fed] parse failed: %s", exc)
            return []

        logger.info("[Fed] %d FOMC events parsed", len(events))
        return events


def _parse_fomc_dates(html: str, lookahead_days: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    now  = datetime.now(UTC)

    # Look-back: show FOMC from 30 days ago (so recent releases are visible)
    since  = now - timedelta(days=30)
    cutoff = now + timedelta(days=lookahead_days)

    events: list[dict] = []

    # Each year is in a <div class="panel ..."> with an <h4> heading like "2026 FOMC Meetings"
    for panel in soup.find_all("div", class_=re.compile(r"panel")):
        heading = panel.find("h4")
        if not heading:
            continue
        year_match = re.search(r"(\d{4})\s+FOMC", heading.get_text())
        if not year_match:
            continue
        year = int(year_match.group(1))

        # Each meeting is a <div class="row"> or <table row> with a date range
        text = panel.get_text(separator=" ")
        # Pattern: "January 27-28" or "June 16-17*"
        date_pattern = re.compile(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(\d{1,2})-(\d{1,2})\*?",
            re.IGNORECASE,
        )

        for m in date_pattern.finditer(text):
            month_name = m.group(1).lower()
            month      = _MONTHS.get(month_name)
            if not month:
                continue
            decision_day = int(m.group(3))   # last day of meeting = decision day

            try:
                decision_at = _to_utc(year, month, decision_day, _DECISION_HOUR_ET, _DECISION_MIN_ET)
                pc_at       = _to_utc(year, month, decision_day, _PC_HOUR_ET, _PC_MIN_ET)
            except ValueError:
                continue

            if decision_at < since or decision_at > cutoff:
                continue

            is_future = decision_at > now
            status    = "pending" if is_future else "released"

            # Rate decision event
            events.append({
                "event_name":     "FOMC Rate Decision",
                "source_id":      "FED_FOMC",
                "currency":       "USD",
                "country":        "United States",
                "category":       "rates",
                "importance":     "high",
                "event_at":       decision_at,
                "actual":         None,
                "forecast":       None,
                "previous":       None,
                "unit":           "%",
                "status":         status,
                "is_high_impact": True,
            })

            # Press conference (30 min later) — also high impact
            events.append({
                "event_name":     "FOMC Press Conference",
                "source_id":      "FED_FOMC_PC",
                "currency":       "USD",
                "country":        "United States",
                "category":       "rates",
                "importance":     "high",
                "event_at":       pc_at,
                "actual":         None,
                "forecast":       None,
                "previous":       None,
                "unit":           None,
                "status":         status,
                "is_high_impact": True,
            })

    return events
