# GH3.md — Guildford Hash House Harriers Scraper Design
 
## Site Overview
 
| Key | Value |
|-----|-------|
| **Scraper name** | `gh3` |
| **Display name** | Guildford Hash House Harriers |
| **URL** | https://guildfordh3.org.uk |
| **Platform** | WordPress + EventOn 4.5.9 plugin |
| **Timezone** | Europe/London (BST = UTC+1, GMT = UTC+0) |
 
---
 
## Data Source
 
**Primary**: Homepage HTML — `https://guildfordh3.org.uk`
 
The calendar is **fully server-side rendered**. All upcoming events are present in the
raw HTML response. No JavaScript execution, authentication, or AJAX calls required.
 
**Do not use:**
- `wp-json/wp/v2/ajde_events` — does not return future events without auth
- `wp-json/eventon/v1/data` — internal plugin POST endpoint, unreliable
- Any AJAX/dynamic endpoint — unnecessary, data is already in page HTML
**Scope**: The homepage renders approximately **8 months** of upcoming events in a
single fetch (EventOn shortcode: `number_of_months="8"`).
 
---
 
## Extraction Strategy
 
Each event has two complementary sources in the page HTML:
 
### 1. JSON-LD block — `<script type="application/ld+json">`
 
Extract all blocks where `@type == "Event"`. Provides datetime and URL.
 
| JSON-LD field | Example value | Used for |
|---------------|---------------|----------|
| `@id` | `"event_6290_0"` | WP post ID: `split("_")[1]` |
| `name` | `"Guildford Hash House Harriers"` | **Not used** — static club name, not event data |
| `url` | `"https://guildfordh3.org.uk/events/2130-daring-alice/"` | → `website` |
| `startDate` | `"2026-6-15T19:30+1:00"` | → `date`, `time` |
| `endDate` | `"2026-6-15T20:45+1:00"` | Not mapped |
| `description` | `"<p>...What3Words: ///woods.lower.danger...</p>"` | → `location.w3s` |
 
### 2. DOM — `<span class="evcal_event_title">`
 
The event title (run number, hare name, location, postcode) is in the DOM, not
the JSON-LD. Each event card contains:
 
```html
<span class="evoet_title evcal_desc2 evcal_event_title" itemprop="name">
    2130 - Daring Alice - Newlands Corner car park (GU4 8SE)
</span>
```
 
This is the primary source for `runno`, `hares`, `location.name`, and
`location.postcode`.
 
**Correlating JSON-LD with DOM elements**: match on the WordPress event ID, which
appears in both:
- JSON-LD: `"@id": "event_6290_0"` → ID = `6290`
- DOM: `<div id="event_6290_0" class="eventon_list_event">`
Scrape both together by iterating `div.eventon_list_event` elements and reading
the JSON-LD from the `<script>` tag within each one.
 
---
 
## Title Parsing
 
GH3 event titles follow this structure:
```
"{runno} - {hare_name} - {location_name} ({postcode})"
```
 
Examples:
```
"2130 - Daring Alice - Newlands Corner car park (GU4 8SE)"
"2133 - Dr Pussy - 4th July Theme - The White House, Millmead (GU2 4AJ)"
"Midsummer Nightmare, Corfe Castle, Dorset"   ← special event, no run number
"Halloween"                                    ← special event, no run number
```
 
**Important**: Use `maxsplit=2` when splitting on ` - ` so that location names
containing ` - ` (e.g. `"4th July Theme - The White House, Millmead"`) are
preserved intact in segment 3.
 
```python
import re
 
def parse_title(title: str) -> dict:
    result = {}
 
    # Check for run number prefix
    match = re.match(r'^(\d{4})\s+-\s+(.+)$', title)
    if not match:
        # Special event — no run number
        return {"is_special": True, "raw_title": title}
 
    result["runno"] = int(match.group(1))
    remainder = match.group(2)  # "Daring Alice - Newlands Corner car park (GU4 8SE)"
 
    # Split hare name from location (maxsplit=1 on remainder)
    parts = remainder.split(" - ", maxsplit=1)
    result["hare"] = parts[0].strip()
 
    if len(parts) > 1:
        loc = parts[1].strip()
        # Extract postcode from end of location string
        pc_match = re.search(r'\(([A-Z]{1,2}\d{1,2}\s*\d[A-Z]{2})\)\s*$', loc)
        if pc_match:
            result["postcode"] = pc_match.group(1)
            loc = loc[:pc_match.start()].strip()
        result["location_name"] = loc
 
    return result
```
 
---
 
## Schema Field Mapping
 
| Schema field | Source | Transform |
|---|---|---|
| `name` | Static | `"Guildford Hash House Harriers"` |
| `runno` | DOM title | Regex leading integer |
| `date` | JSON-LD `startDate` | Parse to `YYYY-MM-DD` |
| `time` | JSON-LD `startDate` | Extract `HH:MM` |
| `location.name` | — | Not available |
| `location.postcode` | DOM title | Regex `(XX## #XX)` from title |
| `location.w3s` | JSON-LD `description` | Extract from `w3w.co/` link |
| `location.address` | — | Not available |
| `location.lat` | JSON-LD `description` | Parse from Waze `ll=` param |
| `location.lng` | JSON-LD `description` | Parse from Waze `ll=` param |
| `location.osgrid` | — | Not available |
| `hares` | DOM title | Middle segment, single-item list |
| `oninn` | — | Not available |
| `notes` | — | Not available |
| `website` | JSON-LD `url` | Direct |
 
---
 
## Example: Mapped Output
 
**Raw inputs:**
 
DOM title: `"2130 - Daring Alice - Newlands Corner car park (GU4 8SE)"`
 
JSON-LD:
```json
{
  "@type": "Event",
  "@id": "event_6290_0",
  "name": "Guildford Hash House Harriers",
  "url": "https://guildfordh3.org.uk/events/2130-daring-alice/",
  "startDate": "2026-6-15T19:30+1:00",
  "description": "<p><a href='https://w3w.co/woods.lower.danger'>///woods.lower.danger</a></p>"
}
```
 
**Mapped output record:**
```json
{
  "name": "Guildford Hash House Harriers",
  "runno": 2130,
  "date": "2026-06-15",
  "time": "19:30",
  "location": {
    "postcode": "GU4 8SE",
    "w3s": "woods.lower.danger",
    "lat": 51.23283538,
    "lng": -0.50674438
  },
  "hares": ["Daring Alice"],
  "website": "https://guildfordh3.org.uk/events/2130-daring-alice/"
}
```
 
---
 
## Skipping Non-Run Events
 
Any event title that does not begin with a **4-digit integer** followed by ` - ` is
**silently skipped** — not parsed, not written to output, no exception raised.
 
```python
if not re.match(r'^\d{4} - ', title):
    continue  # skip silently
```
 
Examples that are skipped:
- `"Midsummer Nightmare, Corfe Castle, Dorset"`
- `"Christmas r*n"`
- `"Burns Night"`
- `"Halloween"`
- `"Alternative Octoberfest"`
Log the skip at DEBUG level only.
 
---
 
## Date Parsing
 
`startDate` format is non-standard ISO 8601 — single-digit month/day, single-digit
timezone offset:
 
```
"2026-6-15T19:30+1:00"
```
 
Python's `datetime.fromisoformat()` fails on this below Python 3.11. Normalise first:
 
```python
import re
from datetime import datetime
 
def normalise_gh3_datetime(s: str) -> datetime:
    # Zero-pad month and day
    s = re.sub(r'(\d{4})-(\d{1,2})-(\d{1,2})',
               lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", s)
    # Zero-pad timezone offset: +1:00 → +01:00
    s = re.sub(r'([+-])(\d):', r'\g<1>0\2:', s)
    return datetime.fromisoformat(s)
 
def parse_date(start_date_str: str) -> str:
    return normalise_gh3_datetime(start_date_str).strftime("%Y-%m-%d")
 
def parse_time(start_date_str: str) -> str:
    return normalise_gh3_datetime(start_date_str).strftime("%H:%M")
```
 
---
 
## What Three Words Extraction
 
```python
from bs4 import BeautifulSoup
import re
 
def parse_w3s(description_html: str) -> str | None:
    if not description_html:
        return None
    soup = BeautifulSoup(description_html, "html.parser")
    for a in soup.find_all("a", href=True):
        if "w3w.co/" in a["href"]:
            slug = a["href"].split("w3w.co/")[-1].strip("/")
            if re.match(r'^[a-z]+\.[a-z]+\.[a-z]+$', slug):
                return slug
    return None
```
 
## Waze Lat/Lng Extraction
 
Some event descriptions contain a Waze link with coordinates in the `ll` query parameter:
 
```html
<a href='https://ul.waze.com/ul?ll=51.23283538%2C-0.50674438&navigate=yes&...'>Waze</a>
```
 
The `ll` value is `{lat}%2C{lng}` (URL-encoded comma). Not all events include a Waze
link — treat as optional.
 
```python
from urllib.parse import urlparse, parse_qs, unquote
from bs4 import BeautifulSoup
 
def parse_latlng(description_html: str) -> tuple[float, float] | tuple[None, None]:
    if not description_html:
        return None, None
    soup = BeautifulSoup(description_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "waze.com" in href and "ll=" in href:
            qs = parse_qs(urlparse(href).query)
            ll = qs.get("ll", [None])[0]
            if ll:
                parts = unquote(ll).split(",")
                if len(parts) == 2:
                    try:
                        return float(parts[0]), float(parts[1])
                    except ValueError:
                        pass
    return None, None
```
 
Usage:
```python
lat, lng = parse_latlng(description_html)
if lat is not None:
    location["lat"] = lat
    location["lng"] = lng
```
 
---
 
## Failure Mode Guidance
 
| Condition | Action |
|-----------|--------|
| HTTP non-200 | `ScraperException(FailureMode.TRANSIENT)` |
| Page loads but zero `div.eventon_list_event` found | `ScraperException(FailureMode.FATAL)` — site structure changed |
| Zero JSON-LD `Event` blocks found | `ScraperException(FailureMode.FATAL)` |
| Individual event missing `startDate` | Skip record, log warning |
| Title has no run number | Skip record (special event), no exception |
 
---
 
## Robots / Politeness
 
- No `robots.txt` restrictions on public event content
- Single HTTP GET retrieves all data — no pagination
- Do not fetch more than once per hour

---

## Regenerating synthetic test output

`map()` accepts an optional `url_expander` so tests resolve goo.gl map links from
a committed offline cache instead of calling the live service. (In practice GH3
coordinates usually come from Waze `ll=` params, so no goo.gl call is made — but
the hook keeps the test fully offline regardless.)

- `tests/fixtures/GH3/gmaps_expansions.json` caches short URL → full URL, tagged
  with a SHA-256 of `raw_response.html`. Editing the raw fixture invalidates the
  hash, and tests fail loudly until the cache is refreshed.
- Online, once (and whenever `raw_response.html` changes):
  `python scripts/regen_synthetic.py --capture gh3`
- Offline, to rebuild `tests/synthetic/gh3/output.json`:
  `python scripts/regen_synthetic.py gh3`