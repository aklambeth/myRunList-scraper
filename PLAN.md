# PLAN — Google Geocoding enrichment fallback

> Transient task tracker. Remove once merged.

## Context

WWH3 (and potentially other sites) publish venue `name`/`address`/`postcode` but **no
coordinates** — `venue.geo_lat`/`geo_lng` are always null and the detail page resolves
location only through a client-side Google Maps embed iframe (see
[docs/WWH3.md](./docs/WWH3.md)). There is no What3Words, so the existing W3W enrichment in
`generators/enrichment.py` cannot fill them.

This adds a **downstream geocoding enrichment** that reassembles the embed's `q=` string
(`address + postcode`) and resolves lat/lng via the **Google Geocoding API** (our key),
**falling back to keyless Nominatim / OpenStreetMap** when Google is unavailable — modelled
on the existing W3W enrichment workaround.

## Decisions

- **Query** = full `address + postcode` (fall back to `name + postcode` when address absent).
- **Generic** — runs for all kennels, like the kennel-agnostic W3W step.
- **Cache** = shared `data/geocode_cache.json`, one entry per event keyed `kennel:runno`
  (Google and Nominatim share the key); honoured while the stored `query` matches, else
  re-geocoded in place.
- **Negative caching:** `ZERO_RESULTS` / empty result is cached as a negative entry so we
  never re-query an unresolvable address. Transient (network) failures are NOT cached.
- **Staleness self-heal:** cache value stores the query; a changed query is a miss and
  re-geocodes (positive and negative entries).
- **Nominatim fallback (not skip):** when `GOOGLE_GEOCODING_API_KEY` is unset, Google returns
  `REQUEST_DENIED` / `OVER_QUERY_LIMIT`, or the Google breaker is disabled, the step falls
  back to Nominatim so enrichment works with no key configured.
- **Two breakers:** `enrich_geocode` (Google) and `enrich_nominatim` (Nominatim), each
  `ttl_max=5`, decremented on transient failures only.

## Tasks

### 1. `generators/enrichment.py` (core)
- Generalize `_write_cache` (lock path derived from cache filename; optional `query` field)
  so W3W, Google and Nominatim share the `flock` + atomic `os.replace` writer. Add
  `_GEOCODE_CACHE_PATH`, breaker keys `enrich_geocode` / `enrich_nominatim` (`ttl_max=5`),
  and the `_NO_MATCH` / `_GOOGLE_UNAVAILABLE` sentinels.
- `lookup_geocode(query)` → `(lat,lng)` on `OK`, `_NO_MATCH` on `ZERO_RESULTS`,
  `_GOOGLE_UNAVAILABLE` on no-key / `REQUEST_DENIED` / `OVER_QUERY_LIMIT`, `None` on
  network error. `lookup_nominatim(query)` → `(lat,lng)` / `_NO_MATCH` / `None`. Never raise.
- Geocode branch in `enrich_records`, after the W3W block: per record build `query`,
  cache-first by query match, try Google, then fall back to Nominatim when Google is
  unavailable or its breaker trips.

### 2. `generate.py`
- Add `load_dotenv(override=True)` so the key is available on the CLI path (MCP already does).

### 3. Config + docs
- `.env.example` / `.env`: add `GOOGLE_GEOCODING_API_KEY=` (shared enrichment key).
- `CLAUDE.md` → Location Enrichment: add Google Geocoding fallback to the chain + subsection.
- `README.md` → Environment variables: document the optional key.
- `docs/WWH3.md`: flip the coordinates note from "future" to "implemented".
- `.gitignore`: add `data/geocode_cache.json`.

### 4. Tests — `tests/test_enrichment_geocode.py` (offline)
Cache hit, negative cache, transient-vs-no-match, staleness, no-key skip, query construction.

## Verification

1. `pytest tests/test_enrichment_geocode.py -v` and full `pytest` (no regressions).
2. No key: `run.py --site wwh3` + `generate.py --json` → WWH3 records without lat/lng,
   INFO "geocoding skipped" logged, breaker untouched.
3. With key: coords populated, `data/geocode_cache.json` written, second pass cache-served.
4. Repeated failures trip `enrich_geocode` in `state/state.json`; W3W unaffected.
