"""Deepcut Hash House Harriers scraper. See docs/DH3.md.

Data comes from the Fouita widget API. The live response is doubly base64
encoded; ``fetch()`` decodes it down to the inner feed JSON string. ``map()``
receives that feed JSON (this is also what the test fixture contains) and
extracts the ``events`` array. All run fields are embedded as HTML strings.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from models.run import Location, Run
from scrapers.base import BaseScraper, FailureMode, ScraperException

log = logging.getLogger(__name__)

API_URL = "https://api2.fouita.com/v1/q/widget"
DISPLAY_NAME = "Deepcut Hash House Harriers"
WEBSITE = "https://www.dh3.org"


def strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()


def extract_labelled(html: str) -> str:
    """Strip a leading 'Label:' prefix and collapse whitespace."""
    text = strip_html(html)
    if ":" in text:
        text = text.split(":", 1)[1]
    return re.sub(r"\s+", " ", text).strip()


def _absent(value: str | None) -> bool:
    return not value or value.upper() == "TBA"


class DH3Scraper(BaseScraper):
    name = "dh3"
    version = "1.0.0"
    method = "POST"
    url = API_URL

    def fetch(self) -> str:
        import os

        uid = os.environ.get("DH3_API_KEY")
        if not uid:
            raise ScraperException("DH3_API_KEY not set", FailureMode.AUTH)

        self.last_request = {
            "url": API_URL,
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
        }
        try:
            resp = requests.post(
                API_URL,
                json={"uid": uid},
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ScraperException(
                f"dh3: request failed: {exc}", FailureMode.TRANSIENT
            ) from exc

        self.last_response = {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "body_size_bytes": len(resp.content),
            "body": resp.text,
        }
        if resp.status_code in (401, 403):
            raise ScraperException(
                f"dh3: auth failure {resp.status_code}", FailureMode.AUTH
            )
        if resp.status_code != 200:
            raise ScraperException(f"dh3: HTTP {resp.status_code}", FailureMode.TRANSIENT)

        try:
            outer = resp.json()
            envelope = json.loads(base64.b64decode(outer["json"]))
            feed_b64 = envelope["q"][0]["data_feed"][0]["feed_data"]
            feed_json = base64.b64decode(feed_b64).decode("utf-8")
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ScraperException(
                f"dh3: feed decode failed: {exc}", FailureMode.FATAL
            ) from exc
        return feed_json

    def map(self, raw: str) -> list[dict]:
        try:
            feed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ScraperException(f"dh3: bad feed JSON: {exc}", FailureMode.FATAL)

        if "events" not in feed:
            raise ScraperException("dh3: no events key", FailureMode.FATAL)
        events = feed["events"]
        if not events:
            raise ScraperException("dh3: empty events", FailureMode.TRANSIENT)

        records: list[dict] = []
        for event in events:
            rec = self._map_event(event)
            if rec is not None:
                records.append(rec)
        return records

    def _map_event(self, event: dict) -> dict | None:
        tag = event.get("tag", [])
        if len(tag) < 3:
            log.warning("dh3: tag too short, skipping")
            return None
        try:
            runno = int(tag[0].split()[-1])
        except (ValueError, IndexError):
            log.warning("dh3: bad run number %r, skipping", tag[0])
            return None
        try:
            dt = datetime.fromisoformat(event["date"])
        except (KeyError, ValueError):
            log.warning("dh3: bad date for run %s, skipping", runno)
            return None

        hare_raw = tag[1].strip()
        hares = [hare_raw] if not _absent(hare_raw) else None

        notes_raw = tag[2]
        notes = (
            notes_raw.split("Notes:", 1)[-1].strip()
            if "Notes:" in notes_raw
            else ""
        )
        notes = notes or None

        popup = event.get("popupArrText", [])
        rv = extract_labelled(popup[3]["html"]) if len(popup) > 3 else ""
        oninn = extract_labelled(popup[4]["html"]) if len(popup) > 4 else ""

        loc_fields: dict = {}
        if not _absent(rv):
            loc_fields["name"] = rv

        run = Run(
            name=DISPLAY_NAME,
            kennel=self.name,
            runno=runno,
            date=dt.strftime("%Y-%m-%d"),
            time=dt.strftime("%H:%M"),
            location=Location(**loc_fields),
            hares=hares,
            oninn=oninn if not _absent(oninn) else None,
            notes=notes,
            website=WEBSITE,
        )
        return run.to_record()
