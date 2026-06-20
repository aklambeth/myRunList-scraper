"""Guildford Hash House Harriers scraper. See docs/GH3.md.

The homepage is server-rendered (EventOn). Each event card is a
``div.eventon_list_event`` containing an inline JSON-LD ``Event`` block (date,
url, description) and a DOM title span (run number, hare, location, postcode).
Non-run titles (no 4-digit prefix) are silently skipped.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from models.run import W3S_PATTERN, Location, Run
from scrapers.base import BaseScraper, FailureMode, ScraperException
from scrapers.geo import expand_gmaps_short_url, parse_latlng_from_gmaps_url

log = logging.getLogger(__name__)

URL = "https://guildfordh3.org.uk"
DISPLAY_NAME = "Guildford Hash House Harriers"


def normalise_gh3_datetime(s: str) -> datetime:
    s = re.sub(
        r"(\d{4})-(\d{1,2})-(\d{1,2})",
        lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}",
        s,
    )
    s = re.sub(r"([+-])(\d):", r"\g<1>0\2:", s)
    return datetime.fromisoformat(s)


def parse_title(title: str) -> dict | None:
    """Return parsed run fields, or None for non-run (special) events."""
    title = title.strip()
    m = re.match(r"^(\d{4})\s+-\s+(.+)$", title)
    if not m:
        return None
    result: dict = {"runno": int(m.group(1))}
    remainder = m.group(2)
    parts = remainder.split(" - ", maxsplit=1)
    hare_str = parts[0].strip()
    result["hares"] = [h.strip() for h in hare_str.split("/") if h.strip()]
    if len(parts) > 1:
        loc = parts[1].strip()
        pc_match = re.search(r"\(([A-Z]{1,2}\d{1,2}\s*\d[A-Z]{2})\)\s*$", loc)
        if pc_match:
            result["postcode"] = pc_match.group(1)
            loc = loc[: pc_match.start()].strip()
        if loc:
            result["location_name"] = loc
    return result


def parse_w3s(description_html: str | None) -> str | None:
    if not description_html:
        return None
    soup = BeautifulSoup(description_html, "html.parser")
    for a in soup.find_all("a", href=True):
        if "w3w.co/" in a["href"]:
            slug = a["href"].split("w3w.co/")[-1].strip("/")
            if re.match(W3S_PATTERN, slug):
                return slug
    return None


def parse_latlng(description_html: str | None, url_expander=expand_gmaps_short_url):
    if not description_html:
        return None, None
    soup = BeautifulSoup(description_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "waze.com" in href and "ll=" in href:
            ll = parse_qs(urlparse(href).query).get("ll", [None])[0]
            if ll:
                parts = unquote(ll).split(",")
                if len(parts) == 2:
                    try:
                        return float(parts[0]), float(parts[1])
                    except ValueError:
                        pass
    for a in soup.find_all("a", href=True):
        if "maps.app.goo.gl" in a["href"]:
            expanded = url_expander(a["href"])
            if expanded:
                lat, lng = parse_latlng_from_gmaps_url(expanded)
                if lat is not None:
                    return lat, lng
    return None, None


class GH3Scraper(BaseScraper):
    name = "gh3"
    version = "1.0.0"
    url = URL

    def map(self, raw: str) -> list[dict]:
        soup = BeautifulSoup(raw, "html.parser")
        events = soup.select("div.eventon_list_event")
        if not events:
            raise ScraperException(
                "no eventon_list_event divs found", FailureMode.FATAL
            )

        records: list[dict] = []
        found_event_ld = False
        for div in events:
            ld = self._event_jsonld(div)
            if ld is not None:
                found_event_ld = True
            rec = self._map_event(div, ld)
            if rec is not None:
                records.append(rec)

        if not found_event_ld:
            raise ScraperException("no JSON-LD Event blocks found", FailureMode.FATAL)
        return records

    @staticmethod
    def _event_jsonld(div) -> dict | None:
        for script in div.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "Event":
                return data
        return None

    def _map_event(self, div, ld: dict | None) -> dict | None:
        title_el = div.select_one("span.evcal_event_title")
        title = title_el.get_text(strip=True) if title_el else ""
        parsed = parse_title(title)
        if parsed is None:
            log.debug("gh3: skipping non-run title %r", title)
            return None

        if not ld or "startDate" not in ld:
            log.warning("gh3: run %s missing startDate, skipping", parsed["runno"])
            return None
        try:
            dt = normalise_gh3_datetime(ld["startDate"])
        except ValueError:
            log.warning("gh3: bad startDate %r, skipping", ld.get("startDate"))
            return None

        description = ld.get("description")
        loc_fields: dict = {}
        if parsed.get("postcode"):
            loc_fields["postcode"] = parsed["postcode"]
        w3s = parse_w3s(description)
        if w3s:
            loc_fields["w3s"] = w3s
        lat, lng = parse_latlng(description)
        if lat is not None:
            loc_fields["lat"] = lat
            loc_fields["lng"] = lng

        run = Run(
            name=DISPLAY_NAME,
            kennel=self.name,
            runno=parsed["runno"],
            date=dt.strftime("%Y-%m-%d"),
            time=dt.strftime("%H:%M"),
            location=Location(**loc_fields),
            hares=parsed["hares"] if parsed.get("hares") else None,
            website=ld.get("url") or None,
        )
        return run.to_record()
