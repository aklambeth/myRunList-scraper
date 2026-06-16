# CHI3.md — Chichester Hash House Harriers Scraper Design

## Site Overview

| Key | Value |
|-----|-------|
| **Scraper name** | `chi3` |
| **Display name** | Chichester Hash House Harriers |
| **URL** | https://www.chihhh.org.uk/diary.php |
| **Platform** | Static PHP site |
| **Timezone** | Europe/London (BST = UTC+1, GMT = UTC+0) |

---

## Data Source

**Primary**: Run diary page — `https://www.chihhh.org.uk/diary.php`

The run list is a static HTML table rendered server-side in the page response. No
JavaScript execution, authentication, or AJAX calls required.

**Do not use:**
- Any other page on the domain — `diary.php` is the authoritative run list

**Scope**: All upcoming runs currently configured in the diary. Based on observed
data, this is typically 6–12 future runs.

---

## Extraction Strategy

The page contains a single `<table>` with a multi-row header and data rows. The
header occupies the first row and defines nine columns:

```
Run | Date | Hare(s) | Venue | MapRef | 1:50000 | 1:25000 | 1:10000 | More
```

Data rows fall into two types:

### Complete records (9 columns)

All fields populated. Column 6 (index 5, `1:50000`) contains an OSMaps link with
`lat` and `lon` query parameters. Columns 7–9 are duplicates at different zoom
levels and are ignored.

```html
<tr>
  <td>Run 1088</td>
  <td>2026-06-21 11:00</td>
  <td>Visit: Deepcut Hash. Hares: Yorkie &amp; Yellow Peril</td>
  <td>Bordon Hogmoor Inclosure</td>
  <td>SU786353</td>
  <td><a href="https://explore.osmaps.com/pin?lat=51.111908&amp;lon=-0.878378&amp;zoom=10">...</a></td>
  <td>...</td>
  <td>...</td>
  <td>...</td>
</tr>
```

### Incomplete records (fewer than 9 columns — `colspan` rows)

Columns 4–9 are merged into a single `colspan` cell containing a placeholder
message (e.g. `see <a href=latest.php>latest</a>`). These records have no venue,
map ref, or coordinates.

**Skip incomplete records entirely** — do not write them to output, do not raise
an exception.

```python
from bs4 import BeautifulSoup

def extract_rows(html: str) -> list[BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    complete = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) == 9:
            complete.append(tds)
    return complete
```

> **Note**: The `<th>` header row and all `colspan` rows are automatically excluded
> by the `len(tds) == 9` guard. No special header-skipping logic is required.

---

## Column Mapping

| Index | Header | Content | Used |
|-------|--------|---------|------|
| 0 | Run | `"Run 1088"` | Yes — run number |
| 1 | Date | `"2026-06-21 11:00"` | Yes — date + time |
| 2 | Hare(s) | Hare name(s), sometimes prefixed | Yes — hares, notes |
| 3 | Venue | Location name | Yes — `location.name` |
| 4 | MapRef | OS grid ref, e.g. `SU786353` | Yes — `location.osgrid` |
| 5 | 1:50000 | OSMaps link with `lat`/`lon` params | Yes — `location.lat`, `location.lng` |
| 6 | 1:25000 | Duplicate OSMaps link (different zoom) | Ignored |
| 7 | 1:10000 | Duplicate OSMaps link (different zoom) | Ignored |
| 8 | More | Internal maps link | Ignored |

---

## Field Parsing

### Run number (column 0)

```python
def parse_runno(cell: str) -> int:
    # "Run 1088" → 1088
    return int(cell.strip().split()[-1])
```

### Date and time (column 1)

Format is `YYYY-MM-DD HH:MM`.

```python
from datetime import datetime

def parse_datetime(cell: str) -> tuple[str, str]:
    dt = datetime.strptime(cell.strip(), "%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
```

### Hare(s) (column 2)

The hare cell sometimes includes a visit annotation prefix (e.g.
`"Visit: Deepcut Hash. Hares: Yorkie & Yellow Peril"`). When a `"Hares:"` label
is present, extract only the portion after it. Otherwise use the full cell text
as the hare string.

The prefix text before `"Hares:"` (e.g. `"Visit: Deepcut Hash."`) is moved to
`notes`.

```python
import re

def parse_hares(cell: str) -> dict:
    result = {}
    cell = cell.strip()

    if "Hares:" in cell:
        parts = cell.split("Hares:", 1)
        notes_prefix = parts[0].strip().rstrip(".")
        if notes_prefix:
            result["notes"] = notes_prefix
        hare_str = parts[1].strip()
    else:
        hare_str = cell

    # Split on " & ", " and ", or ", "
    names = re.split(r'\s*&\s*|\s+and\s+|,\s*', hare_str)
    names = [n.strip() for n in names if n.strip()]
    if names:
        result["hares"] = names

    return result
```

### Venue / location name (column 3)

```python
def parse_venue(cell: str) -> str | None:
    v = cell.strip()
    return v if v else None
```

### OS grid ref (column 4)

```python
def parse_osgrid(cell: str) -> str | None:
    v = cell.strip()
    return v if v else None
```

### Lat/lng from OSMaps link (column 5)

Extract `lat` and `lon` query parameters from the first `<a href>` in the cell.

```python
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup

def parse_latlng(td) -> tuple[float, float] | tuple[None, None]:
    a = td.find("a", href=True)
    if not a:
        return None, None
    href = a["href"]
    if "explore.osmaps.com" not in href:
        return None, None
    qs = parse_qs(urlparse(href).query)
    try:
        lat = float(qs["lat"][0])
        lon = float(qs["lon"][0])
        return lat, lon
    except (KeyError, ValueError, IndexError):
        return None, None
```

---

## Schema Field Mapping

| Schema field | Source | Transform |
|---|---|---|
| `name` | Static | `"Chichester Hash House Harriers"` |
| `runno` | Column 0 | Strip `"Run "` prefix, parse as int |
| `date` | Column 1 | Parse `YYYY-MM-DD HH:MM` → `YYYY-MM-DD` |
| `time` | Column 1 | Parse `YYYY-MM-DD HH:MM` → `HH:MM` |
| `location.name` | Column 3 | Direct string |
| `location.osgrid` | Column 4 | Direct string |
| `location.lat` | Column 5 | Extract from OSMaps `lat=` param |
| `location.lng` | Column 5 | Extract from OSMaps `lon=` param |
| `location.postcode` | — | Not available |
| `location.address` | — | Not available |
| `location.w3s` | — | Not available |
| `hares` | Column 2 | Split on `&`, `and`, `,`; strip `"Hares:"` prefix if present |
| `notes` | Column 2 | Text before `"Hares:"` label, if present |
| `oninn` | — | Not available |
| `website` | Static | `"https://www.chihhh.org.uk"` |

---

## Example: Mapped Output

**Raw row (complete record):**
```html
<td>Run 1088</td>
<td>2026-06-21 11:00</td>
<td>Visit: Deepcut Hash. Hares: Yorkie &amp; Yellow Peril</td>
<td>Bordon Hogmoor Inclosure</td>
<td>SU786353</td>
<td><a href="https://explore.osmaps.com/pin?lat=51.111908&amp;lon=-0.878378&amp;zoom=10">...</a></td>
...
```

**Mapped output record:**
```json
{
  "name": "Chichester Hash House Harriers",
  "runno": 1088,
  "date": "2026-06-21",
  "time": "11:00",
  "location": {
    "name": "Bordon Hogmoor Inclosure",
    "osgrid": "SU786353",
    "lat": 51.111908,
    "lng": -0.878378
  },
  "hares": ["Yorkie", "Yellow Peril"],
  "notes": "Visit: Deepcut Hash",
  "website": "https://www.chihhh.org.uk"
}
```

**Skipped row (incomplete — `colspan`):**
```html
<td>Run 1089</td>
<td>2026-07-05 11:00</td>
<td>Bika</td>
<td colspan=6> see <a href=latest.php>latest</a></td>
```
→ Silently skipped (fewer than 9 `<td>` cells). Log at DEBUG level.

---

## Failure Mode Guidance

| Condition | Action |
|-----------|--------|
| HTTP non-200 | `ScraperException(FailureMode.TRANSIENT)` |
| Page loads but no `<table>` found | `ScraperException(FailureMode.FATAL)` — site structure changed |
| Table found but zero complete (9-column) rows | `ScraperException(FailureMode.TRANSIENT)` — may be temporarily empty |
| Run number cell cannot be parsed as integer | Skip row, log warning |
| Date cell cannot be parsed | Skip row, log warning |
| OSMaps link missing or malformed | Omit `lat`/`lng`, continue |

---

## Robots / Politeness

- No `robots.txt` restrictions on public diary content
- Single HTTP GET retrieves all data — no pagination
- Do not fetch more than once per hour