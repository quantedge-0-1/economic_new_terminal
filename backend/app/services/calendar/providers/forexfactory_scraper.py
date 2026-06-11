"""
ForexFactory economic calendar scraper.
Replaces Investing.com (blocked by bot detection since June 2026).

ForexFactory is widely used by retail/institutional traders and is more
resilient to scraping than Investing.com's JSON API endpoint.

Times are Eastern Time (ET) — converted to UTC before storage.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from app.core.logger import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://www.forexfactory.com/calendar"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "DNT": "1",
}

_ALLOWED_CURRENCIES = {"USD", "EUR", "GBP", "CAD"}

_CURRENCY_COUNTRY = {
    "USD": "United States",
    "EUR": "Eurozone",
    "GBP": "United Kingdom",
    "CAD": "Canada",
}

_CATEGORY_MAP = [
    (["cpi", "inflation", "pce", "ppi", "rpi", "hicp"], "inflation"),
    (["nfp", "payroll", "unemployment", "jobless", "employment", "labor", "labour", "adp"], "employment"),
    (["gdp", "growth"], "gdp"),
    (["rate", "fomc", "fed", "boe", "ecb", "boj", "rba", "rbnz", "snb", "interest"], "rates"),
    (["retail", "trade balance", "import", "export", "current account"], "trade"),
    (["housing", "home sales", "building permit", "construction permit", "permit"], "housing"),
    (["pmi", "ism", "manufacturing", "services", "composite", "sentiment", "confidence"], "sentiment"),
]


def _infer_category(name: str) -> str:
    low = name.lower()
    for keywords, cat in _CATEGORY_MAP:
        if any(k in low for k in keywords):
            return cat
    return "general"


def _parse_float(text: str | None) -> float | None:
    """
    Parse a numeric string, stripping unit suffixes (K/M/B/T) WITHOUT multiplying.
    Stores the coefficient: "29K" → 29.0, "-55.9B" → -55.9, "2.4%" → 2.4.
    This matches FRED's convention (e.g., Payrolls in K, Trade Balance in B).
    """
    if not text or text.strip() in ("", "—", "N/A", "-", "...", "Tentative"):
        return None
    # Normalize: strip whitespace, commas, percent; replace Unicode minus (U+2212) with hyphen
    t = text.strip().replace(",", "").replace("%", "").replace("−", "-")
    # Strip trailing unit suffix — keep the numeric coefficient
    if t and t[-1].upper() in "KMBT":
        t = t[:-1]
    try:
        return float(t)
    except ValueError:
        return None


def _et_offset(dt: datetime) -> timezone:
    """UTC offset for Eastern Time on the given date (DST-aware, no external deps)."""
    year = dt.year
    # EDT (UTC-4): second Sunday of March → first Sunday of November
    march1 = datetime(year, 3, 1)
    dst_start = march1 + timedelta(days=(6 - march1.weekday()) % 7 + 7)
    nov1 = datetime(year, 11, 1)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    if dst_start.date() <= dt.date() < dst_end.date():
        return timezone(timedelta(hours=-4))  # EDT
    return timezone(timedelta(hours=-5))      # EST


class ForexFactoryCalendarScraper:
    """
    Scrapes forexfactory.com for current and surrounding weeks.
    Returns event dicts compatible with EconomicEvent model.
    Degrades gracefully — returns [] on any failure.
    """

    async def fetch_calendar(
        self,
        lookahead_days: int = 7,
        min_importance: str = "medium",
    ) -> list[dict]:
        imp_filter = {"low": 1, "medium": 2, "high": 3}
        min_level = imp_filter.get(min_importance, 2)

        all_events: list[dict] = []

        try:
            async with httpx.AsyncClient(
                headers=_HEADERS,
                follow_redirects=True,
                timeout=25.0,
            ) as client:
                # Always fetch last week (recent actuals) + this week
                for week in ("last", "this"):
                    events = await self._fetch_week(client, week, min_level)
                    all_events.extend(events)

                # Fetch next week only when lookahead warrants it
                if lookahead_days > 4:
                    events = await self._fetch_week(client, "next", min_level)
                    all_events.extend(events)

        except Exception as exc:
            logger.warning("[ForexFactory] fetch failed: %s", exc)
            return []

        # Filter to the relevant date window
        now = datetime.now(UTC)
        since = now - timedelta(days=7)
        cutoff = now + timedelta(days=lookahead_days)
        filtered = [e for e in all_events if since <= e["event_at"] <= cutoff]

        logger.info("[ForexFactory] %d events in date window", len(filtered))
        return filtered

    async def _fetch_week(
        self, client: httpx.AsyncClient, week: str, min_level: int
    ) -> list[dict]:
        try:
            r = await client.get(_BASE_URL, params={"week": week})
            r.raise_for_status()
            events = self._parse_html(r.text, min_level)
            logger.debug("[ForexFactory] week=%s → %d events", week, len(events))
            return events
        except Exception as exc:
            logger.warning("[ForexFactory] week=%s failed: %s", week, exc)
            return []

    def _parse_html(self, html: str, min_level: int) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        # ForexFactory wraps the calendar in a table with class "calendar__table"
        table = soup.find("table", class_=re.compile(r"calendar__table"))
        if not table:
            logger.warning("[ForexFactory] calendar__table not found — HTML structure may have changed")
            return []

        events: list[dict] = []
        current_date: datetime | None = None
        current_year = datetime.now(UTC).year
        last_time_str = "8:30am"  # carried forward when a row shares the previous event's time

        for row in table.find_all("tr"):
            try:
                # Date cell — only on the first row of a new calendar day
                date_td = row.find("td", class_=re.compile(r"calendar__date"))
                if date_td:
                    raw = date_td.get_text(separator=" ", strip=True)
                    parsed = self._parse_date(raw, current_year)
                    if parsed:
                        current_date = parsed

                if current_date is None:
                    continue

                # Time — carry forward when cell is blank (same-time block)
                time_td = row.find("td", class_=re.compile(r"calendar__time"))
                time_text = time_td.get_text(strip=True) if time_td else ""
                if time_text and time_text.lower() not in ("all day", "tentative", ""):
                    last_time_str = time_text
                effective_time = last_time_str if not time_text else time_text

                # Currency
                cur_td = row.find("td", class_=re.compile(r"calendar__currency"))
                currency = cur_td.get_text(strip=True) if cur_td else ""
                if currency not in _ALLOWED_CURRENCIES:
                    continue

                # Impact
                imp_td = row.find("td", class_=re.compile(r"calendar__impact"))
                imp_level = self._parse_impact(imp_td)
                if imp_level < min_level:
                    continue

                importance = {1: "low", 2: "medium", 3: "high"}.get(imp_level, "low")

                # Event name — strip any trailing detail span text
                ev_td = row.find("td", class_=re.compile(r"calendar__event"))
                if not ev_td:
                    continue
                # Remove child spans that carry sub-detail (e.g. "m/m", "q/q" qualifiers)
                for span in ev_td.find_all("span", class_=re.compile(r"detail")):
                    span.decompose()
                name = ev_td.get_text(strip=True)
                if not name:
                    continue

                # Values
                actual_td   = row.find("td", class_=re.compile(r"calendar__actual"))
                forecast_td = row.find("td", class_=re.compile(r"calendar__forecast"))
                prev_td     = row.find("td", class_=re.compile(r"calendar__previous"))

                actual   = _parse_float(actual_td.get_text()   if actual_td   else None)
                forecast = _parse_float(forecast_td.get_text() if forecast_td else None)
                previous = _parse_float(prev_td.get_text()     if prev_td     else None)

                event_at = self._build_event_at(current_date, effective_time)

                events.append({
                    "event_name":     name,
                    "source_id":      None,
                    "currency":       currency,
                    "country":        _CURRENCY_COUNTRY.get(currency, "Unknown"),
                    "category":       _infer_category(name),
                    "importance":     importance,
                    "event_at":       event_at,
                    "actual":         actual,
                    "forecast":       forecast,
                    "previous":       previous,
                    "unit":           None,
                    "status":         "released" if actual is not None else "pending",
                    "is_high_impact": importance == "high",
                })
            except Exception:
                continue

        return events

    def _parse_impact(self, td) -> int:
        if td is None:
            return 0
        # FF marks impact with span class icons: icon--ff-impact-red (high), -ora (medium), -yel/-gra (low)
        for el in td.find_all(True):
            classes = " ".join(el.get("class", []))
            if "impact-red" in classes:
                return 3
            if "impact-ora" in classes:
                return 2
            if "impact-yel" in classes or "impact-gra" in classes:
                return 1
        # Fallback: title attribute
        title = td.get("title", "").lower()
        if "high" in title:
            return 3
        if "medium" in title or "moderate" in title:
            return 2
        if "low" in title:
            return 1
        return 0

    def _parse_date(self, text: str, year: int) -> datetime | None:
        """
        Parse ForexFactory date cells like 'Mon Jun 9', 'Tue Jun 10', etc.
        Falls back to dateutil for unusual formats.
        """
        text = re.sub(r"\s+", " ", text).strip()
        # Strip leading weekday abbreviation
        text = re.sub(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*", "", text, flags=re.IGNORECASE)

        for fmt in ("%b %d %Y", "%b %d", "%B %d %Y", "%B %d"):
            try:
                candidate = text if "%Y" in fmt else f"{text} {year}"
                fmt_used  = fmt if "%Y" in fmt else f"{fmt} %Y"
                d = datetime.strptime(candidate, fmt_used)
                # Advance year if the date is more than 6 months in the past
                now_naive = datetime.now(UTC).replace(tzinfo=None)
                if (d - now_naive).days < -180:
                    d = d.replace(year=year + 1)
                return d
            except ValueError:
                continue

        # Last resort: dateutil
        try:
            d = dateutil_parser.parse(text, default=datetime(year, 1, 1))
            return d.replace(tzinfo=None)
        except Exception:
            return None

    def _build_event_at(self, base_date: datetime, time_str: str) -> datetime:
        """Convert an ET time string (e.g. '8:30am') + base date to UTC datetime."""
        clean = time_str.lower().strip()
        # Python's strptime %I already accepts 1- or 2-digit hours without padding
        for fmt in ("%I:%M%p", "%I%p"):
            try:
                t = datetime.strptime(clean, fmt)
                naive = base_date.replace(
                    hour=t.hour, minute=t.minute, second=0, microsecond=0
                )
                return naive.replace(tzinfo=_et_offset(naive)).astimezone(UTC)
            except ValueError:
                continue

        # Default: 08:30 ET (most US releases — BLS, BEA, Census standard release time)
        naive = base_date.replace(hour=8, minute=30, second=0, microsecond=0)
        return naive.replace(tzinfo=_et_offset(naive)).astimezone(UTC)
