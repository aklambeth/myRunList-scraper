# DH3.md — Deepcut Hash House Harriers Scraper Design
 
## Site Overview
 
| Key | Value |
|-----|-------|
| **Scraper name** | `dh3` |
| **Display name** | Deepcut Hash House Harriers |
| **URL** | https://www.dh3.org/run-list |
| **Platform** | Google Sites + Fouita widget |
| **Timezone** | Europe/London (BST = UTC+1, GMT = UTC+0) |
 
---
 
## Data Source
 
**Primary**: Fouita widget API — `https://api2.fouita.com/v1/q/widget`
 
The run list is displayed on the site via a Fouita third-party calendar widget (ID `0x37f64f`) embedded inside a sandboxed Google Sites iframe. The widget fetches its data from the Fouita API at page load time. The run data never touches the `dh3.org` domain.
 
**Do not use:**
- `https://www.dh3.org/run-list` — page HTML contains no run data; the widget is rendered remotely
- The Fouita iframe HTML itself — the iframe shell contains no data; it is populated by JavaScript at runtime
- Any GunDB/websocket endpoint — the Fouita library connects to `gun2.fouita.com` for real-time sync but the canonical data source is the REST API
**Scope**: The feed returns all upcoming runs configured in the Fouita admin panel. In the live data this is approximately 8 future runs.
 
---
 
## How the Widget Loads (for reference)
 
The Google Sites page embeds a custom HTML block containing:
 
```javascript
(async () => {
    const FT = await import("https://cdn.fouita.com/assets/fouita/fouita-utils.es.js");
    FT.Loader("0x37f64f");
})()
```
 
The `Loader` function POSTs to the Fouita API, decodes the response, dynamically imports the Svelte widget component, and mounts it into the DOM. This is not relevant to scraping — fetch the API directly.
 
---
 
## Endpoint
 
```
POST https://api2.fouita.com/v1/q/widget
Content-Type: application/json
Body: {"uid": "0x37f64f"}
```
 
No authentication required. No API key needed.
 
### Response Structure
 
The response uses **two layers of base64 encoding**:
 
```
response.json          → base64 string
  └─ decoded JSON
       └─ .q[0].data_feed[0].feed_data  → base64 string
            └─ decoded JSON             → { "events": [...], "settings": {...}, ... }
```
 
The run data is in the `events` array of the innermost decoded JSON.
 
### Verified curl
 
```bash
curl -s -X POST "https://api2.fouita.com/v1/q/widget" \
  -H "Content-Type: application/json" \
  -d '{"uid": "0x37f64f"}' \
  | jq -r '.json' \
  | base64 -d \
  | jq -r '.q[0].data_feed[0].feed_data' \
  | base64 -d
```
 
### Python fetch
 
```python
import requests
import base64
import json
 
def fetch_raw(api_key: str) -> list[dict]:
    resp = requests.post(
        "https://api2.fouita.com/v1/q/widget",
        json={"uid": api_key},
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    resp.raise_for_status()
    envelope = json.loads(base64.b64decode(resp.json()["json"]))
    feed_b64 = envelope["q"][0]["data_feed"][0]["feed_data"]
    feed = json.loads(base64.b64decode(feed_b64))
    return feed["events"]
```
 
The widget UID `0x37f64f` is stored as `DH3_API_KEY` in `.env` per project convention.
 
---
 
## Raw Data Format
 
The decoded feed contains an `events` array. Each element is an event object. Example record (Run 671):
 
```json
{
  "tag": ["Run 671", "Machinist", "Notes: Curry and snacks provided, bring your own drink and a chair."],
  "image": "",
  "link": "",
  "button": "",
  "cardArrText": [
    {"html": "<b>Chobham, High St CP</b>", "klass": "md:text-xl text-lg text-left", "custom": false}
  ],
  "popupArrText": [
    {"html": "<span class=\"font-semibold\">Run # 671</span>", "klass": "md:text-2xl text-xl text-left"},
    {"html": "Hare(s):&nbsp; &nbsp; &nbsp; Machinist", "klass": ""},
    {"html": "Location:&nbsp; &nbsp; Chobham", "klass": ""},
    {"html": "RV:&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; High St CP", "klass": ""},
    {"html": "On-Inn:&nbsp; &nbsp; &nbsp; &nbsp;Machinist's gaff", "klass": "text-left mt-1", "custom": false}
  ],
  "date": "2026-07-01T11:00",
  "ndate": "2026-07-01T11:00",
  "name": "Run 671",
  "location": "",
  "repeat": "none"
}
```
 
### Field Notes
 
All structured data is embedded as HTML strings inside `tag` and `popupArrText` arrays — there are no clean scalar fields for run number, hare, location etc. Everything must be parsed from HTML.
 
| Field | Content | Notes |
|-------|---------|-------|
| `tag[0]` | `"Run 671"` | Run number as `"Run NNN"` |
| `tag[1]` | `"Machinist"` | Hare name — `"TBA"` if not yet set |
| `tag[2]` | `"Notes: ..."` | Notes — empty string after `"Notes: "` if none |
| `date` | `"2026-07-01T11:00"` | ISO-like datetime, no timezone suffix |
| `ndate` | `"2026-07-01T11:00"` | Identical to `date` — ignore |
| `name` | `"Run 671"` | Duplicates `tag[0]` |
| `cardArrText[0].html` | `"<b>Chobham, High St CP</b>"` | Location + RV as single HTML string |
| `popupArrText[2].html` | `"Location:&nbsp; &nbsp; Chobham"` | Area/town name |
| `popupArrText[3].html` | `"RV:&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; High St CP"` | Rendezvous / start location name |
| `popupArrText[4].html` | `"On-Inn:&nbsp; &nbsp; &nbsp; &nbsp;Machinist's gaff"` | On-inn venue |
| `location` | `""` | Always empty — do not use |
 
---
 
## Extraction Strategy
 
Since all fields are HTML strings, use BeautifulSoup to strip tags and `html.unescape()` / `&nbsp;` handling to clean values.
 
```python
from bs4 import BeautifulSoup
import re
 
def strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()
 
def extract_labelled(html: str, label: str) -> str:
    """Strip label prefix like 'Hare(s):' and clean whitespace."""
    text = strip_html(html)
    if ":" in text:
        text = text.split(":", 1)[1]
    return re.sub(r'\s+', ' ', text).strip()
```
 
### Run number
 
```python
# tag[0] = "Run 671"
runno = int(event["tag"][0].split()[-1])
```
 
### Date and time
 
```python
from datetime import datetime
 
dt = datetime.fromisoformat(event["date"])  # "2026-07-01T11:00"
date = dt.strftime("%Y-%m-%d")
time = dt.strftime("%H:%M")
```
 
No timezone info is present in the `date` field. Treat as Europe/London local time.
 
### Hare
 
```python
# tag[1] = "Machinist" or "TBA"
hare_raw = event["tag"][1].strip()
hares = [hare_raw] if hare_raw and hare_raw.upper() != "TBA" else []
```
 
### Notes
 
```python
# tag[2] = "Notes: Curry and snacks provided..."
notes_raw = event["tag"][2]
notes = notes_raw.split("Notes:", 1)[-1].strip() if "Notes:" in notes_raw else ""
notes = notes if notes else None
```
 
### Location name (RV/start point)
 
```python
# popupArrText[3].html = "RV:&nbsp; &nbsp; &nbsp; High St CP"
rv = extract_labelled(event["popupArrText"][3]["html"], "RV")
rv = rv if rv and rv.upper() != "TBA" else None
```
 
### On-inn
 
```python
# popupArrText[4].html = "On-Inn:&nbsp; &nbsp; Machinist's gaff"
oninn = extract_labelled(event["popupArrText"][4]["html"], "On-Inn")
oninn = oninn if oninn and oninn.upper() != "TBA" else None
```
 
---
 
## TBA Handling
 
Many future runs have `"TBA"` for hare, location, RV, and on-inn. Treat `"TBA"` (case-insensitive) as absent — omit the field from output rather than writing `"TBA"` as a value.
 
---
 
## Schema Field Mapping
 
| Schema field | Source | Transform |
|---|---|---|
| `name` | Static | `"Deepcut Hash House Harriers"` |
| `runno` | `tag[0]` | `int(tag[0].split()[-1])` |
| `date` | `date` | `datetime.fromisoformat()` → `YYYY-MM-DD` |
| `time` | `date` | `datetime.fromisoformat()` → `HH:MM` |
| `location.name` | `popupArrText[3].html` | Strip `"RV:"` label + HTML, omit if TBA |
| `location.postcode` | — | Not available |
| `location.address` | — | Not available |
| `location.lat` | — | Not available |
| `location.lng` | — | Not available |
| `location.osgrid` | — | Not available |
| `location.w3s` | — | Not available |
| `hares` | `tag[1]` | Single-item list, omit if TBA |
| `oninn` | `popupArrText[4].html` | Strip `"On-Inn:"` label + HTML, omit if TBA |
| `notes` | `tag[2]` | Strip `"Notes:"` prefix, omit if empty |
| `website` | Static | `"https://www.dh3.org"` |
 
---
 
## Example: Mapped Output
 
**Raw event:**
```json
{
  "tag": ["Run 671", "Machinist", "Notes: Curry and snacks provided, bring your own drink and a chair."],
  "date": "2026-07-01T11:00",
  "popupArrText": [
    {"html": "<span class=\"font-semibold\">Run # 671</span>"},
    {"html": "Hare(s):&nbsp; &nbsp; &nbsp; Machinist"},
    {"html": "Location:&nbsp; &nbsp; Chobham"},
    {"html": "RV:&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; High St CP"},
    {"html": "On-Inn:&nbsp; &nbsp; &nbsp; &nbsp;Machinist's gaff"}
  ]
}
```
 
**Mapped output record:**
```json
{
  "name": "Deepcut Hash House Harriers",
  "runno": 671,
  "date": "2026-07-01",
  "time": "11:00",
  "location": {
    "name": "High St CP"
  },
  "hares": ["Machinist"],
  "oninn": "Machinist's gaff",
  "notes": "Curry and snacks provided, bring your own drink and a chair.",
  "website": "https://www.dh3.org"
}
```
 
---
 
## Failure Mode Guidance
 
| Condition | Action |
|-----------|--------|
| HTTP non-200 from Fouita API | `ScraperException(FailureMode.TRANSIENT)` |
| Response has no `.json` field | `ScraperException(FailureMode.FATAL)` — API structure changed |
| Base64 decode fails | `ScraperException(FailureMode.FATAL)` — encoding changed |
| `q[0].data_feed` missing or empty | `ScraperException(FailureMode.FATAL)` — feed structure changed |
| `events` key missing from decoded feed | `ScraperException(FailureMode.FATAL)` — feed schema changed |
| `events` array is empty | `ScraperException(FailureMode.TRANSIENT)` — may be temporarily empty |
| `tag` array has fewer than 3 elements | Skip record, log warning |
| `date` field cannot be parsed | Skip record, log warning |
| Run number cannot be parsed from `tag[0]` | Skip record, log warning |
 
---
 
## Environment Variables
 
| Variable | Value | Notes |
|---|---|---|
| `DH3_API_KEY` | `0x37f64f` | Fouita widget UID. Named as API key per project convention since it is embedded in the request body. Set in `.env`, never committed. |
 
---
 
## Robots / Politeness
 
- No `robots.txt` restrictions identified on `api2.fouita.com`
- Single HTTP POST retrieves all data — no pagination
- Do not fetch more than once per hour
 
