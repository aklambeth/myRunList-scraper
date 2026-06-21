# PLAN — Google Geocoding enrichment fallback

> Transient task tracker. Remove once merged.

## Context

WWH3 (and potentially other sites) publish venue `name`/`address`/`postcode` but **no
coordinates** — `venue.geo_lat`/`geo_lng` are always null and the detail page resolves
location only through a client-side Google Maps embed iframe (see
[docs/WWH3.md](./docs/WWH3.md)). There is no What3Words, so the existing W3W enrichment in
`generators/enrichment.py` cannot fill them.

This adds a **downstream Google Geocoding enrichment** that reassembles the embed's `q=`
string (`address + postcode`) and resolves lat/lng via the Google Geocoding API using our
own key — modelled directly on the existing W3W enrichment workaround.

## Decisions

- **Query** = full `address + postcode` (fall back to `name + postcode` when address absent).
- **Generic** — runs for all kennels, like the kennel-agnostic W3W step.
- **Cache key = `f"{kennel}:{runno}"`** (event identity, the W3W-triple equivalent).
- **Negative caching:** `ZERO_RESULTS` is cached as a negative entry so we never re-query an
  unresolvable address. Transient failures (network, `OVER_QUERY_LIMIT`, `REQUEST_DENIED`)
  are NOT cached and decrement the TTL breaker instead.
- **Staleness self-heal:** cache value stores the queried address; a changed query is a miss
  and re-geocodes (applies to positive and negative entries).
- **No key → skip entirely:** if `GOOGLE_GEOCODING_API_KEY` is unset, the geocode pass is
  skipped (log once at INFO) — no HTTP, no breaker change.

## Tasks

### 1. `generators/enrichment.py` (core)
- Generalize `_write_cache` lock path so W3W and geocode share the `flock` + atomic
  `os.replace` writer. Add `_GEOCODE_CACHE_PATH = data/geocode_cache.json`,
  `_GEOCODE_STATE_KEY = "enrich_geocode"`, `_GEOCODE_TTL_MAX = 5`, `_NO_MATCH = object()`.
- `lookup_geocode(query)` → `(lat,lng)` on `OK`, `_NO_MATCH` on `ZERO_RESULTS`, `None` on
  transient/network. Never raises.
- New geocode branch in `enrich_records`, after the W3W block: read key once (skip pass if
  absent); per record build `key`+`query`, cache-first with query match, then call lookup
  and cache/record-breaker per the three outcomes.

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
