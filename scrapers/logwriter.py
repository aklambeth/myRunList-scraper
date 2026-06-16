"""Structured JSON logging, one directory per scraper.

Log file count is capped at ``ttl_max`` — oldest purged when exceeded. On
reset, the directory is cleared so the next TTL cycle starts fresh.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from scrapers.base import FailureMode

_LOGS_ROOT = Path(__file__).resolve().parent.parent / "logs"


class LogWriter:
    def __init__(self, max_body_size_bytes: int = 10240, root: Path = _LOGS_ROOT):
        self.max_body_size_bytes = max_body_size_bytes
        self.root = Path(root)

    def _site_dir(self, site: str) -> Path:
        return self.root / site

    def _truncate_body(self, body: str | None) -> tuple[str, bool]:
        if not body:
            return "", False
        encoded = body.encode("utf-8")
        if len(encoded) <= self.max_body_size_bytes:
            return body, False
        return encoded[: self.max_body_size_bytes].decode("utf-8", "ignore"), True

    def _build_response(self, response: dict | None) -> dict | None:
        if not response:
            return None
        body, truncated = self._truncate_body(response.get("body"))
        return {
            "status_code": response.get("status_code"),
            "headers": response.get("headers", {}),
            "body_size_bytes": response.get("body_size_bytes", 0),
            "body_truncated": truncated,
            "body": body,
        }

    def write(
        self,
        *,
        site: str,
        version: str,
        status: str,
        ttl_before: int,
        ttl_after: int,
        records_parsed: int,
        ttl_max: int,
        failure_mode: FailureMode | None = None,
        exception: BaseException | None = None,
        request: dict | None = None,
        response: dict | None = None,
    ) -> Path:
        entry: dict = {
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "site": site,
            "scraper_version": version,
            "status": status,
            "failure_mode": failure_mode.name if failure_mode else None,
            "ttl_before": ttl_before,
            "ttl_after": ttl_after,
            "records_parsed": records_parsed,
            "exception": None,
            "request": request,
            "response": self._build_response(response),
        }
        if exception is not None:
            entry["exception"] = {
                "type": type(exception).__name__,
                "message": str(exception),
                "stacktrace": traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                ),
            }

        site_dir = self._site_dir(site)
        site_dir.mkdir(parents=True, exist_ok=True)
        path = site_dir / f"{datetime.now(timezone.utc):%Y-%m-%d}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(entry, fh, indent=2)
            fh.write("\n")

        self._purge(site_dir, ttl_max)
        return path

    def _purge(self, site_dir: Path, ttl_max: int) -> None:
        files = sorted(site_dir.glob("*.json"))
        excess = len(files) - ttl_max
        for old in files[:excess] if excess > 0 else []:
            old.unlink()

    def clear(self, site: str) -> None:
        site_dir = self._site_dir(site)
        if site_dir.exists():
            for f in site_dir.glob("*.json"):
                f.unlink()

    def read(self, site: str) -> list[dict]:
        site_dir = self._site_dir(site)
        if not site_dir.exists():
            return []
        out = []
        for f in sorted(site_dir.glob("*.json")):
            with open(f, encoding="utf-8") as fh:
                out.append(json.load(fh))
        return out
