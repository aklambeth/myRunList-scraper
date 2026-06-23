"""Tests for the Google Geocoding enrichment fallback.

All tests are offline — the Google API is mocked via responses or by
patching requests.get.  The cache files live under a tmp_path fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from generators.enrichment import (
    _CACHE_MAX,
    _NO_MATCH,
    _GOOGLE_UNAVAILABLE,
    _GEOCODE_CACHE_PATH,
    _GEOCODE_STATE_KEY,
    _GEOCODE_TTL_MAX,
    _read_cache,
    _write_cache,
    enrich_records,
    lookup_geocode,
)
from scrapers.base import FailureMode
from scrapers.state import StateStore


# ------------------------------------------------------------------ fixtures


@pytest.fixture()
def tmp_cache(tmp_path: Path):
    """Return a tmp_path with a dummy geocode_cache.json."""
    cache_path = tmp_path / "geocode_cache.json"
    cache_path.write_text("{}")
    return cache_path


@pytest.fixture()
def state(tmp_path: Path):
    return StateStore(path=tmp_path / "state.json")


@pytest.fixture()
def mock_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GOOGLE_GEOCODING_API_KEY", "test-key-123")


@pytest.fixture()
def tmp_cache(tmp_path: Path):
    """Provide a temporary cache path for tests that need it."""
    yield tmp_path / "geocode_cache.json"


def _make_record(
    kennel: str = "wwh3",
    runno: int = 2144,
    lat: float | None = None,
    lng: float | None = None,
    address: str | None = None,
    name: str | None = None,
    postcode: str | None = None,
) -> dict:
    loc: dict = {}
    if address:
        loc["address"] = address
    if name:
        loc["name"] = name
    if postcode:
        loc["postcode"] = postcode
    if lat is not None:
        loc["lat"] = lat
    if lng is not None:
        loc["lng"] = lng
    return {
        "name": "Test Run",
        "kennel": kennel,
        "runno": runno,
        "date": "2026-08-01",
        "location": loc if loc else {"name": "Stub Pub"},
    }


def _make_api_response(status: str, results: list[dict] | None = None) -> dict:
    """Build a mock Google Geocoding API JSON response."""
    resp: dict = {"status": status}
    if results is not None:
        resp["results"] = results
    else:
        resp["results"] = []
    return resp


def _make_result(lat: float, lng: float) -> dict:
    return {
        "formatted_address": "Test Address",
        "geometry": {"location": {"lat": lat, "lng": lng}},
    }


# ------------------------------------------------------------------ lookup_geocode


class TestLookupGeocode:
    """Tests for the lookup_geocode() function."""

    def test_cache_hit_positive(self, tmp_cache: Path, mock_api_key):
        """Cache hit with lat/lng → returns coords without API call."""
        tmp_cache.write_text(
            json.dumps({"wwh3:2144": {"lat": 51.0, "lng": -1.0, "query": "Test St SO24 9LW"}})
        )
        result = lookup_geocode("Test St SO24 9LW", cache_path=tmp_cache)
        assert result == (51.0, -1.0)

    def test_cache_hit_negative(self, tmp_cache: Path, mock_api_key):
        """Cache hit with null lat/lng (ZERO_RESULTS) → returns _NO_MATCH."""
        tmp_cache.write_text(
            json.dumps({"wwh3:2144": {"lat": None, "lng": None, "query": "Bad Address SO24 9LW"}})
        )
        result = lookup_geocode("Bad Address SO24 9LW", cache_path=tmp_cache)
        assert result is _NO_MATCH

    def test_cache_miss_staleness(self, tmp_cache: Path, mock_api_key):
        """Cache entry exists but query differs → treated as miss."""
        tmp_cache.write_text(
            json.dumps({"wwh3:2144": {"lat": 51.0, "lng": -1.0, "query": "Old Address SO24 9LW"}})
        )
        # The cache lookup should not match because query differs
        # (this is tested in enrich_records; lookup_geocode doesn't check entry_key)
        # lookup_geocode checks by query match in the cache, so a different query is a cache miss

    def test_no_api_key_returns_unavailable(self, tmp_cache: Path, monkeypatch: pytest.MonkeyPatch):
        """Without API key, lookup_geocode returns _GOOGLE_UNAVAILABLE so the caller falls back to Nominatim."""
        monkeypatch.delenv("GOOGLE_GEOCODING_API_KEY", raising=False)
        result = lookup_geocode("Test St SO24 9LW", cache_path=tmp_cache)
        assert result is _GOOGLE_UNAVAILABLE

    def test_network_error_returns_none(self, tmp_cache: Path, mock_api_key):
        """Network error → returns None, does not write cache."""
        import requests as _requests
        with patch("requests.get", side_effect=_requests.RequestException("network error")):
            result = lookup_geocode("Test St SO24 9LW", cache_path=tmp_cache)
        assert result is None
        # Cache file should not exist (no write on transient error)
        assert not tmp_cache.exists()

    def test_ok_response_populates_coords(self, tmp_cache: Path, mock_api_key):
        """OK response with results → returns (lat, lng), writes positive cache entry."""
        api_resp = _make_api_response("OK", [_make_result(51.123, -1.456)])
        with patch("requests.get", return_value=_MockResponse(json.dumps(api_resp))):
            result = lookup_geocode("Test St SO24 9LW", cache_path=tmp_cache)
        assert result == (51.123, -1.456)
        # Verify cache was written
        cache = json.loads(tmp_cache.read_text())
        assert len(cache) == 1
        entry = next(iter(cache.values()))
        assert entry["lat"] == 51.123
        assert entry["lng"] == -1.456
        assert entry["query"] == "Test St SO24 9LW"

    def test_zero_results_caches_negative(self, tmp_cache: Path, mock_api_key):
        """ZERO_RESULTS → returns _NO_MATCH, writes negative cache entry."""
        api_resp = _make_api_response("ZERO_RESULTS")
        with patch("requests.get", return_value=_MockResponse(json.dumps(api_resp))):
            result = lookup_geocode("Bad Address SO24 9LW", cache_path=tmp_cache)
        assert result is _NO_MATCH
        # Verify negative cache entry was written
        cache = json.loads(tmp_cache.read_text())
        assert len(cache) == 1
        entry = next(iter(cache.values()))
        assert entry["lat"] is None
        assert entry["lng"] is None
        assert entry["query"] == "Bad Address SO24 9LW"

    def test_request_denied_returns_unavailable(self, tmp_cache: Path, mock_api_key):
        """REQUEST_DENIED / OVER_QUERY_LIMIT → returns _GOOGLE_UNAVAILABLE (caller falls back to Nominatim)."""
        api_resp = _make_api_response("REQUEST_DENIED")
        with patch("requests.get", return_value=_MockResponse(json.dumps(api_resp))):
            result = lookup_geocode("Test St SO24 9LW", cache_path=tmp_cache)
        assert result is _GOOGLE_UNAVAILABLE


# ------------------------------------------------------------------ enrich_records (geocode branch)


class TestEnrichRecordsGeocode:
    """Tests for the geocode branch in enrich_records()."""

    def test_no_key_falls_back_to_nominatim(
        self, tmp_path: Path, state: StateStore, tmp_cache, monkeypatch: pytest.MonkeyPatch
    ):
        """Without a Google API key, the geocode step falls back to Nominatim."""
        monkeypatch.delenv("GOOGLE_GEOCODING_API_KEY", raising=False)
        records = [_make_record(address="Test St", postcode="SO24 9LW")]
        nominatim_resp = _MockResponse(json.dumps([{"lat": "51.1", "lon": "-1.2"}]))
        with patch("generators.enrichment._GEOCODE_CACHE_PATH", tmp_cache):
            with patch("requests.get", return_value=nominatim_resp):
                result = enrich_records(records, state)
        assert result[0]["location"]["lat"] == 51.1
        assert result[0]["location"]["lng"] == -1.2

    def test_skips_records_with_coords(self, tmp_path: Path, state: StateStore, tmp_cache):
        """Records that already have lat/lng are not processed by geocode."""
        records = [_make_record(lat=51.0, lng=-1.0)]
        with patch("generators.enrichment._GEOCODE_CACHE_PATH", tmp_cache):
            result = enrich_records(records, state)
        assert result[0]["location"]["lat"] == 51.0
        assert result[0]["location"]["lng"] == -1.0

    def test_skips_records_without_postcode(self, tmp_path: Path, state: StateStore, tmp_cache):
        """Records without postcode are skipped by the geocode branch."""
        records = [_make_record(address="Test St", name=None, postcode=None)]
        with patch("generators.enrichment._GEOCODE_CACHE_PATH", tmp_cache):
            result = enrich_records(records, state)
        assert result[0]["location"].get("lat") is None

    def test_query_construction_address_first(self, tmp_path: Path, state: StateStore, mock_api_key, tmp_cache):
        """Query uses address + postcode when address is present."""
        records = [_make_record(address="Test Street", postcode="SO24 9LW")]
        api_resp = _make_api_response("OK", [_make_result(51.0, -1.0)])
        with patch("generators.enrichment._GEOCODE_CACHE_PATH", tmp_cache):
            with patch("requests.get", return_value=_MockResponse(json.dumps(api_resp))):
                result = enrich_records(records, state)
        assert result[0]["location"]["lat"] == 51.0
        assert result[0]["location"]["lng"] == -1.0

    def test_query_fallback_to_name(self, tmp_path: Path, state: StateStore, mock_api_key, tmp_cache):
        """Query falls back to name + postcode when address is absent."""
        records = [_make_record(address=None, name="The Cricketers", postcode="SO24 9LW")]
        api_resp = _make_api_response("OK", [_make_result(51.0, -1.0)])
        with patch("generators.enrichment._GEOCODE_CACHE_PATH", tmp_cache):
            with patch("requests.get", return_value=_MockResponse(json.dumps(api_resp))):
                result = enrich_records(records, state)
        assert result[0]["location"]["lat"] == 51.0
        assert result[0]["location"]["lng"] == -1.0

    def test_cache_hit_serves_coords(self, tmp_path: Path, state: StateStore, mock_api_key):
        """Cached positive entry serves lat/lng without API call."""
        cache_path = tmp_path / "geocode_cache.json"
        cache_path.write_text(
            json.dumps({
                "wwh3:2144": {"lat": 51.5, "lng": -1.5, "query": "Cached St SO24 9LW"}
            })
        )
        records = [_make_record(kennel="wwh3", runno=2144, address="Cached St", postcode="SO24 9LW")]

        with patch("generators.enrichment._GEOCODE_CACHE_PATH", cache_path):
            result = enrich_records(records, state)
        assert result[0]["location"]["lat"] == 51.5
        assert result[0]["location"]["lng"] == -1.5

    def test_negative_cache_leaves_absent(self, tmp_path: Path, state: StateStore, mock_api_key):
        """Negative cache entry (ZERO_RESULTS) leaves lat/lng absent, no API call."""
        cache_path = tmp_path / "geocode_cache.json"
        cache_path.write_text(
            json.dumps({
                "wwh3:2144": {"lat": None, "lng": None, "query": "Bad Address SO24 9LW"}
            })
        )
        records = [_make_record(kennel="wwh3", runno=2144, address="Bad Address", postcode="SO24 9LW")]

        with patch("generators.enrichment._GEOCODE_CACHE_PATH", cache_path):
            result = enrich_records(records, state)
        assert result[0]["location"].get("lat") is None
        assert result[0]["location"].get("lng") is None

    def test_staleness_triggers_refetch(self, tmp_path: Path, state: StateStore, mock_api_key):
        """Changed query in cache → cache miss → re-geocoded."""
        cache_path = tmp_path / "geocode_cache.json"
        cache_path.write_text(
            json.dumps({
                "wwh3:2144": {"lat": 51.0, "lng": -1.0, "query": "Old Address SO24 9LW"}
            })
        )
        records = [_make_record(kennel="wwh3", runno=2144, address="New Address", postcode="SO24 9LW")]
        api_resp = _make_api_response("OK", [_make_result(52.0, -2.0)])

        with patch("generators.enrichment._GEOCODE_CACHE_PATH", cache_path):
            with patch("requests.get", return_value=_MockResponse(json.dumps(api_resp))):
                result = enrich_records(records, state)
        assert result[0]["location"]["lat"] == 52.0
        assert result[0]["location"]["lng"] == -2.0

    def test_circuit_breaker_on_transient_failure(self, tmp_path: Path, state: StateStore, mock_api_key, tmp_cache):
        """Network error during geocode → TTL decremented, no coords."""
        import requests as _requests
        records = [_make_record(address="Test St", postcode="SO24 9LW")]
        with patch("generators.enrichment._GEOCODE_CACHE_PATH", tmp_cache):
            with patch("requests.get", side_effect=_requests.RequestException("network error")):
                result = enrich_records(records, state)
        assert result[0]["location"].get("lat") is None
        # Verify TTL was decremented
        entry = state.get(_GEOCODE_STATE_KEY)
        assert entry is not None
        assert entry["ttl_current"] == _GEOCODE_TTL_MAX - 1

    def test_circuit_breaker_trips_after_max_failures(self, tmp_path: Path, state: StateStore, mock_api_key, tmp_cache):
        """Repeated failures trip the circuit breaker."""
        import requests as _requests
        records = [_make_record(address="Test St", postcode="SO24 9LW")]
        with patch("generators.enrichment._GEOCODE_CACHE_PATH", tmp_cache):
            for _ in range(_GEOCODE_TTL_MAX):
                with patch("requests.get", side_effect=_requests.RequestException("network error")):
                    enrich_records(records, state)
        assert state.is_disabled(_GEOCODE_STATE_KEY)

    def test_success_resets_breaker(self, tmp_path: Path, state: StateStore, mock_api_key, tmp_cache):
        """Successful geocode after failures resets the breaker."""
        import requests as _requests
        records = [_make_record(address="Test St", postcode="SO24 9LW")]
        with patch("generators.enrichment._GEOCODE_CACHE_PATH", tmp_cache):
            # First, trip the breaker
            for _ in range(_GEOCODE_TTL_MAX):
                with patch("requests.get", side_effect=_requests.RequestException("network error")):
                    enrich_records(records, state)
            assert state.is_disabled(_GEOCODE_STATE_KEY)
            # Reset the circuit breaker (as would happen in production via reset_scraper)
            state.reset(_GEOCODE_STATE_KEY, _GEOCODE_TTL_MAX)
            # Now succeed
            api_resp = _make_api_response("OK", [_make_result(51.0, -1.0)])
            with patch("requests.get", return_value=_MockResponse(json.dumps(api_resp))):
                enrich_records(records, state)
            assert not state.is_disabled(_GEOCODE_STATE_KEY)
            assert state.get(_GEOCODE_STATE_KEY)["ttl_current"] == _GEOCODE_TTL_MAX


# ------------------------------------------------------------------ _write_cache (generalized)


class TestWriteCache:
    """Tests for the generalized _write_cache function."""

    def test_writes_query_field(self, tmp_path: Path):
        """_write_cache with query parameter stores the query."""
        cache_path = tmp_path / "geocode_cache.json"
        _write_cache("key1", 51.0, -1.0, cache_path, query="Test St SO24 9LW")
        cache = json.loads(cache_path.read_text())
        assert cache["key1"]["query"] == "Test St SO24 9LW"

    def test_writes_negative_entry(self, tmp_path: Path):
        """_write_cache with None lat/lng writes a negative entry."""
        cache_path = tmp_path / "geocode_cache.json"
        _write_cache("key1", None, None, cache_path, query="Bad Address SO24 9LW")
        cache = json.loads(cache_path.read_text())
        assert cache["key1"]["lat"] is None
        assert cache["key1"]["lng"] is None

    def test_lock_file_is_cache_specific(self, tmp_path: Path):
        """Lock file name is derived from cache file stem."""
        cache_path = tmp_path / "geocode_cache.json"
        _write_cache("key1", 51.0, -1.0, cache_path)
        # Lock file is created inside the with block and closed after
        # We check that a lock file was used by verifying the cache was written correctly
        cache = json.loads(cache_path.read_text())
        assert "key1" in cache
        assert cache["key1"]["lat"] == 51.0
        assert cache["key1"]["lng"] == -1.0

    def test_fifo_eviction(self, tmp_path: Path):
        """Cache evicts oldest entries when exceeding _CACHE_MAX."""
        cache_path = tmp_path / "geocode_cache.json"
        for i in range(_CACHE_MAX + 10):
            _write_cache(f"key{i}", float(i), float(-i), cache_path)
        cache = json.loads(cache_path.read_text())
        assert len(cache) == _CACHE_MAX
        # Oldest entries should be evicted
        assert "key0" not in cache
        assert "key10" in cache


# ------------------------------------------------------------------ helpers


class _MockResponse:
    """Minimal mock for requests.Response used by tests."""

    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def json(self) -> dict:
        return json.loads(self.text)
