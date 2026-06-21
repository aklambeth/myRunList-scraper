# WWH3.md — Worthy Winchester Hash House Harriers Scraper Design

## Site Overview

| Key | Value |
|-----|-------|
| **Scraper name** | `wwh3` |
| **Display name** | Worthy Winchester Hash House Harriers |
| **Platform** | WordPress + The Events Calendar (Tribe Events) + Event Espresso + Elementor |
| **Timezone** | Europe/London (BST = UTC+1, GMT = UTC+0) |

---

## Data Source

**Primary**: The Events Calendar REST API — a **single request**:

```
https://worthyh3.com/wp-json/tribe/events/v1/events?per_page=<MAX_RECORDS>&start_date=now
```

Returns a JSON object `{ "events": [...], "rest_url", "total", "total_pages" }`.
Each element of `events` is a **fully structured** event object — title, start
date/time, venue (name/address/postcode), organizers, and description — so one
request captures every field. **No HTML parsing and no per-event fetches.**

The API is advertised in the page head of any site page
(`<meta name="tec-api-version" content="v1">`,
`<link rel="alternate" href="https://worthyh3.com/wp-json/tribe/events/v1/" />`).

**Fixture**: `tests/fixtures/WWH3/raw_response.json` (captured response, 14
events, `total_pages: 1`). `tests/fixtures/WWH3/upcomming_events.html` is the
human-facing listing page, kept for reference only — **do not** scrape it: it is
title-only stubs paginated 7 pages deep and lacks date/venue/hare data.

`MAX_RECORDS` (default **50**) sets `per_page`. It is a named constant in the
scraper, not hardcoded inline, so the future-window can be widened with a
one-line change. The captured fixture's `total_pages` is `1`, so a single
request covers the full upcoming window.

> **Why not the SH3 strategy?** SH3 is Astra + Elementor and embeds the rendered
> detail HTML in `wp/v2/pages` `content.rendered`. WWH3 uses a *different*
> plugin (The Events Calendar) with a *different* endpoint that returns clean
> structured fields — so WWH3 needs no Elementor/BeautifulSoup parsing, no
> goo.gl resolution, and no What3Words handling.

---

## Extraction

Parse the response JSON. If it is not an object or lacks an `events` **list**,
raise `ScraperException(FailureMode.FATAL)` — the API or structure has changed.
An **empty** `events` list is **not** fatal (legitimate off-season) — return
`[]`.

All string values are passed through `html.unescape` (the API emits HTML
entities such as `&#8211;` for en-dash and `&#8217;` for apostrophe).

### Run number and date/time

- **`runno`** — parsed from `title` with `re.search(r"\bRun\s+(\d+)", title)`
  (e.g. `"Run 2139 – The Rising Sun, Colden Common"` → `2139`). There is no
  dedicated run-number field. If no match, skip the record and log a warning.
- **`date`** — `start_date[:10]` (`start_date` is `"YYYY-MM-DD HH:MM:SS"`).
- **`time`** — `start_date[11:16]` (`HH:MM`). Unlike SH3, a time **is**
  available (typically `18:30`).

### Hares

Hares are the event's **organizers** — `organizer` is a list of
`{organizer, slug, email, phone, website}` dicts, one per hare:

```json
"organizer": [{"organizer": "BTV"}, {"organizer": "Ram"}]
```

Map `hares = [html.unescape(o["organizer"]) for o in organizer if o.get("organizer")]`.
Omit `hares` when the list is empty.

### Location

From the `venue` object:

| Schema field | Source | Transform |
|---|---|---|
| `location.name` | `venue.venue` | omit when it equals `"TBC"` (placeholder) |
| `location.address` | `venue.address` + `venue.city` | join, strip trailing commas; omit if empty |
| `location.postcode` | `venue.zip` | direct |

### On on (oninn)

The `description` field is usually empty but occasionally carries the on-in,
e.g. `<p>OnOn &#8211; The Bunch of Grapes</p>`. Strip HTML tags, unescape, then
remove a leading `OnOn` / `On On` label and separator. Omit `oninn` if blank.

### Coordinates — not available at source

`venue.geo_lat` / `venue.geo_lng` are present as keys but are **always null**.
The detail page renders location only via a Google Maps **embed iframe** whose
`q=` is the place name + postcode (e.g.
`q=The+Cricketers+Alresford+SO24+9LW`) — the coordinates are resolved
client-side by Google and never appear in the page HTML. There is no
What3Words, so the existing W3W enrichment does not apply.

The scraper therefore:
- **Conditionally maps** `venue.geo_lat`/`geo_lng` → `location.lat`/`lng` (cast
  to `float`) **when both are non-null**, so coordinates flow through
  automatically if the club ever populates them at source. They are null today,
  so `exclude_none` omits them.
- Emits clean `name`/`address`/`postcode` so that a **downstream geocoding
  enrichment** (future, separate change) can assemble the same `q=` string the
  embed uses and resolve `lat`/`lng` via the Google Geocoding API using **our
  own** API key — analogous to the W3W enrichment workaround. See
  `CLAUDE.md` → Location Enrichment.

---

## Placeholders / unfilled events

Not-yet-arranged future runs are published as placeholders with `venue.venue ==
"TBC"`, no `zip`/`address`, and an empty `organizer` list (e.g. `Run 2141 –
TBC`, `Run 2152 – Darkness Returns`).

**Detection & handling:** in `map()`, skip the record (log at DEBUG) when the
venue name is absent or equals `"TBC"` (case-insensitive) **and** there is no
postcode. This is an explicit skip — matching SH3's placeholder approach rather
than relying solely on downstream filtering. In the captured fixture this drops
runs **2141, 2143, 2145, 2149, 2152** (5 of 14), leaving 9 real runs.

Past-dated survivors are additionally filtered by `BaseScraper.run()`
(`scrapers/base.py:149`).

---

## Schema Field Mapping

| Schema field | Source | Transform |
|---|---|---|
| `name` | static | `"Worthy Winchester Hash House Harriers"` |
| `kennel` | static | `"wwh3"` |
| `runno` | `title` | `re.search(r"\bRun\s+(\d+)", title)` → `int` |
| `date` | `start_date` | first 10 chars (`YYYY-MM-DD`) |
| `time` | `start_date` | chars 11–16 (`HH:MM`) |
| `location.name` | `venue.venue` | unescape; omit if `"TBC"` |
| `location.address` | `venue.address` + `venue.city` | join, strip trailing commas |
| `location.postcode` | `venue.zip` | direct |
| `location.lat` / `lng` | `venue.geo_lat` / `geo_lng` | `float` when both non-null; else omitted (downstream geocode) |
| `location.osgrid` / `w3s` | — | not available |
| `oninn` | `description` | strip tags, drop `OnOn` label; omit if blank |
| `hares` | `organizer[].organizer` | unescape each; omit if empty |
| `notes` | — | not available |
| `website` | `url` | direct (the `website` field is empty) |

---

## Example: Mapped Output

**Source event (id 1223, run 2144):** title `Run 2144 – The Cricketers, Jacklyns
Lane, Alresford,` · `start_date 2026-07-27 18:30:00` · venue `The Cricketers,
Alresford` / `SO24 9LW` · organizers `Plum Rod`, `Pushover`.

```json
{
  "name": "Worthy Winchester Hash House Harriers",
  "kennel": "wwh3",
  "runno": 2144,
  "date": "2026-07-27",
  "time": "18:30",
  "location": {
    "name": "The Cricketers, Alresford",
    "postcode": "SO24 9LW"
  },
  "hares": ["Plum Rod", "Pushover"],
  "website": "https://worthyh3.com/event/run-2144-the-cricketers-jacklyns-lane-alresford"
}
```

---

## Failure Mode Guidance

| Condition | Action |
|-----------|--------|
| HTTP non-200 | handled by `BaseScraper.fetch()` → `TRANSIENT` / `AUTH` |
| Response not valid JSON | `ScraperException(FailureMode.TRANSIENT)` |
| Response not an object / no `events` list | `ScraperException(FailureMode.FATAL)` — structure changed |
| Empty `events` list | return `[]` (legitimate off-season, not an error) |
| An event with no parseable `Run <n>` title | skip that record, log warning |

---

## Robots / Politeness

- Public REST endpoint; no authentication or API key required.
- One GET retrieves all run data (`per_page=MAX_RECORDS`); no per-event or
  coordinate-resolution requests.
- Do not fetch more than once per hour.

---

## Regenerating synthetic test output

`map()` is a pure function of the raw JSON — no network, no injected expander.
Rebuild `tests/synthetic/wwh3/output.json` by running `map()` against
`tests/fixtures/WWH3/raw_response.json` (e.g. via `scripts/regen_synthetic.py
wwh3` if/when wired in, or a one-off script). Re-capture `raw_response.json`
from the live API whenever the fixture needs refreshing.
