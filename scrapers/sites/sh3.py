"""Surrey Hash House Harriers (SH3) scraper.

Uses the WordPress REST API to fetch trail pages in a single request.
Each page's ``content.rendered`` holds the complete Elementor-rendered
detail page, so no per-trail fetches are needed.

See docs/SH3.md for the full strategy document.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from models.run import Location, Run, W3S_PATTERN
from scrapers.base import BaseScraper, FailureMode, ScraperException
from scrapers.geo import (
    expand_gmaps_short_url,
    expand_gmaps_short_urls_parallel,
    parse_latlng_from_gmaps_url,
)

log = logging.getLogger(__name__)

URL_BASE = "https://surreyhashhouseharriers.com"
DISPLAY_NAME = "Surrey Hash House Harriers"
MAX_RECORDS = 50


def _parse_trail_no(trail_no_text: str, publish_date: str) -> tuple[int, str]:
    """Parse runno and date from the 'Trail no' content value.

    The value is ``"<runno>, <date>"`` where date is usually ``DD Month YYYY``
    but may omit the year (e.g. ``19 July``).  When the year is missing it
    is inferred from the page's WordPress ``date`` (publish) field.

    Returns ``(runno, iso_date)``.
    """
    parts = trail_no_text.split(", ", 1)
    runno = int(parts[0])
    date_str = parts[1].strip()

    # Try with year first
    try:
        dt = datetime.strptime(date_str, "%d %B %Y")
        return runno, dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    # No year — try %d %B and infer from publish date
    try:
        dt_no_year = datetime.strptime(date_str, "%d %B")
    except ValueError:
        raise ScraperException(
            f"unparseable date in trail no value {trail_no_text!r}",
            FailureMode.TRANSIENT,
        )

    pub_dt = datetime.fromisoformat(publish_date[:10])
    pub_year = pub_dt.year

    # Build the run date with the publish year
    run_dt = pub_dt.replace(year=pub_year, month=dt_no_year.month, day=dt_no_year.day)

    # If the run date is more than 2 weeks *before* the publish date,
    # it's a year-end wrap (e.g. a January run published in December).
    diff_days = (run_dt - pub_dt).days
    if diff_days < -14:
        run_dt = run_dt.replace(year=pub_year + 1)

    return runno, run_dt.strftime("%Y-%m-%d")


def _parse_hares(hares_text: str) -> list[str] | None:
    """Split hare names on any of ``&``, ``/``, or ``,``."""
    if not hares_text:
        return None
    names = re.split(r"\s*[&/,]\s*", hares_text)
    cleaned = [n.strip() for n in names if n.strip()]
    return cleaned or None


def _extract_postcode(from_value: str) -> tuple[str | None, str | None]:
    """Extract postcode and location name from the 'From' value.

    Returns ``(location_name, postcode)``.
    """
    pc_match = re.search(
        r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\s*$", from_value
    )
    if pc_match:
        postcode = pc_match.group(1)
        location_name = from_value[: pc_match.start()].strip().rstrip(",")
        return location_name or None, postcode
    return None, None


def _is_placeholder(from_value: str) -> bool:
    """Check if the 'From' value is a placeholder (unfilled template).

    A placeholder has no valid UK postcode AND contains the ``x, x, x``
    template pattern.
    """
    pc_match = re.search(
        r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\s*$", from_value
    )
    return (not pc_match) and ("x, x, x" in from_value)


def _extract_w3s(buttons: list[tuple[str, str]]) -> str | None:
    """Extract What3Words slug from button links."""
    for text, href in buttons:
        if text == "What3Words" and "w3w.co/" in href:
            slug = href.split("w3w.co/")[-1].strip("/")
            if re.match(W3S_PATTERN, slug):
                return slug
    return None


def _extract_map_link(buttons: list[tuple[str, str]], url_expander=expand_gmaps_short_url) -> dict:
    """Extract lat/lng from the 'Map link to Start' button."""
    for text, href in buttons:
        if text == "Map link to Start" and "maps.app.goo.gl" in href:
            expanded = url_expander(href)
            if expanded:
                lat, lng = parse_latlng_from_gmaps_url(expanded)
                if lat is not None:
                    return {"lat": lat, "lng": lng}
    return {}


def _extract_oninn_first_line(text_editor_text: str) -> str | None:
    """Extract the 'On on' value, taking the first non-empty line.

    Omits if it's a placeholder.
    """
    lines = text_editor_text.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped:
            # Check for placeholder pattern
            if "x, x, x" in stripped:
                return None
            pc_match = re.search(
                r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\s*$", stripped
            )
            if pc_match:
                return stripped
            return stripped
    return None


class SH3Scraper(BaseScraper):
    name = "sh3"
    version = "1.0.0"
    url = f"{URL_BASE}/wp-json/wp/v2/pages?search=trail&orderby=date&order=desc&per_page={MAX_RECORDS}"

    def map(self, raw: str) -> list[dict]:
        """Parse WordPress REST API JSON response into run records."""
        pages = json.loads(raw)
        if not isinstance(pages, list):
            raise ScraperException(
                "wp-json response is not a JSON array", FailureMode.FATAL
            )

        # Filter to trail pages only (skip rs* run-report pages)
        trail_pages = [p for p in pages if re.match(r"^trail-\d+-", p.get("slug", ""))]

        if not trail_pages:
            raise ScraperException(
                "no trail-* pages found in response", FailureMode.FATAL
            )

        # Collect all gmaps short URLs across all trail pages and expand in parallel
        all_short_urls: list[str] = []
        for page in trail_pages:
            soup = BeautifulSoup(page.get("content", {}).get("rendered", ""), "html.parser")
            for a in soup.find_all("a", href=True):
                if a.get_text(strip=True) == "Map link to Start" and "maps.app.goo.gl" in a["href"]:
                    all_short_urls.append(a["href"])

        expanded_cache = expand_gmaps_short_urls_parallel(all_short_urls)

        def cached_expander(url: str) -> str | None:
            return expanded_cache.get(url) or expand_gmaps_short_url(url)

        records: list[dict] = []
        for page in trail_pages:
            record = self._map_trail(page, url_expander=cached_expander)
            if record is not None:
                records.append(record)

        return records

    def _map_trail(self, page: dict, url_expander=expand_gmaps_short_url) -> dict | None:
        """Map a single WordPress page to a run record."""
        content_html = page.get("content", {}).get("rendered", "")
        publish_date = page.get("date", "")
        page_link = page.get("link", "")

        soup = BeautifulSoup(content_html, "html.parser")

        # Find all heading and text-editor widgets.
        # In Elementor, heading labels and text-editor values are stored
        # as SEPARATE widgets.  The heading widgets have the class
        # ``elementor-widget-heading`` and the text-editor widgets have
        # the class ``elementor-widget-text-editor``.
        #
        # Within a trail page the headings and text-editors are in the
        # same order, so we can match them by index:
        #   heading[1] = "Trail no"  -> text_editor[0] = "2631, 28 June 2026"
        #   heading[2] = "Hare(s)"  -> text_editor[1] = "Eskimo Nell ..."
        #   heading[3] = "From"     -> text_editor[2] = "St Martins ..."
        #   heading[4] = "On on"    -> text_editor[3] = "TBD (so many..."

        headings = soup.find_all("div", class_="elementor-widget-heading")
        text_editors = soup.find_all("div", class_="elementor-widget-text-editor")

        # Extract heading labels (strip trailing colon and "Run details" / "Directions/details")
        heading_labels = []
        for h in headings:
            htag = h.find(["h2", "h3", "h4", "h5"])
            if htag:
                label = htag.get_text(strip=True).rstrip(":")
                if label not in ("Run details", "Directions/details"):
                    heading_labels.append(label)

        # Extract text-editor values
        text_editor_values = [te.get_text(strip=True) for te in text_editors]

        # Build label -> value mapping by matching by index
        label_to_value: dict[str, str] = {}
        for i, label in enumerate(heading_labels):
            if i < len(text_editor_values):
                label_to_value[label] = text_editor_values[i]

        # Parse "Trail no"
        trail_no_text = label_to_value.get("Trail no", "")
        if not trail_no_text:
            log.warning("sh3: page %s missing 'Trail no', skipping", page.get("slug"))
            return None

        try:
            runno, iso_date = _parse_trail_no(trail_no_text, publish_date)
        except ScraperException:
            log.warning("sh3: page %s has unparseable date, skipping", page.get("slug"))
            return None

        # Parse "Hare(s)"
        hares_text = label_to_value.get("Hare(s)", "")
        hares = _parse_hares(hares_text)

        # Parse "From" - check for placeholder
        from_value = label_to_value.get("From", "")
        if _is_placeholder(from_value):
            log.debug("sh3: skipping placeholder record runno=%s", runno)
            return None

        location_name, postcode = _extract_postcode(from_value)

        # Parse buttons for map link and W3W
        buttons = []
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            if text in ("Map link to Start", "What3Words"):
                buttons.append((text, href))

        # Extract coordinates
        coords = _extract_map_link(buttons, url_expander=url_expander)

        # Extract W3S
        w3s = _extract_w3s(buttons)

        # Build location
        loc_fields: dict = {}
        if location_name:
            loc_fields["name"] = location_name
        if postcode:
            loc_fields["postcode"] = postcode
        if coords:
            loc_fields.update(coords)
        if w3s:
            loc_fields["w3s"] = w3s

        # Parse "On on" - take first non-empty line
        oninn_text = label_to_value.get("On on", "")
        oninn = _extract_oninn_first_line(oninn_text)

        # Build the record
        run = Run(
            name=DISPLAY_NAME,
            kennel=self.name,
            runno=runno,
            date=iso_date,
            location=Location(**loc_fields),
            hares=hares,
            oninn=oninn,
            website=page_link or None,
        )
        return run.to_record()
