"""Hursley Hash House Harriers scraper. See docs/HH3.md.

Fetches a server-side-included HTML fragment containing a single
``<table class="order-table table">`` of upcoming runs. No JS or auth required.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from models.run import Location, Run
from scrapers.base import BaseScraper, FailureMode, ScraperException

log = logging.getLogger(__name__)

URL = "https://www.hursleyh3.co.uk/includes/table-nextRuns.html"
DISPLAY_NAME = "Hursley Hash House Harriers"
WEBSITE = "https://www.hursleyh3.co.uk"

# Site blocks the default python-requests User-Agent with a 403.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; myRunList-scraper/1.0; "
        "+https://github.com/aklambeth/myRunList-scraper)"
    )
}


def parse_runno(cell: str) -> tuple[int, str | None]:
    m = re.match(r"^(\d+)(.*)", cell.strip())
    if not m:
        raise ValueError(f"Cannot parse run number from: {cell!r}")
    suffix = m.group(2).strip() or None
    return int(m.group(1)), suffix


def parse_date_time(cell: str) -> tuple[str, str | None]:
    cell = cell.strip()
    if " " in cell:
        dt = datetime.strptime(cell, "%d/%m/%y %H:%M")
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    dt = datetime.strptime(cell, "%d/%m/%y")
    return dt.strftime("%Y-%m-%d"), None


def parse_hares(cell: str) -> list[str]:
    parts = re.split(r"\s*&\s*|\s*,\s*", cell)
    return [p.strip() for p in parts if p.strip()]


def parse_oninn(cell: str) -> str | None:
    val = cell.strip()
    return val if val else None


def parse_location_name(cell: str) -> str | None:
    val = cell.strip()
    return val if val and val != "?" else None


def parse_postcode(cell: str) -> str | None:
    val = cell.strip().upper()
    return val if val else None


def extract_rows(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="order-table")
    if not table:
        raise ScraperException("table.order-table not found", FailureMode.FATAL)
    rows = table.find("tbody").find_all("tr")
    return [
        [td.get_text(separator=" ", strip=True) for td in row.find_all("td")]
        for row in rows
        if len(row.find_all("td")) == 6
    ]


class HH3Scraper(BaseScraper):
    name = "hh3"
    version = "1.0.0"
    url = URL
    request_headers = _HEADERS

    def map(self, raw: str) -> list[dict]:
        rows = extract_rows(raw)
        if not rows:
            raise ScraperException("no valid rows found in table", FailureMode.TRANSIENT)

        records: list[dict] = []
        for row in rows:
            runno_raw, date_raw, pub_raw, loc_raw, pc_raw, hares_raw = row
            try:
                runno, suffix = parse_runno(runno_raw)
            except ValueError:
                log.warning("hh3: bad run number %r, skipping", runno_raw)
                continue
            try:
                date, time = parse_date_time(date_raw)
            except ValueError:
                log.warning("hh3: bad date %r, skipping", date_raw)
                continue

            loc_fields: dict = {}
            loc_name = parse_location_name(loc_raw)
            if loc_name:
                loc_fields["name"] = loc_name
            postcode = parse_postcode(pc_raw)
            if postcode:
                loc_fields["postcode"] = postcode

            hares = parse_hares(hares_raw) or None
            oninn = parse_oninn(pub_raw)

            run = Run(
                name=DISPLAY_NAME,
                kennel=self.name,
                runno=runno,
                date=date,
                time=time,
                location=Location(**loc_fields),
                hares=hares,
                oninn=oninn,
                notes=suffix,
                website=WEBSITE,
            )
            records.append(run.to_record())
        return records
