"""TTL circuit-breaker state, persisted to state/state.json."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scrapers.base import FailureMode

_STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "state.json"


class StateStore:
    def __init__(self, path: Path = _STATE_PATH):
        self.path = Path(path)
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                self._data = json.load(fh)
        else:
            self._data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, sort_keys=True)
            fh.write("\n")

    def _entry(self, site: str, ttl_max: int) -> dict:
        if site not in self._data:
            self._data[site] = {
                "ttl_current": ttl_max,
                "last_success": None,
                "last_failure": None,
                "disabled_at": None,
            }
        return self._data[site]

    def get(self, site: str) -> dict | None:
        return self._data.get(site)

    def all(self) -> dict:
        return self._data

    def is_disabled(self, site: str) -> bool:
        entry = self._data.get(site)
        return bool(entry and entry.get("disabled_at"))

    def record_success(self, site: str, ttl_max: int) -> dict:
        entry = self._entry(site, ttl_max)
        entry["ttl_current"] = ttl_max
        entry["last_success"] = date.today().isoformat()
        entry["disabled_at"] = None
        return entry

    def record_failure(self, site: str, ttl_max: int, mode: FailureMode) -> dict:
        """Apply the TTL change for a failure and persist. Returns the entry."""
        entry = self._entry(site, ttl_max)
        before = entry["ttl_current"]
        if mode is FailureMode.FATAL:
            after = 0
        else:
            after = before - mode.value
        after = max(0, after)
        entry["ttl_current"] = after
        entry["last_failure"] = date.today().isoformat()
        if after == 0:
            entry["disabled_at"] = date.today().isoformat()
        return entry

    def reset(self, site: str, ttl_max: int) -> dict:
        """Re-enable a disabled scraper, restoring full TTL."""
        entry = self._entry(site, ttl_max)
        entry["ttl_current"] = ttl_max
        entry["disabled_at"] = None
        return entry
