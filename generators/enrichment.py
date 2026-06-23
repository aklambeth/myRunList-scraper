"""Post-processing enrichment: populate lat/lng from W3W address or Google Geocoding when coords are absent."""

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
_GEOCODE_TTL_MAX = 5
_GEOCODE_STATE_KEY = "enrich_geocode"
_NOMINATIM_TTL_MAX = 5
_NOMINATIM_STATE_KEY = "enrich_nominatim"
_CACHE_MAX = 1000
_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "w3w_cache.json"
_GEOCODE_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "geocode_cache.json"

_W3W_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_NO_MATCH = object()
_GOOGLE_UNAVAILABLE = object()  # REQUEST_DENIED / OVER_QUERY_LIMIT — try Nominatim instead

_NOMINATIM_USER_AGENT = "myRunList-scraper/1.0 (anthropic@adrian.lambeth.org)"


# ------------------------------------------------------------------ cache


def _read_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(entry_key: str, lat: float | None, lng: float | None, cache_path: Path = _CACHE_PATH, query: str | None = None) -> None:
    lock_path = cache_path.parent / f".{cache_path.stem}_cache.lock"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            cache = _read_cache(cache_path)
            entry: dict = {"lat": lat, "lng": lng}
            if query is not None:
                entry["query"] = query
            cache[entry_key] = entry
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


def lookup_geocode(entry_key: str, query: str, cache_path: Path = _GEOCODE_CACHE_PATH) -> tuple[float, float] | object | None:
    """Resolve coords for a record, cached under the stable entry_key (kennel:runno).

    Returns (lat, lng) on OK, _NO_MATCH on ZERO_RESULTS, _GOOGLE_UNAVAILABLE on
    REQUEST_DENIED/OVER_QUERY_LIMIT, None on transient error. Never raises.
    A cached entry is honoured only while its stored query matches; a changed
    query (address corrected at source) is a miss and re-geocodes in place.
    """
    cache = _read_cache(cache_path)
    entry = cache.get(entry_key)
    if entry is not None and entry.get("query") == query:
        if entry["lat"] is None and entry["lng"] is None:
            return _NO_MATCH
        return entry["lat"], entry["lng"]

    api_key = os.environ.get("GOOGLE_GEOCODING_API_KEY")
    if not api_key:
        return _GOOGLE_UNAVAILABLE

    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={requests.utils.quote(query)}&key={api_key}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    status = data.get("status", "")
    if status == "OK" and data.get("results"):
        loc = data["results"][0]["geometry"]["location"]
        lat, lng = float(loc["lat"]), float(loc["lng"])
        _write_cache(entry_key, lat, lng, cache_path, query=query)
        return lat, lng
    elif status == "ZERO_RESULTS":
        _write_cache(entry_key, None, None, cache_path, query=query)
        return _NO_MATCH
    elif status in ("REQUEST_DENIED", "OVER_QUERY_LIMIT"):
        return _GOOGLE_UNAVAILABLE
    else:
        return None


def lookup_nominatim(entry_key: str, query: str, cache_path: Path = _GEOCODE_CACHE_PATH) -> tuple[float, float] | object | None:
    """Resolve coords via Nominatim, cached under the stable entry_key (kennel:runno).

    Returns (lat, lng) on OK, _NO_MATCH on empty results, None on transient error.
    Never raises. Shares the geocode cache with Google: a cached entry is honoured
    only while its stored query matches (changed query → re-geocode in place).
    """
    cache = _read_cache(cache_path)
    entry = cache.get(entry_key)
    if entry is not None and entry.get("query") == query:
        if entry["lat"] is None and entry["lng"] is None:
            return _NO_MATCH
        return entry["lat"], entry["lng"]

    url = "https://nominatim.openstreetmap.org/search"
    try:
        resp = requests.get(
            url,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": _NOMINATIM_USER_AGENT},
            timeout=10,
        )
        results = resp.json()
    except (requests.RequestException, ValueError):
        return None

    if results:
        lat, lng = float(results[0]["lat"]), float(results[0]["lon"])
        _write_cache(entry_key, lat, lng, cache_path, query=query)
        return lat, lng
    else:
        _write_cache(entry_key, None, None, cache_path, query=query)
        return _NO_MATCH


# ------------------------------------------------------------------ enrichment


def _try_nominatim(entry_key: str, query: str, loc: dict, state_store) -> bool:
    """Attempt Nominatim lookup and populate loc in-place. Returns True if coords were set."""
    if state_store.is_disabled(_NOMINATIM_STATE_KEY):
        return False

    coords = lookup_nominatim(entry_key, query)
    if coords is _NO_MATCH:
        return False
    elif coords:
        loc["lat"], loc["lng"] = coords
        state_store.record_success(_NOMINATIM_STATE_KEY, _NOMINATIM_TTL_MAX)
        return True
    else:
        log.warning("enrich: Nominatim lookup failed for %r", query)
        entry = state_store.record_failure(_NOMINATIM_STATE_KEY, _NOMINATIM_TTL_MAX, FailureMode.TRANSIENT)
        if entry.get("disabled_at"):
            log.warning("enrich: %s circuit breaker tripped — service disabled", _NOMINATIM_STATE_KEY)
        return False


def enrich_records(records: list[dict], state_store) -> list[dict]:
    """Enrich records missing lat/lng in-place. Returns the same list."""
    for record in records:
        loc = record.get("location")
        if not isinstance(loc, dict):
            continue
        if loc.get("lat") is not None and loc.get("lng") is not None:
            continue

        # W3W — for records that have a w3s address
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

    # Geocoding fallback — after W3W, for records still missing coords
    # Tries Google first; falls back to Nominatim when Google is unavailable
    # (no key, REQUEST_DENIED, OVER_QUERY_LIMIT, or circuit breaker disabled).
    for record in records:
        loc = record.get("location")
        if not isinstance(loc, dict):
            continue
        if loc.get("lat") is not None and loc.get("lng") is not None:
            continue

        address = loc.get("address") or loc.get("name")
        postcode = loc.get("postcode")

        if not postcode:
            continue

        query = " ".join(p for p in (address, postcode) if p)
        entry_key = f"{record['kennel']}:{record['runno']}"

        # Cache first — one entry per event keyed kennel:runno, shared by both
        # providers. Honour it only while the stored query matches (a changed
        # address falls through and re-geocodes in place). A negative entry
        # (null coords) means a known no-match → skip without calling out.
        cache = _read_cache(_GEOCODE_CACHE_PATH)
        if entry_key in cache:
            cached_entry = cache[entry_key]
            if cached_entry.get("query") == query:
                if cached_entry["lat"] is not None and cached_entry["lng"] is not None:
                    loc["lat"] = cached_entry["lat"]
                    loc["lng"] = cached_entry["lng"]
                continue

        google_disabled = state_store.is_disabled(_GEOCODE_STATE_KEY)
        use_nominatim = google_disabled

        if not google_disabled:
            coords = lookup_geocode(entry_key, query, cache_path=_GEOCODE_CACHE_PATH)
            if coords is _NO_MATCH:
                continue
            elif coords is _GOOGLE_UNAVAILABLE:
                log.info("enrich: Google geocoding unavailable for %r — trying Nominatim", query)
                use_nominatim = True
            elif coords:
                loc["lat"], loc["lng"] = coords
                state_store.record_success(_GEOCODE_STATE_KEY, _GEOCODE_TTL_MAX)
            else:
                log.warning("enrich: geocode lookup failed for %r", query)
                fb_entry = state_store.record_failure(_GEOCODE_STATE_KEY, _GEOCODE_TTL_MAX, FailureMode.TRANSIENT)
                if fb_entry.get("disabled_at"):
                    log.warning("enrich: %s circuit breaker tripped — trying Nominatim", _GEOCODE_STATE_KEY)
                    use_nominatim = True

        if use_nominatim:
            _try_nominatim(entry_key, query, loc, state_store)

    return records
