"""Base scraper framework: FailureMode, ScraperException, BaseScraper.

Central responsibilities live here so site scrapers stay thin:
- ``fetch()`` performs HTTP and maps status codes to failure modes, capturing
  request/response metadata for structured logging.
- ``validate()`` validates a single record against ``run.schema.json``.
- ``run()`` orchestrates fetch -> map -> validate.

Site scrapers implement ``map()`` and may override ``fetch()`` where the
transport differs (e.g. POST + base64 decode).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path

import requests
from jsonschema import Draft7Validator

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "run.schema.json"


class FailureMode(Enum):
    """TTL impact carried by a ScraperException.

    The enum *value* is the amount to decrement the TTL by; FATAL (None) zeros
    the TTL immediately.
    """

    TRANSIENT = 1  # 404, 500, parse/mapping errors -> decrement 1
    AUTH = 2  # 401, 403 -> decrement 2
    FATAL = None  # endpoint gone / structure changed -> zero immediately


class ScraperException(Exception):
    """Raised by scrapers, carrying the failure mode that drives TTL changes."""

    def __init__(self, message: str, mode: FailureMode):
        super().__init__(message)
        self.message = message
        self.mode = mode


def _load_validator() -> Draft7Validator:
    with open(_SCHEMA_PATH, encoding="utf-8") as fh:
        return Draft7Validator(json.load(fh))


class BaseScraper(ABC):
    name: str
    version: str

    # Default transport config; subclasses override as needed.
    url: str | None = None
    method: str = "GET"
    timeout: int = 10

    _validator = None

    def __init__(self):
        # Populated by fetch() for the log writer to consume.
        self.last_request: dict | None = None
        self.last_response: dict | None = None

    # ------------------------------------------------------------------ fetch
    def build_url(self) -> str:
        """Return the request URL. Override if it needs runtime construction."""
        if not self.url:
            raise ScraperException(
                f"{self.name}: no URL configured", FailureMode.FATAL
            )
        return self.url

    def fetch(self) -> str:
        """Perform the HTTP request and return the raw response body text.

        Maps status codes to failure modes and records request/response
        metadata on ``self.last_request`` / ``self.last_response``.
        """
        url = self.build_url()
        self.last_request = {"url": url, "method": self.method, "headers": {}}
        try:
            resp = requests.request(
                self.method, url, timeout=self.timeout, allow_redirects=True
            )
        except requests.RequestException as exc:
            raise ScraperException(
                f"{self.name}: request failed: {exc}", FailureMode.TRANSIENT
            ) from exc

        body = resp.text
        self.last_response = {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "body_size_bytes": len(resp.content),
            "body": body,
        }

        if resp.status_code in (401, 403):
            raise ScraperException(
                f"{self.name}: auth failure {resp.status_code}", FailureMode.AUTH
            )
        if resp.status_code != 200:
            raise ScraperException(
                f"{self.name}: HTTP {resp.status_code}", FailureMode.TRANSIENT
            )
        return body

    # --------------------------------------------------------------- validate
    @classmethod
    def _get_validator(cls) -> Draft7Validator:
        if BaseScraper._validator is None:
            BaseScraper._validator = _load_validator()
        return BaseScraper._validator

    def validate(self, record: dict) -> None:
        """Validate a single record against run.schema.json.

        Raises ScraperException(TRANSIENT) on failure — a mapping bug should
        decrement TTL but not be treated as fatal.
        """
        errors = sorted(
            self._get_validator().iter_errors(record), key=lambda e: e.path
        )
        if errors:
            msgs = "; ".join(e.message for e in errors)
            raise ScraperException(
                f"{self.name}: schema validation failed: {msgs}",
                FailureMode.TRANSIENT,
            )

    # -------------------------------------------------------------------- map
    @abstractmethod
    def map(self, raw) -> list[dict]:
        """Transform raw fetched data into a list of run records."""

    # -------------------------------------------------------------------- run
    def run(self) -> list[dict]:
        """fetch -> map -> validate. Returns validated records."""
        raw = self.fetch()
        records = self.map(raw)
        for record in records:
            self.validate(record)
        return records
