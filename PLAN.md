# PLAN — Shared geo helpers + SH3 (Surrey H3) scraper

> Transient task tracker. Remove once both tasks are merged.

## Context

SH3 (Surrey Hash House Harriers) is a WordPress + Elementor site. The WordPress REST API
returns every trail page with its **full detail content embedded** in `content.rendered`, so a
**single request** captures all run data (run no, date+year, hares, start location + postcode,
on-on, What3Words, and a compressed Google Maps start link):

```
https://surreyhashhouseharriers.com/wp-json/wp/v2/pages?search=trail&orderby=date&order=desc&per_page=<MAX_RECORDS>
```

Coordinates need the same Google-Maps-short-URL expansion that GH3 already implements. Those
helpers currently live in `scrapers/sites/gh3.py` and must be shared before SH3 can reuse them.
The work is **two sequential tasks**: (1) refactor the geo helpers into a shared module;
(2) build the SH3 scraper. Each task is done when its tests pass; Task 2 additionally must
return expected data from `python3 run.py --dry-run --site sh3`.

Detailed SH3 scraper strategy lives in [docs/SH3.md](./docs/SH3.md).

Fixtures captured: `tests/fixtures/SH3/raw_response.json` (the wp-json response),
`tests/fixtures/SH3/43250.html` (one detail page, reference only).

---

## Task 1 — Extract Google Maps helpers into a shared module

Move `expand_gmaps_short_url()` and `parse_latlng_from_gmaps_url()` out of
`scrapers/sites/gh3.py` into a shared module so multiple scrapers can use them.

**Shape:** module of plain functions (idiomatic Python for stateless helpers; matches existing
codebase style — `BaseScraper` is a class because it carries state, these helpers do not).

- [ ] **New `scrapers/geo.py`** with the two functions (moved verbatim from `gh3.py`):
  - `expand_gmaps_short_url(url) -> str | None` — `requests.head(url, allow_redirects=True,
    timeout=5)`, returns `r.url`; `None` on `requests.RequestException`.
  - `parse_latlng_from_gmaps_url(url) -> tuple[float, float] | tuple[None, None]` — regex
    `/@(-?\d+\.\d+),(-?\d+\.\d+),` → `(lat, lng)`, else `(None, None)`. Keep the 2-tuple return
    (callers unpack `lat, lng = ...`); only the type hint is tightened vs the bare gh3 version.
- [ ] **Edit `scrapers/sites/gh3.py`:** remove the two local defs; add
  `from scrapers.geo import expand_gmaps_short_url, parse_latlng_from_gmaps_url`. `parse_latlng()`
  stays in gh3 (default `url_expander=expand_gmaps_short_url`) and keeps working unchanged.
- [ ] **New `tests/test_geo.py`:** unit-test `parse_latlng_from_gmaps_url` (a `/@51.23,-0.50,`
  URL and a no-match URL); test `expand_gmaps_short_url` with `requests.head` mocked (no network).
- [ ] **Edit `CLAUDE.md`:** document the shared-helper convention —
  - add `scrapers/geo.py` to the Project Structure tree
    (`← shared geo helpers: Google Maps short-URL expansion, lat/lng parsing`)
  - add a line to "Adding a New Scraper" pointing site scrapers at `scrapers/geo.py` for
    coordinate/Maps helpers instead of writing their own.

**Gate:** `pytest tests/test_geo.py tests/test_gh3.py` green. (`test_gh3.py` injects
`url_expander` and imports only `parse_latlng`, so it is unaffected by the move.)

---

## Task 2 — Implement the SH3 scraper  (detail: [docs/SH3.md](./docs/SH3.md))

Depends on Task 1. Follows CLAUDE.md "Adding a New Scraper".

**Data flow:** single wp-json GET → `map()` parses JSON → keep slugs matching `^trail-\d+-`
(skips `rs*` "Runday Shag" run-report pages) → parse each `content.rendered`.
`BaseScraper.run()` already drops past dates (`base.py:148`) and location-less records, so
`map()` returns **all** parsed trail records without its own future-date filtering.

**`MAX_RECORDS` constant** (default `50`) drives `per_page` — not hardcoded inline, so the
window can be widened by changing one value. (API orders by *publish* date, not run date, so
future runs aren't contiguous; we fetch the capped set and let the base date-filter keep the
future ones.)

- [ ] **New `scrapers/sites/sh3.py`** — `SH3Scraper(BaseScraper)`, `name="sh3"`,
  `version="1.0.0"`, `url` = wp-json endpoint with `per_page=MAX_RECORDS`. `map()` parses
  JSON, filters `trail-*` slugs (FATAL if none), parses each `content.rendered` for the fields
  in the docs/SH3.md mapping table; lat/lng via `scrapers/geo.py`; expander injectable for tests.
  Note: `hares` splits on any of `&` `/` `,` (the field uses inconsistent separators).
- [ ] **Edit `config.yaml`:** add `sh3` site entry (`name`, `display_name`,
  `scraper: SH3Scraper`, `ttl_max: 5`, `enabled: true`). No `.env` key — endpoint is public.
- [ ] **Rewrite `docs/SH3.md`** for the wp-json strategy (done as part of this work).
- [ ] **`tests/synthetic/sh3/output.json`** — expected mapped output for `trail-*` fixture
  records (e.g. 2631 → `2026-06-28`, hares `["Eskimo Nell","Eveready"]`, postcode `RH4 1DX`,
  w3s `fantastic.shiny.pack`, website `.../trail-2631-28-june/`).
- [ ] **`tests/test_sh3.py`** — load fixture, run `map()` with a stub `url_expander` (returns a
  known `/@lat,lng,` URL) for deterministic offline lat/lng; assert against synthetic output;
  assert `rs*` pages excluded.

**Gate:** `pytest tests/test_sh3.py` green, then `python3 run.py --dry-run --site sh3` returns
the expected SH3 run records.

CLAUDE.md already lists the `sh3` row in the Site Strategy Documents table — no change needed.
