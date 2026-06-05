"""
Investing.com economic calendar scraper.

Fetches the public calendar HTML and parses events including forecast/consensus.
This complements FRED (which lacks forecasts) with consensus estimates.

Rate limit: max 1 request / 5 seconds. Respect robots.txt for commercial use.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from app.core.logger import get_logger

logger = get_logger(__name__)

_CALENDAR_URL = "https://www.investing.com/economic-calendar/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.investing.com/economic-calendar/",
    "Origin": "https://www.investing.com",
    "Content-Type": "application/x-www-form-urlencoded",
}

# Currencies to track — all others are discarded at parse time
_ALLOWED_CURRENCIES = {"USD", "EUR", "GBP", "CAD"}

# Importance mapping from Investing bull icons
_IMPORTANCE = {"1": "low", "2": "medium", "3": "high"}

# Categories inferred from event name keywords
_CATEGORY_MAP = [
    (["cpi", "inflation", "pce", "ppi", "rpi", "hicp"], "inflation"),
    (["nfp", "payroll", "unemployment", "jobless", "employment", "labor", "labour"], "employment"),
    (["gdp", "growth"], "gdp"),
    (["rate", "fomc", "fed", "boe", "ecb", "boj", "rba", "rbnz", "snb"], "rates"),
    (["retail", "trade", "import", "export", "balance"], "trade"),
    (["housing", "home", "building permit", "construction"], "housing"),
    (["pmi", "ism", "manufacturing", "services"], "sentiment"),
]


def _infer_category(name: str) -> str:
    low = name.lower()
    for keywords, cat in _CATEGORY_MAP:
        if any(k in low for k in keywords):
            return cat
    return "general"


def _parse_float(text: str | None) -> float | None:
    if not text or text.strip() in ("", "—", "N/A", "-"):
        return None
    text = text.strip().replace(",", "").replace("%", "").replace("K", "e3").replace("M", "e6").replace("B", "e9")
    try:
        return float(text)
    except ValueError:
        return None


class InvestingCalendarScraper:
    """
    Scrapes investing.com/economic-calendar for the current week.
    Returns a list of event dicts compatible with EconomicEvent model.

    Degrades gracefully — returns [] if scraping fails (bot detection, etc.).
    """

    async def fetch_calendar(
        self,
        lookahead_days: int = 7,
        min_importance: str = "medium",
    ) -> list[dict]:
        imp_filter = {"low": 1, "medium": 2, "high": 3}
        min_level  = imp_filter.get(min_importance, 2)

        try:
            async with httpx.AsyncClient(
                headers=_HEADERS,
                follow_redirects=True,
                timeout=20.0,
            ) as client:
                now = datetime.now(UTC)
                params = {
                    "dateFrom": now.strftime("%Y-%m-%d"),
                    "dateTo":   (now + timedelta(days=lookahead_days)).strftime("%Y-%m-%d"),
                    "timeZone": "55",   # 55 = GMT/UTC in Investing.com's internal ID system
                    "timeFilter": "timeRemain",
                    "currentTab": "custom",
                    "submitFilters": 1,
                    "limit_from": 0,
                }
                r = await client.post(
                    "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
                    data=params,
                )
                r.raise_for_status()
                html = r.json().get("data", "")
        except Exception as exc:
            logger.warning(f"[InvestingScraper] fetch failed: {exc}")
            return []

        return self._parse_html(html, min_level)

    def _parse_html(self, html: str, min_level: int) -> list[dict]:
        soup  = BeautifulSoup(html, "html.parser")
        rows  = soup.find_all("tr", class_=re.compile(r"js-event-item"))
        events: list[dict] = []
        current_date = datetime.now(UTC).date()

        for row in rows:
            try:
                # Date from parent section header
                date_attr = row.get("data-event-datetime") or ""
                if not date_attr:
                    continue
                try:
                    event_at = datetime.strptime(date_attr, "%Y/%m/%d %H:%M:%S").replace(tzinfo=UTC)
                except ValueError:
                    continue

                # Importance — count filled bull icons (multiple class-name patterns across versions)
                bull_icons = row.find_all("i", class_=re.compile(
                    r"greenBullishIcon|grayFullBullishIcon|bullish-icon-full|bull-full"
                ))
                imp_level = min(len(bull_icons), 3)

                # Fallback: try data-img_key attribute on the row's sentinel td
                if imp_level == 0:
                    sentinel = row.find("td", class_=re.compile(r"left.*event"))
                    if sentinel:
                        key = sentinel.get("data-img_key", "")
                        if "bull3" in key:
                            imp_level = 3
                        elif "bull2" in key:
                            imp_level = 2
                        elif "bull1" in key:
                            imp_level = 1

                if imp_level == 0:
                    imp_level = 1  # treat unknown as low rather than skip

                if imp_level < min_level:
                    continue

                importance = _IMPORTANCE.get(str(imp_level), "low")

                # Name and currency
                name_td   = row.find("td", class_="event")
                currency_td = row.find("td", class_="flagCur")
                if not name_td:
                    continue
                name     = name_td.get_text(strip=True)
                currency = currency_td.get_text(strip=True) if currency_td else "USD"

                if currency not in _ALLOWED_CURRENCIES:
                    continue

                # Values
                actual_td   = row.find("td", id=re.compile(r"^eventActual_"))
                forecast_td = row.find("td", id=re.compile(r"^eventForecast_"))
                previous_td = row.find("td", id=re.compile(r"^eventPrevious_"))

                actual   = _parse_float(actual_td.get_text()   if actual_td   else None)
                forecast = _parse_float(forecast_td.get_text() if forecast_td else None)
                previous = _parse_float(previous_td.get_text() if previous_td else None)

                # Country inferred from currency
                country = _CURRENCY_COUNTRY.get(currency, "Unknown")

                events.append({
                    "event_name":     name,
                    "source_id":      row.get("event_attr_id"),
                    "currency":       currency,
                    "country":        country,
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


_CURRENCY_COUNTRY = {
    "USD": "United States",
    "EUR": "Eurozone",
    "GBP": "United Kingdom",
    "CAD": "Canada",
}
