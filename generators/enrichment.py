"""Post-processing enrichment: populate lat/lng from W3W address when coords are absent."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
from pathlib import Path

import requests

from scrapers.base import FailureMode

log = logging.getLogger(__name__)

_W3W_TTL_MAX = 5
_W3W_STATE_KEY = "enrich_w3w"
_CACHE_MAX = 1000
_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "w3w_cache.json"
_LOCK_PATH = Path(__file__).resolve().parent.parent / "data" / ".w3w_cache.lock"

_W3W_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ------------------------------------------------------------------ cache


def _read_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(entry_key: str, lat: float, lng: float, cache_path: Path = _CACHE_PATH) -> None:
    lock_path = cache_path.parent / ".w3w_cache.lock"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            cache = _read_cache(cache_path)
            cache[entry_key] = {"lat": lat, "lng": lng}
            if len(cache) > _CACHE_MAX:
                cache = dict(list(cache.items())[-_CACHE_MAX:])
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
            os.replace(tmp, cache_path)
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


# ------------------------------------------------------------------ W3W lookup


def lookup_w3w(address: str, cache_path: Path = _CACHE_PATH) -> tuple[float, float] | None:
    """Return (lat, lng) for a w3s address. Checks cache first. Never raises."""
    cache = _read_cache(cache_path)
    if address in cache:
        entry = cache[address]
        return entry["lat"], entry["lng"]

    url = f"https://what3words.com/{address}"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _W3W_USER_AGENT},
            timeout=10,
        )
        text = resp.text
    except requests.RequestException:
        return None

    lat_m = re.search(r"lat=(-?\d+\.\d+)", text)
    lng_m = re.search(r"lng=(-?\d+\.\d+)", text)
    if not lat_m or not lng_m:
        return None

    lat, lng = float(lat_m.group(1)), float(lng_m.group(1))
    _write_cache(address, lat, lng, cache_path)
    return lat, lng


# ------------------------------------------------------------------ enrichment


def enrich_records(records: list[dict], state_store) -> list[dict]:
    """Enrich records missing lat/lng in-place. Returns the same list."""
    for record in records:
        loc = record.get("location")
        if not isinstance(loc, dict):
            continue
        if loc.get("lat") is not None and loc.get("lng") is not None:
            continue

        # W3W — last resort for records with no coords
        w3s = loc.get("w3s")
        if not w3s:
            continue

        # Always try cache first — even if the circuit breaker is disabled
        cached = _read_cache(_CACHE_PATH)
        if w3s in cached:
            loc["lat"] = cached[w3s]["lat"]
            loc["lng"] = cached[w3s]["lng"]
            continue

        if state_store.is_disabled(_W3W_STATE_KEY):
            continue

        coords = lookup_w3w(w3s)
        if coords:
            loc["lat"], loc["lng"] = coords
            state_store.record_success(_W3W_STATE_KEY, _W3W_TTL_MAX)
        else:
            log.warning("enrich: W3W lookup failed for %r", w3s)
            entry = state_store.record_failure(_W3W_STATE_KEY, _W3W_TTL_MAX, FailureMode.AUTH)
            if entry.get("disabled_at"):
                log.warning("enrich: %s circuit breaker tripped — service disabled", _W3W_STATE_KEY)

    return records
