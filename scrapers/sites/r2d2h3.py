"""R2D2 Hash House Harriers scraper. See docs/R2D2H3.md."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from models.run import OSGRID_PATTERN, Location, Run
from scrapers.base import BaseScraper, FailureMode, ScraperException

log = logging.getLogger(__name__)

ENDPOINT = (
    "https://www.myfreedevsite.com/r2d2h3leagues/gethashtables.aspx"
    "?title=Next%20Twenty%20Runs&dataname=next20runs"
)
DISPLAY_NAME = "R2D2 Hash House Harriers"
WEBSITE = "https://www.r2d2h3.com"


def extract_rows(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr", class_=lambda c: c and "hashTableBodyRow" in c)
    return [
        [td.get_text(strip=True) for td in row.find_all("td")]
        for row in rows
        if len(row.find_all("td")) == 5
    ]


def parse_gridref_postcode(cell: str) -> dict:
    result: dict = {}
    cell = cell.strip()
    if not cell or cell.upper() == "TBC":
        return result

    if cell.lower().startswith("w3w."):
        slug = cell[4:].strip("/")
        if re.match(r"^[a-z]+\.[a-z]+\.[a-z]+$", slug):
            result["w3s"] = slug
        return result

    combined = re.match(
        r"^([A-Z]{0,2}\d[\d\s]{3,})\s*/\s*([A-Z]{1,2}\d{1,2}\s*\d[A-Z]{2})$",
        cell,
        re.IGNORECASE,
    )
    if combined:
        osgrid_raw = combined.group(1).replace(" ", "").upper()
        result["postcode"] = combined.group(2).strip().upper()
        # Central schema requires a two-letter prefix; only emit if it matches.
        if re.match(OSGRID_PATTERN, osgrid_raw):
            result["osgrid"] = osgrid_raw
        return result

    pc = re.match(r"^([A-Z]{1,2}\d{1,2}\s*\d[A-Z]{2})$", cell, re.IGNORECASE)
    if pc:
        result["postcode"] = pc.group(1).strip().upper()
        return result

    osgrid = re.match(r"^[A-Z]{2}\d{4,}$", cell.replace(" ", ""), re.IGNORECASE)
    if osgrid:
        candidate = cell.replace(" ", "").upper()
        if re.match(OSGRID_PATTERN, candidate):
            result["osgrid"] = candidate
        return result

    return result


def parse_notes(cell: str) -> dict:
    result: dict = {}
    cell = cell.strip()
    if not cell or cell.lower() in ("tbc", "hares needed"):
        return result

    parts = cell.split(" - ", maxsplit=1)
    hare_part = parts[0].strip()
    if len(parts) > 1:
        result["notes"] = parts[1].strip()

    names = re.split(r",\s*|\s+and\s+", hare_part)
    names = [n.strip() for n in names if n.strip()]
    if names:
        result["hares"] = names
    return result


def parse_date(cell: str) -> str:
    return datetime.strptime(cell.strip(), "%d %b %Y").strftime("%Y-%m-%d")


class R2D2H3Scraper(BaseScraper):
    name = "r2d2h3"
    version = "1.0.0"
    url = ENDPOINT

    def map(self, raw: str) -> list[dict]:
        rows = extract_rows(raw)
        if not rows:
            raise ScraperException(
                "no hashTableBodyRow rows found", FailureMode.FATAL
            )

        records: list[dict] = []
        for row in rows:
            runno_raw, date_raw, location_raw, gridref_raw, notes_raw = row
            try:
                runno = int(runno_raw.strip())
            except ValueError:
                log.warning("r2d2h3: bad run number %r, skipping", runno_raw)
                continue
            try:
                date = parse_date(date_raw)
            except ValueError:
                log.warning("r2d2h3: bad date %r, skipping", date_raw)
                continue

            loc_fields = parse_gridref_postcode(gridref_raw)
            loc_name = location_raw.strip()
            if loc_name and loc_name.upper() != "TBC":
                loc_fields["name"] = loc_name

            note_fields = parse_notes(notes_raw)

            run = Run(
                name=DISPLAY_NAME,
                runno=runno,
                date=date,
                location=Location(**loc_fields),
                hares=note_fields.get("hares"),
                notes=note_fields.get("notes"),
                website=WEBSITE,
            )
            records.append(run.to_record())
        return records
