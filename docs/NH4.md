# NH4.md — North Hampshire Hash House Harriers Scraper Design
 
## Site Overview
 
| Key | Value |
|-----|-------|
| **Scraper name** | `nh4` |
| **Display name** | North Hampshire Hash House Harriers |
| **URL** | https://www.nh4.org |
| **Platform** | Google Sites (hosted) |
| **Data source** | Google Sheets (publicly published CSV) |
| **Timezone** | Europe/London (BST = UTC+1, GMT = UTC+0) |
 
---
 
## Data Source
 
**Primary**: Publicly published Google Sheet — CSV export endpoint.
 
The run list is maintained in a Google Sheet and embedded on the [Run List page](https://www.nh4.org/run-list-data/run-list) via an iframe. The sheet is published to the web and can be fetched directly as CSV without authentication.
 
**Do not use:**
- The `pubhtml` endpoint — returns HTML, not structured data
- The Google Sheets API (`sheets.googleapis.com`) — requires OAuth, unnecessary
- The embedded iframe URL — returns HTML, not structured data
- Web scraping of `www.nh4.org` — the sheet is the authoritative source
**Scope**: The sheet contains upcoming runs only. The meaningful data range is `B1:I11` (confirmed from the embed code on the site), giving a maximum of 10 data rows at a time.
 
---
 
## Endpoint
 
```
https://docs.google.com/spreadsheets/d/e/2PACX-1vTVhgeQtlXNqbt00EUMEtnm9BUKusXxkIfKyjucXz-lGYkmN2gFoCm89BPovapIf-1c8zheXvS8npg_/pub?gid={NH4_API_KEY}&single=true&output=csv
```
 
### Parameters
 
| Parameter | Value | Notes |
|---|---|---|
| `gid` | `NH4_API_KEY` env var (`2009907438`) | Identifies the sheet tab. Treat as configurable — may change if the spreadsheet is restructured. |
| `single` | `true` | Required for single-sheet export |
| `output` | `csv` | Requests CSV format |
 
### URL construction
 
```python
import os
gid = os.environ["NH4_API_KEY"]  # "2009907438"
url = f"https://docs.google.com/spreadsheets/d/e/2PACX-1vTVhgeQtlXNqbt00EUMEtnm9BUKusXxkIfKyjucXz-lGYkmN2gFoCm89BPovapIf-1c8zheXvS8npg_/pub?gid={gid}&single=true&output=csv"
```
 
### Verified curl
 
```bash
curl -L "https://docs.google.com/spreadsheets/d/e/2PACX-1vTVhgeQtlXNqbt00EUMEtnm9BUKusXxkIfKyjucXz-lGYkmN2gFoCm89BPovapIf-1c8zheXvS8npg_/pub?gid=2009907438&single=true&output=csv"
```
 
**Important**: The endpoint returns an HTTP 302 redirect. The HTTP client must follow redirects (`urllib.request` does this by default; `curl` requires `-L`).
 
---
 
## Raw Data Format
 
The CSV export returns the **full sheet**, ignoring any `range` parameter. Column A is empty/unused. The meaningful data occupies columns B–I, rows 1–11.
 
### Trimming rules
 
| Dimension | Rule |
|---|---|
| Columns | Skip index 0 (column A). Keep indices 1–8 (columns B–I). |
| Rows | Keep first 11 rows only (row 1 = header, rows 2–11 = data). |
 
These bounds should be defined as constants in the scraper:
 
```python
DATA_COL_START = 1   # skip column A (index 0)
DATA_ROW_LIMIT = 11  # header + max 10 data rows
```
 
### Expected columns (B–I)
 
The exact column headers must be confirmed from a live fetch, as the sheet owner controls them. The scraper should use whatever headers appear in row 1 of the trimmed range and map them to the output schema (see Schema Field Mapping below).
 
---
 
## Schema Field Mapping
 
Based on the data visible in the embedded sheet on [www.nh4.org/run-list-data/run-list](https://www.nh4.org/run-list-data/run-list). Column headers must be confirmed on first run.
 
| Schema field | Source | Transform |
|---|---|---|
| `name` | Static | `"North Hampshire Hash House Harriers"` |
| `runno` | CSV column | Parse as positive integer |
| `date` | CSV column | Parse to `YYYY-MM-DD` |
| `time` | CSV column | Extract `HH:MM` if present |
| `location.name` | CSV column | Venue/area name, direct string |
| `location.postcode` | CSV column | Direct string if present |
| `location.address` | CSV column | Direct string if present |
| `hares` | CSV column | Split on comma if multiple hares, return as list |
| `oninn` | CSV column | Direct string if present |
| `notes` | CSV column | Direct string if present |
| `website` | — | Not available |
| `location.lat` | — | Not available |
| `location.lng` | — | Not available |
| `location.osgrid` | — | Not available |
| `location.w3s` | — | Not available |
 
---
 
## Failure Mode Guidance
 
| Condition | Action |
|---|---|
| HTTP non-200 after redirect | `ScraperException(FailureMode.TRANSIENT)` |
| HTTP 401 / 403 | `ScraperException(FailureMode.AUTH)` — gid may have been made private |
| Response is not valid CSV (e.g. HTML error page returned) | `ScraperException(FailureMode.FATAL)` — sheet structure changed |
| Trimmed data has zero rows after stripping empty rows | `ScraperException(FailureMode.TRANSIENT)` — sheet may be temporarily empty |
| Header row does not contain expected columns | `ScraperException(FailureMode.FATAL)` — sheet columns renamed |
| Individual row missing `runno` or `date` | Skip record, log warning |
 
---
 
## Robots / Politeness
 
- No `robots.txt` restrictions on publicly published Google Sheets content
- Single HTTP GET retrieves all data — no pagination
- Do not fetch more than once per hour
---
 
## Environment Variables
 
| Variable | Value | Notes |
|---|---|---|
| `NH4_API_KEY` | `2009907438` | The `gid` of the sheet tab. Named as an API key per project convention since it is embedded in the request URL. Set in `.env`, never committed. |
 
