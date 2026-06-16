"""Chichester Hash House Harriers scraper. See docs/CHI3.md.

Fetches a server-rendered HTML diary page and extracts run data from a single
``<table>``. Rows with fewer than 9 ``<td>`` cells (colspan placeholders) are
silently skipped. Past-date filtering is handled by BaseScraper.run().
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from models.run import Location, Run
from scrapers.base import BaseScraper, FailureMode, ScraperException

log = logging.getLogger(__name__)

URL = "https://www.chihhh.org.uk/diary.php"
DISPLAY_NAME = "Chichester Hash House Harriers"
WEBSITE = "https://www.chihhh.org.uk"

# Site blocks the default python-requests User-Agent with a 403.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; myRunList-scraper/1.0; "
        "+https://github.com/aklambeth/myRunList-scraper)"
    )
}


def parse_runno(cell: str) -> int:
    return int(cell.strip().split()[-1])


def parse_datetime(cell: str) -> tuple[str, str]:
    dt = datetime.strptime(cell.strip(), "%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def parse_hares(cell: str) -> dict:
    result: dict = {}
    cell = cell.strip()
    if "Hares:" in cell:
        parts = cell.split("Hares:", 1)
        notes_prefix = parts[0].strip().rstrip(".")
        if notes_prefix:
            result["notes"] = notes_prefix
        hare_str = parts[1].strip()
    else:
        hare_str = cell
    names = re.split(r"\s*&\s*|\s+and\s+|,\s*", hare_str)
    names = [n.strip() for n in names if n.strip()]
    if names:
        result["hares"] = names
    return result


def parse_latlng(td) -> tuple[float | None, float | None]:
    a = td.find("a", href=True)
    if not a:
        return None, None
    href = a["href"]
    if "explore.osmaps.com" not in href:
        return None, None
    qs = parse_qs(urlparse(href).query)
    try:
        return float(qs["lat"][0]), float(qs["lon"][0])
    except (KeyError, ValueError, IndexError):
        return None, None


class CHI3Scraper(BaseScraper):
    name = "chi3"
    version = "1.0.1"
    url = URL
    request_headers = _HEADERS

    def map(self, raw: str) -> list[dict]:
        soup = BeautifulSoup(raw, "html.parser")
        tables = soup.find_all("table")
        diary_table = None
        for t in tables:
            if t.find("th", string=re.compile(r"^Run$")):
                diary_table = t
                break
        if not diary_table:
            raise ScraperException("diary table not found", FailureMode.FATAL)

        complete_rows = [
            tr.find_all("td")
            for tr in diary_table.find_all("tr")
            if len(tr.find_all("td")) == 9
        ]
        if not complete_rows:
            raise ScraperException(
                "no complete rows found in diary table", FailureMode.TRANSIENT
            )

        records: list[dict] = []
        for tds in complete_rows:
            try:
                runno = parse_runno(tds[0].get_text(strip=True))
            except (ValueError, IndexError):
                log.warning("chi3: bad run number %r, skipping", tds[0].get_text())
                continue
            try:
                date, time = parse_datetime(tds[1].get_text(strip=True))
            except ValueError:
                log.warning("chi3: bad date %r, skipping", tds[1].get_text())
                continue

            hare_data = parse_hares(tds[2].get_text(strip=True))
            venue = tds[3].get_text(strip=True) or None
            osgrid = tds[4].get_text(strip=True) or None
            lat, lng = parse_latlng(tds[5])

            loc_fields: dict = {}
            if venue:
                loc_fields["name"] = venue
            if osgrid:
                loc_fields["osgrid"] = osgrid
            if lat is not None:
                loc_fields["lat"] = lat
                loc_fields["lng"] = lng

            run = Run(
                name=DISPLAY_NAME,
                kennel=self.name,
                runno=runno,
                date=date,
                time=time,
                location=Location(**loc_fields),
                hares=hare_data.get("hares"),
                notes=hare_data.get("notes"),
                website=WEBSITE,
            )
            records.append(run.to_record())
        return records
