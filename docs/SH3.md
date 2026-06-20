# SH3.md — Surrey Hash House Harriers Scraper Design

## Site Overview

| Key | Value |
|-----|-------|
| **Scraper name** | `sh3` |
| **Display name** | Surrey Hash House Harriers |
| **Platform** | WordPress + Astra theme + Elementor page builder |
| **Timezone** | Europe/London (BST = UTC+1, GMT = UTC+0) |

---

## Data Source

**Primary**: WordPress REST API — a **single request**:

```
https://surreyhashhouseharriers.com/wp-json/wp/v2/pages?search=trail&orderby=date&order=desc&per_page=<MAX_RECORDS>
```

Returns a JSON array of page objects. Each object's **`content.rendered`** holds the complete
rendered detail-page HTML (the same Elementor widgets a browser would render at
`/trail-<runno>-<day>-<month>/`), so one request captures every field — no per-trail fetches.

**Fixture**: `tests/fixtures/SH3/raw_response.json` (captured response).
`tests/fixtures/SH3/43250.html` is a single rendered detail page, kept for reference only.

`MAX_RECORDS` (default **50**) sets `per_page`. It is a named constant in the scraper, not
hardcoded inline, so the future-window can be widened with a one-line change. (The captured
fixture used `per_page=20`; `per_page` only affects the live request URL, not fixture parsing.)

**Do not use:**
- The `/receding-hareline/` listing page HTML — superseded by this API (it lacks W3W,
  postcode, on-on, and per-run map links).
- The SEO meta description — truncated.
- Per-trail detail-page fetches — unnecessary, the content is already embedded in the API.

---

## Filtering page types

`search=trail` returns **two** page types; keep only real trails:

| Slug pattern | Meaning | Action |
|---|---|---|
| `trail-<runno>-<day>-<month>` | Upcoming/scheduled trail | **keep** |
| `rs<runno>` | "The Runday Shag" past-run report newsletter (different structure) | **skip** |

Filter: slug matches `^trail-\d+-`. If **zero** trail pages are found, raise
`ScraperException(FailureMode.FATAL)` — the API or page structure has changed.

> **Ordering caveat:** `orderby=date` is the WordPress **publish** date, not the run date, so
> future runs are **not contiguous** in the response (e.g. `trail-2637` 9 Aug was published
> 2026-05-02 and appears near the end). Do **not** stop at the first past date — parse all
> fetched records. `BaseScraper.run()` already drops past-dated and location-less records
> (`scrapers/base.py:148-150`), so the scraper's `map()` returns every parsed trail and lets
> the base filter the window.

---

## Extraction

Parse each kept page's `content.rendered` with BeautifulSoup. The detail page is a set of
Elementor **heading** label/value pairs plus **button** links:

```
Trail no:   2631, 28 June 2026
Hare(s):    Eskimo Nell & Eveready (again)
From:       St Martins Walk car park, Mill Lane, Dorking RH4 1DX
On on:      TBD (so many to choose from – make sure you tell Bonn Bugle!)
[buttons]   Map link to Start -> https://maps.app.goo.gl/72NnD5wBTwQ5knSJA
            What3Words        -> https://w3w.co/fantastic.shiny.pack
```

Build `{label-without-colon: next-widget-text}` pairs from the heading/text-editor widgets,
and `{button-text: href}` from the Elementor button anchors.

### Run number and date

The "Trail no" value is `"<runno>, <date>"`. Split on the first `,`:
- **`runno`** = left side → `int`.
- **`date`** = right side. Usually `DD Month YYYY` (`%d %B %Y`). **The year may be missing**
  (some not-yet-filled future trails read e.g. `19 July`). Fallback: parse `DD Month` and infer
  the year from the page's `date` (publish) field — use the publish year, and if the resulting
  run date is more than a few weeks *before* the publish date, add one year (handles year-end
  wrap where a run published in December is for the following January).

### Hare(s)

The "Hare(s)" value can list multiple names joined by **any of** `&`, `/`, or `,` (the data is
inconsistent). Split on `re.split(r'\s*[&/,]\s*', value)`, strip each part, drop empties.
Names are otherwise kept verbatim (e.g. `Eveready (again)`, `Dr. Death`).

### Location

"From" value = start location, with a UK postcode usually at the end:
- **`location.postcode`**: `re.search(r'\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\s*$', from_value)`.
- **`location.name`**: the "From" value with the trailing postcode (and trailing comma) removed.

### Coordinates — compressed Google Maps URL

The "Map link to Start" button is a shortened `maps.app.goo.gl/...` URL. Resolve coords with
the shared helpers in **`scrapers/geo.py`** (the same approach GH3 uses):
- `expand_gmaps_short_url(href)` — follows the redirect to the full Google Maps URL.
- `parse_latlng_from_gmaps_url(expanded)` — regex `/@(-?\d+\.\d+),(-?\d+\.\d+),` → `(lat, lng)`.

> This adds **one HEAD request per trail** that has a real start map link. Make the expander
> injectable so tests run offline. `location.w3s` is also captured and remains a fallback
> coordinate source via the enrichment pipeline (`generators/enrichment.py`).

### What Three Words

"What3Words" button `https://w3w.co/<x.y.z>` → `location.w3s` = the slug, validated against
`W3S_PATTERN` (reused from `models/run.py`, as GH3 does).

### On on (oninn)

The "On on" value is the single text-editor widget following the `On on:` heading (the map-link
buttons are separate sibling widgets, read independently — see Coordinates). Its text is messy
and can span **multiple lines**; for now take only the **first non-empty line**
(`get_text("\n")` → split `\n` → first stripped non-empty line). Omit `oninn` if that line is a
placeholder (`x, x, x, ...`). On on exists on **trail pages only** — the only type processed.

---

## Placeholders / unfilled trails

Not-yet-arranged future trails are published as templates with placeholder values
(e.g. `x, x, x, GUx xxx` in the From and On on fields). These records must be **detected and
skipped explicitly in `map()`** — do not emit them and rely on downstream filtering.

**Detection rule:** if the "From" value matches the placeholder pattern (no valid UK postcode
extractable *and* the raw text contains the `x, x, x` template), skip the record entirely and
log at DEBUG level. This is the clearest signal — a trail without a real start location is not
ready to publish.

The individual field handling for any value that slips through:

| Field | Placeholder seen | Handling |
|---|---|---|
| What3Words | `https://w3w.co/#` (fails `W3S_PATTERN`) | omit `location.w3s` |
| Map link to Start | `#` (not a `maps.app.goo.gl` URL) | skip expansion, no lat/lng |
| On on | `x, x, x, GUx xxx` | omit `oninn` |

---

## Schema Field Mapping

| Schema field | Source | Transform |
|---|---|---|
| `name` | static | `"Surrey Hash House Harriers"` |
| `kennel` | static | `"sh3"` |
| `runno` | "Trail no" value, left of `,` | `int` |
| `date` | "Trail no" value, right of `,` | `%d %B %Y`; infer year from publish `date` if absent |
| `time` | — | not available |
| `location.name` | "From" value minus trailing postcode | omit if placeholder |
| `location.postcode` | "From" value | UK postcode regex at end |
| `location.lat` / `lng` | "Map link to Start" button | expand + parse via `scrapers/geo.py` |
| `location.w3s` | "What3Words" button | slug, validated against `W3S_PATTERN` |
| `location.osgrid` | — | not available |
| `oninn` | "On on" value | omit if placeholder |
| `hares` | "Hare(s)" value | split on `[&/,]`, strip, drop empties |
| `notes` | — | not available |
| `website` | page `link` field | direct |

---

## Example: Mapped Output

**Source page (id 43250, run 2631):** `content.rendered` →
`Trail no: 2631, 28 June 2026` · `Hare(s): Eskimo Nell & Eveready (again)` ·
`From: St Martins Walk car park, Mill Lane, Dorking RH4 1DX` ·
What3Words → `w3w.co/fantastic.shiny.pack` · Map link to Start → `maps.app.goo.gl/72NnD5wBTwQ5knSJA`.

```json
{
  "name": "Surrey Hash House Harriers",
  "kennel": "sh3",
  "runno": 2631,
  "date": "2026-06-28",
  "location": {
    "name": "St Martins Walk car park, Mill Lane, Dorking",
    "postcode": "RH4 1DX",
    "w3s": "fantastic.shiny.pack",
    "lat": 51.23,
    "lng": -0.33
  },
  "hares": ["Eskimo Nell", "Eveready (again)"],
  "oninn": "TBD (so many to choose from – make sure you tell Bonn Bugle!)",
  "website": "https://surreyhashhouseharriers.com/trail-2631-28-june/"
}
```

*(lat/lng shown illustratively — resolved at runtime from the expanded Maps URL.)*

---

## Failure Mode Guidance

| Condition | Action |
|-----------|--------|
| HTTP non-200 | handled by `BaseScraper.fetch()` → `TRANSIENT` / `AUTH` |
| Response not valid JSON | `ScraperException(FailureMode.TRANSIENT)` |
| Zero `trail-*` pages in response | `ScraperException(FailureMode.FATAL)` — structure changed |
| A page missing "Trail no" / unparseable date | skip that record, log warning |
| Map short-URL expansion fails | leave lat/lng unset; W3W enrichment can fill them |

---

## Robots / Politeness

- Public REST endpoint; no authentication or API key required.
- One GET retrieves all run data (`per_page=MAX_RECORDS`); coordinate resolution adds one
  HEAD request per trail with a real start map link.
- Do not fetch more than once per hour.

---

## Regenerating synthetic test output

`map()` accepts an optional `url_expander`. In production (`url_expander=None`)
it expands goo.gl start-map links live and concurrently. Tests and synthetic
regeneration inject an offline expander so no live call is made.

- `tests/fixtures/SH3/gmaps_expansions.json` caches short URL → full URL, tagged
  with a SHA-256 of `raw_response.json`. Editing the raw fixture invalidates the
  hash, and tests fail loudly until the cache is refreshed.
- Online, once (and whenever `raw_response.json` changes):
  `python scripts/regen_synthetic.py --capture sh3`
- Offline, to rebuild `tests/synthetic/sh3/output.json`:
  `python scripts/regen_synthetic.py sh3`
