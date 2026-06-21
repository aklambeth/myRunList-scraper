"""Worthy Winchester Hash House Harriers (WWH3) scraper.

Uses The Events Calendar (Tribe Events) REST API — a single GET request that
returns fully structured event JSON.  No HTML parsing, no goo.gl resolution,
no What3Words.

See docs/WWH3.md for the full strategy document.
"""

from __future__ import annotations

import html
import json
import logging
import re
from html.parser import HTMLParser

from models.run import Location, Run
from scrapers.base import BaseScraper, FailureMode, ScraperException

log = logging.getLogger(__name__)

URL_BASE = "https://worthyh3.com"
DISPLAY_NAME = "Worthy Winchester Hash House Harriers"
MAX_RECORDS = 50


def _strip_tags(html_text: str) -> str:
    """Strip HTML tags from a string."""
    s = _TagStripper()
    s.feed(html_text)
    return s.get_text()


class _TagStripper(HTMLParser):
    """Minimal HTMLParser that collects text data and strips tags."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str):
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _is_placeholder(venue_name: str | None, postcode: str | None) -> bool:
    """Check if the venue is a placeholder (unfilled TBC event).

    Returns True when the venue name is absent or equals ``"TBC"``
    (case-insensitive) **and** there is no postcode.
    """
    if not venue_name:
        return True
    if venue_name.strip().upper() == "TBC" and not postcode:
        return True
    return False


class WWH3Scraper(BaseScraper):
    name = "wwh3"
    version = "1.0.0"
    url = f"{URL_BASE}/wp-json/tribe/events/v1/events?per_page={MAX_RECORDS}&start_date=now"

    def map(self, raw: str) -> list[dict]:
        """Parse The Events Calendar REST API JSON response into run records."""
        result = json.loads(raw)
        if not isinstance(result, dict) or "events" not in result:
            raise ScraperException(
                "TEC API response is not a JSON object with 'events' list",
                FailureMode.FATAL,
            )
        if not isinstance(result["events"], list):
            raise ScraperException(
                "TEC API 'events' field is not a list",
                FailureMode.FATAL,
            )

        records: list[dict] = []
        for event in result["events"]:
            record = self._map_event(event)
            if record is not None:
                records.append(record)

        return records

    def _map_event(self, event: dict) -> dict | None:
        """Map a single TEC event to a run record.

        Returns ``None`` for placeholders (TBC) or events with no parseable
        run number.
        """
        title = html.unescape(event.get("title", ""))

        # Extract run number from title
        m = re.search(r"\bRun\s+(\d+)", title)
        if not m:
            log.warning("wwh3: event %s has no parseable run number, skipping", event.get("id"))
            return None
        runno = int(m.group(1))

        # Date and time from start_date
        start_date = event.get("start_date", "")
        date = start_date[:10]  # YYYY-MM-DD
        time = start_date[11:16] if len(start_date) > 16 else None  # HH:MM

        # Venue
        venue = event.get("venue", {})
        venue_name = html.unescape(venue.get("venue", "")) or None
        postcode = venue.get("zip") or None

        # Skip TBC placeholders
        if _is_placeholder(venue_name, postcode):
            log.debug("wwh3: skipping placeholder record runno=%s", runno)
            return None

        # Address: join address + city, strip trailing commas
        address_parts = []
        addr_raw = venue.get("address", "") or ""
        city_raw = venue.get("city", "") or ""
        if addr_raw:
            address_parts.append(addr_raw)
        if city_raw:
            address_parts.append(city_raw)
        address_str = ", ".join(address_parts).rstrip(", ").strip() or None

        # On inn from description
        description = event.get("description", "") or ""
        oninn = None
        if description:
            text = _strip_tags(html.unescape(description)).strip()
            # Remove leading OnOn/On On label and separator
            oninn_match = re.match(
                r"(?:OnOn|On\s*On)\s*[-\u2013\u2014]\s*(.*)", text
            )
            if oninn_match:
                text = oninn_match.group(1).strip()
            if text:
                oninn = text

        # Hares from organizers list
        organizers = event.get("organizer", [])
        hares = [
            html.unescape(o["organizer"])
            for o in organizers
            if o.get("organizer")
        ]
        hares = hares or None

        # Website (use event url, the 'website' field is empty)
        website = event.get("url") or None

        # Location
        loc_fields: dict = {}
        if venue_name:
            loc_fields["name"] = venue_name
        if address_str:
            loc_fields["address"] = address_str
        if postcode:
            loc_fields["postcode"] = postcode

        # Conditionally map geo_lat/lng when both are non-null (always null
        # in current fixture, but plumbing exists for future)
        geo_lat = venue.get("geo_lat")
        geo_lng = venue.get("geo_lng")
        if geo_lat is not None and geo_lng is not None:
            try:
                loc_fields["lat"] = float(geo_lat)
                loc_fields["lng"] = float(geo_lng)
            except (TypeError, ValueError):
                pass

        # Build the record
        run = Run(
            name=DISPLAY_NAME,
            kennel=self.name,
            runno=runno,
            date=date,
            time=time,
            location=Location(**loc_fields),
            oninn=oninn,
            hares=hares,
            website=website,
        )
        return run.to_record()
