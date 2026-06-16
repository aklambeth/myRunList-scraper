# HH3.md — Hursley Hash House Harriers Scraper Design

## Site Overview

| Key | Value |
|-----|-------|
| **Scraper name** | `hh3` |
| **Display name** | Hursley Hash House Harriers |
| **URL** | https://www.hursleyh3.co.uk/runList.html |
| **Platform** | Custom static HTML site (server-side rendered include) |
| **Timezone** | Europe/London (BST = UTC+1, GMT = UTC+0) |

---

## Data Source

**Primary**: HTML table include — `https://www.hursleyh3.co.uk/includes/table-nextRuns.html`

The run list page (`/runList.html`) server-side includes a separate HTML fragment
at `/includes/table-nextRuns.html`. This fragment contains a fully rendered
`<table>` with all upcoming runs. No JavaScript execution, authentication, or AJAX
calls are required.

**Do not use:**
- `https://www.hursleyh3.co.uk/runList.html` — the parent page; the include fragment
  is the authoritative source and avoids parsing surrounding page chrome
- Any API or dynamic endpoint — none exists; the data is static HTML

**Scope**: The table contains all upcoming runs up to approximately the next 2 months
(~18 records observed). No pagination.

---

## Extraction Strategy

Fetch the include fragment directly and parse the `<table class="order-table table">`
with BeautifulSoup. The `<thead>` defines six columns; each `<tr>` in `<tbody>`
is one run.

```python
import requests
from bs4 import BeautifulSoup

def fetch_raw() -> str:
    resp = requests.get(
        "https://www.hursleyh3.co.uk/includes/table-nextRuns.html",
        timeout=10
    )
    resp.raise_for_status()
    return resp.text

def extract_rows(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="order-table")
    if not table:
        raise ScraperException("Table not found", FailureMode.FATAL)
    rows = table.find("tbody").find_all("tr")
    return [
        [td.get_text(separator=" ", strip=True) for td in row.find_all("td")]
        for row in rows
        if len(row.find_all("td")) == 6
    ]
```

### Column Layout

| Index | `<th>` header | Example value |
|-------|---------------|---------------|
| 0 | Run Number | `1946`, `1947 FNL`, `1951 Solstice` |
| 1 | Date | `31/05/26`, `21/06/26 04:30` |
| 2 | Pub | `The Prince Consort`, `Monument carpark` |
| 3 | Location | `Netley`, `Farley Mount` |
| 4 | Postcode | `SO31 5DS` (may be empty) |
| 5 | Hares | `OMO & Tinkerbell` (multi-line `<br>` in source) |

**Note**: `get_text(separator=" ")` collapses `<br>` tags and `&amp;` entities into
plain text — no additional HTML stripping needed.

---

## Run Number Parsing

The Run Number cell may contain suffixes beyond the integer (e.g. `"FNL"`,
`"Solstice"`). Extract the leading integer; store any suffix in `notes` if present.

```python
import re

def parse_runno(cell: str) -> tuple[int, str | None]:
    match = re.match(r'^(\d+)(.*)', cell.strip())
    if not match:
        raise ValueError(f"Cannot parse run number from: {cell!r}")
    runno = int(match.group(1))
    suffix = match.group(2).strip() or None
    return runno, suffix
```

The suffix (e.g. `"FNL"`, `"Solstice"`) is appended to `notes` if no other notes
are present, or prepended if notes are already set from another source.

---

## Date and Time Parsing

The Date cell is in `DD/MM/YY` format. An optional time (`HH:MM`) may follow,
separated by a space:

```
"31/05/26"           → date only
"21/06/26 04:30"     → date + time
"21/06/26 11:00"     → date + time
```

```python
from datetime import datetime

def parse_date_time(cell: str) -> tuple[str, str | None]:
    cell = cell.strip()
    if " " in cell:
        dt = datetime.strptime(cell, "%d/%m/%y %H:%M")
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    else:
        dt = datetime.strptime(cell, "%d/%m/%y")
        return dt.strftime("%Y-%m-%d"), None
```

---

## Hare Parsing

Hares are stored in a single cell, separated by `<br>&amp;` in the raw HTML,
which becomes `" &"` or `"& "` after `get_text()`. Split on `&` and strip each
token. Discard empty tokens (trailing `&` with no second name).

```python
import re

def parse_hares(cell: str) -> list[str]:
    # Split on "&" — handles "OMO & Tinkerbell", "OMO &", "Mudlark,Sunny D, K9 &Yellow Peril"
    parts = re.split(r'\s*&\s*|\s*,\s*', cell)
    return [p.strip() for p in parts if p.strip()]
```

**TBA / empty handling**: if the cell is empty or all tokens are empty after
stripping, omit `hares` from output.

---

## On-Inn (Pub) Parsing

The Pub cell maps directly to `oninn`. The cell may be empty for unconfirmed runs
— omit the field in that case.

Multi-line pub names (e.g. `"Hogmore Inclosure Hogmore Road"`) are produced by a
`<br>` in the source; `get_text(separator=" ")` joins them with a space. Use the
joined string directly as `oninn`.

```python
def parse_oninn(cell: str) -> str | None:
    val = cell.strip()
    return val if val else None
```

---

## Location Parsing

The Location cell maps to `location.name`. May be empty or `"?"` for unconfirmed
runs — omit the field in those cases.

```python
def parse_location_name(cell: str) -> str | None:
    val = cell.strip()
    return val if val and val != "?" else None
```

---

## Postcode Parsing

The Postcode cell maps directly to `location.postcode`. May be empty — omit if so.

```python
def parse_postcode(cell: str) -> str | None:
    val = cell.strip().upper()
    return val if val else None
```

---

## Schema Field Mapping

| Schema field | Source | Transform |
|---|---|---|
| `name` | Static | `"Hursley Hash House Harriers"` |
| `runno` | Column 0 | Leading integer via regex |
| `date` | Column 1 | `strptime("%d/%m/%y")` → `"%Y-%m-%d"` |
| `time` | Column 1 | Optional `HH:MM` suffix |
| `location.name` | Column 3 | Direct, omit if empty or `"?"` |
| `location.postcode` | Column 4 | Direct, omit if empty |
| `location.address` | — | Not available |
| `location.lat` | — | Not available |
| `location.lng` | — | Not available |
| `location.osgrid` | — | Not available |
| `location.w3s` | — | Not available |
| `hares` | Column 5 | Split on `&` and `,`, omit empty tokens |
| `oninn` | Column 2 | Direct, omit if empty |
| `notes` | Column 0 suffix | Run number suffix (e.g. `"FNL"`, `"Solstice"`), omit if none |
| `website` | Static | `"https://www.hursleyh3.co.uk"` |

---

## Example: Mapped Output

**Raw row (run with time, multiple hares, suffix):**

HTML source:
```html
<tr>
    <td>1951 Solstice</td>
    <td>21/06/26 04:30</td>
    <td>Monument carpark</td>
    <td>Farley Mount</td>
    <td>SO51 0QT</td>
    <td>Mudlark
        <br>&amp; </td>
</tr>
```

After `get_text(separator=" ", strip=True)`:
```
["1951 Solstice", "21/06/26 04:30", "Monument carpark", "Farley Mount", "SO51 0QT", "Mudlark &"]
```

**Mapped output record:**
```json
{
  "name": "Hursley Hash House Harriers",
  "runno": 1951,
  "date": "2026-06-21",
  "time": "04:30",
  "location": {
    "name": "Farley Mount",
    "postcode": "SO51 0QT"
  },
  "hares": ["Mudlark"],
  "oninn": "Monument carpark",
  "notes": "Solstice",
  "website": "https://www.hursleyh3.co.uk"
}
```

**Raw row (standard run, two hares, no time):**

After `get_text()`:
```
["1946", "31/05/26", "The Prince Consort", "Netley", "SO31 5DS", "OMO & Tinkerbell"]
```

**Mapped output record:**
```json
{
  "name": "Hursley Hash House Harriers",
  "runno": 1946,
  "date": "2026-05-31",
  "location": {
    "name": "Netley",
    "postcode": "SO31 5DS"
  },
  "hares": ["OMO", "Tinkerbell"],
  "oninn": "The Prince Consort",
  "website": "https://www.hursleyh3.co.uk"
}
```

**Raw row (unconfirmed run — empty pub, location, postcode, trailing `&`):**

After `get_text()`:
```
["1959", "26/07/26", "", "", "", "Cooee! & Cruella"]
```

**Mapped output record:**
```json
{
  "name": "Hursley Hash House Harriers",
  "runno": 1959,
  "date": "2026-07-26",
  "location": {},
  "hares": ["Cooee!", "Cruella"],
  "website": "https://www.hursleyh3.co.uk"
}
```

**Raw row (multi-hare comma-separated with `&`):**

After `get_text()`:
```
["1958", "19/07/26", "M.A.D.", "?", "", "Mudlark,Sunny D, K9 & Yellow Peril"]
```

**Mapped output record:**
```json
{
  "name": "Hursley Hash House Harriers",
  "runno": 1958,
  "date": "2026-07-19",
  "location": {},
  "hares": ["Mudlark", "Sunny D", "K9", "Yellow Peril"],
  "oninn": "M.A.D.",
  "website": "https://www.hursleyh3.co.uk"
}
```

---

## Failure Mode Guidance

| Condition | Action |
|-----------|--------|
| HTTP non-200 from include endpoint | `ScraperException(FailureMode.TRANSIENT)` |
| Response contains no `<table class="order-table">` | `ScraperException(FailureMode.FATAL)` — page structure changed |
| `<tbody>` contains zero valid rows (6 `<td>` each) | `ScraperException(FailureMode.TRANSIENT)` — table may be temporarily empty |
| Row has fewer than 6 `<td>` cells | Skip row, log warning |
| Run number cell contains no leading integer | Skip row, log warning |
| Date cell cannot be parsed | Skip row, log warning |

---

## Robots / Politeness

- No `robots.txt` restrictions identified on public run list content
- Single HTTP GET retrieves all data — no pagination
- Do not fetch more than once per hour

---

## Known Issues

### 403 on default User-Agent

The server returns a 403 for requests sent with the default `python-requests/<version>` User-Agent. A browser-style User-Agent is required.

The scraper sets `request_headers` on `HH3Scraper` (via the `BaseScraper.request_headers` hook) to a polite bot string:

```
Mozilla/5.0 (compatible; myRunList-scraper/1.0; +https://github.com/aklambeth/myRunList-scraper)
```

If the site starts returning 403 again, check whether the User-Agent is still being sent correctly before treating it as an auth failure.