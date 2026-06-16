"""North Hampshire Hash House Harriers scraper. See docs/NH4.md.

Data source is a published Google Sheet exported as CSV. The full sheet is
returned; we trim to columns B-I and the first 11 rows (header + 10 runs).
The Date/Time column is a single multi-line cell, e.g.::

    Sunday
    13th Sep 2026
    11:00 am
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
from datetime import datetime

from models.run import W3S_PATTERN, Location, Run
from scrapers.base import BaseScraper, FailureMode, ScraperException

log = logging.getLogger(__name__)

DISPLAY_NAME = "North Hampshire Hash House Harriers"
URL_TEMPLATE = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTVhgeQtlXNqbt00EUMEtnm9BUKusXxkIfKyjucXz-lGYkmN2gFoCm89BPovapIf"
    "-1c8zheXvS8npg_/pub?gid={gid}&single=true&output=csv"
)

DATA_COL_START = 1  # skip column A (index 0)
DATA_ROW_LIMIT = 11  # header + max 10 data rows

# Normalised header text -> schema concept.
HEADER_MAP = {
    "run #": "runno",
    "date/time": "datetime",
    "location": "location",
    "hare(s)": "hares",
    "on inn": "oninn",
    "notes": "notes",
    "nearest postcode": "postcode",
    "w3w": "w3s",
}

_PLACEHOLDERS = {"", "tba", "tbc", "hares needed"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_placeholder(value: str) -> bool:
    return _norm(value).lower() in _PLACEHOLDERS


def parse_datetime_cell(cell: str) -> tuple[str, str | None]:
    """Return (YYYY-MM-DD, HH:MM|None) from a multi-line Date/Time cell."""
    lines = [ln.strip() for ln in cell.splitlines() if ln.strip()]
    date_str: str | None = None
    time_str: str | None = None

    for line in lines:
        if date_str is None and re.search(r"\b\d{4}\b", line):
            date_str = _parse_date_line(line)
            continue
        if time_str is None and re.search(r"\d{1,2}:\d{2}", line):
            time_str = _parse_time_line(line)

    if date_str is None:
        raise ValueError(f"no date found in {cell!r}")
    return date_str, time_str


def _parse_date_line(line: str) -> str:
    # Strip ordinal suffix: "13th" -> "13", "3rd" -> "3".
    cleaned = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", line, flags=re.IGNORECASE)
    cleaned = _norm(cleaned)
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"unparseable date line {line!r}")


def _parse_time_line(line: str) -> str | None:
    m = re.search(r"(\d{1,2}):(\d{2})\s*([ap]m)?", line, re.IGNORECASE)
    if not m:
        return None
    spec = f"{m.group(1)}:{m.group(2)}"
    if m.group(3):
        return datetime.strptime(
            f"{spec} {m.group(3).lower()}", "%I:%M %p"
        ).strftime("%H:%M")
    return datetime.strptime(spec, "%H:%M").strftime("%H:%M")


def parse_hares(cell: str) -> list[str] | None:
    if _is_placeholder(cell):
        return None
    names = re.split(r"\s*\+\s*|\s*,\s*", _norm(cell))
    names = [n.strip() for n in names if n.strip()]
    return names or None


class NH4Scraper(BaseScraper):
    name = "nh4"
    version = "1.0.0"

    def build_url(self) -> str:
        gid = os.environ.get("NH4_API_KEY")
        if not gid:
            raise ScraperException(
                "NH4_API_KEY not set", FailureMode.AUTH
            )
        return URL_TEMPLATE.format(gid=gid)

    def map(self, raw: str) -> list[dict]:
        if raw.lstrip().lower().startswith("<!doctype") or raw.lstrip().startswith("<"):
            raise ScraperException(
                "expected CSV, got HTML", FailureMode.FATAL
            )

        rows = list(csv.reader(io.StringIO(raw)))
        rows = [row[DATA_COL_START:] for row in rows[:DATA_ROW_LIMIT]]
        if not rows:
            raise ScraperException("empty CSV", FailureMode.TRANSIENT)

        header = [_norm(h).lower() for h in rows[0]]
        col = {}
        for idx, h in enumerate(header):
            concept = HEADER_MAP.get(h)
            if concept:
                col[concept] = idx

        for required in ("runno", "datetime"):
            if required not in col:
                raise ScraperException(
                    f"missing expected column for {required}", FailureMode.FATAL
                )

        data_rows = [r for r in rows[1:] if any(c.strip() for c in r)]
        if not data_rows:
            raise ScraperException("no data rows", FailureMode.TRANSIENT)

        records: list[dict] = []
        for row in data_rows:
            rec = self._map_row(row, col)
            if rec is not None:
                records.append(rec)
        return records

    def _map_row(self, row: list[str], col: dict) -> dict | None:
        def cell(concept: str) -> str:
            idx = col.get(concept)
            return row[idx] if idx is not None and idx < len(row) else ""

        try:
            runno = int(_norm(cell("runno")))
        except ValueError:
            log.warning("nh4: bad run number %r, skipping", cell("runno"))
            return None
        try:
            date, time = parse_datetime_cell(cell("datetime"))
        except ValueError as exc:
            log.warning("nh4: %s, skipping run %s", exc, runno)
            return None

        loc_fields: dict = {}
        loc_name = _norm(cell("location"))
        if loc_name and not _is_placeholder(loc_name):
            loc_fields["name"] = loc_name
        postcode = _norm(cell("postcode"))
        if postcode and not _is_placeholder(postcode):
            loc_fields["postcode"] = postcode
        w3s = _norm(cell("w3s"))
        if w3s and re.match(W3S_PATTERN, w3s):
            loc_fields["w3s"] = w3s

        oninn = _norm(cell("oninn"))
        notes = _norm(cell("notes"))

        run = Run(
            name=DISPLAY_NAME,
            kennel=self.name,
            runno=runno,
            date=date,
            time=time,
            location=Location(**loc_fields),
            hares=parse_hares(cell("hares")),
            oninn=oninn if oninn and not _is_placeholder(oninn) else None,
            notes=notes or None,
            website=None,
        )
        return run.to_record()
