
# Hash Scraper Project
 
## Overview
A Python-based scraping pipeline that collects run data from multiple Hash House Harriers websites, transforms it into a standardised JSON format, and outputs it for consumption by a static site generator (SSG). Scrapers run on a daily schedule with a TTL-based circuit breaker to disable failing scrapers automatically.
 
---
 
## Architecture
 
### Pipeline
```
Sites → Scrapers → Raw data (CSV / JSON / XML / HTML)
                          ↓
                 Site-specific mapping (scraper class)
                          ↓
              Validated against JSON Schema (run.schema.json)
                          ↓
                 Archive existing output
                          ↓
              Output JSON written to data/ (one file per site)
                          ↓
               Generator reads data/*.json (independent run)
                          ↓
         Enrichment — W3W → lat/lng (cache-first, scrape as last resort)
                          ↓
         [Optional] Transformer — e.g. --transform latest
                          ↓
             HTML / JSON written to output/
```
 
### Project Structure
```
project/
├── CLAUDE.md                        ← this file
├── README.md                        ← setup and usage guide
├── docs/                            ← per-site strategy documents
│   ├── NH4.md
│   ├── DH3.md
│   ├── GH3.md
│   ├── R2D2H3.md
│   ├── HH3.md
│   └── CHI3.md
├── schemas/
│   ├── run.schema.json              ← output data contract
│   └── log.schema.json              ← log file contract
├── scrapers/
│   ├── base.py                      ← BaseScraper, ScraperException, FailureMode
│   ├── registry.py                  ← discovers and registers scrapers from config
│   ├── state.py                     ← TTL circuit breaker, reads/writes state/state.json
│   ├── logwriter.py                 ← structured JSON log writer
│   ├── output.py                    ← data output writer and archiver
│   └── sites/
│       ├── nh4.py
│       ├── dh3.py
│       ├── gh3.py
│       ├── r2d2h3.py
│       ├── hh3.py
│       └── chi3.py
├── generators/
│   ├── enrichment.py                ← post-processing: Google Maps URL → W3W lat/lng fallback
│   ├── transformer.py               ← named query transforms (e.g. latest)
│   ├── base_writer.py               ← abstract writer base class
│   └── writers/
│       ├── json_writer.py           ← JSON to file or stdout
│       └── html_writer.py           ← self-contained HTML to file or stdout
├── models/
│   └── run.py                       ← Pydantic model matching run.schema.json
├── state/
│   └── state.json                   ← runtime TTL state (gitignored)
├── logs/
│   └── <name>/                      ← one dir per scraper
│       └── YYYY-MM-DD.json          ← max N files = ttl_max, oldest purged
├── data/
│   ├── <name>.json                  ← scraper output per site (gitignored)
│   └── archive/
│       └── <name>/                  ← timestamped archives (gitignored)
│           └── <name>_<timestamp>.json
├── output/
│   ├── index.html                   ← generated HTML (gitignored)
│   └── runs.json                    ← generated JSON (gitignored)
├── tests/
│   ├── conftest.py                  ← shared fixtures and loaders
│   ├── fixtures/
│   │   └── <name>/
│   │       ├── raw_response.*       ← real raw input captured from each site
│   │       └── gmaps_expansions.json ← goo.gl expansion cache (geo scrapers only)
│   ├── synthetic/
│   │   └── <name>/
│   │       └── output.json          ← expected mapped output for unit tests
│   ├── test_<name>.py
│   └── test_framework.py            ← TTL, logging, archiving tests
├── mcpserver/
│   └── server.py                    ← stdio MCP interface
├── scripts/
│   └── regen_synthetic.py           ← regenerate synthetic output; --capture for one-time goo.gl fetch
├── run.py                           ← scraper CLI entry point
├── generate.py                      ← generator CLI entry point
├── config.yaml                      ← site configuration
├── .env                             ← API keys (gitignored)
├── .env.example                     ← key names with empty values (committed)
└── requirements.txt
```
 
---
 
## Configuration
 
### `config.yaml`
```yaml
logging:
  max_body_size_bytes: 10240
 
data:
  archive_retention_days: 365
 
sites:
  nh4:
    name: "nh4"
    display_name: "North Hampshire Hash House Harriers"
    scraper: NH4Scraper
    ttl_max: 5
    enabled: true
 
  dh3:
    name: "dh3"
    display_name: "Deepcut Hash House Harriers"
    scraper: DH3Scraper
    ttl_max: 5
    enabled: true
```
 
### `.env.example`
```bash
# North Hampshire Hash House Harriers
NH4_API_KEY=
 
# Deepcut Hash House Harriers
DH3_API_KEY=
```
API keys are embedded in the request URL. Never commit `.env` to the repository.
 
---
 
## Output Schema
 
Defined in `schemas/run.schema.json`. All scrapers must produce output conforming to this schema. Validation is handled centrally in `BaseScraper` — individual scraper classes only implement `map()`.
 
### Fields
 
| Field      | Type             | Required | Notes                                      |
|------------|------------------|----------|--------------------------------------------|
| `name`     | string           | Yes      | Display name of the hash club              |
| `kennel`   | string           | Yes      | Short identifier matching config.yaml key  |
| `runno`    | positive integer | Yes      | Run number                                 |
| `date`     | date string      | Yes      | ISO 8601 format `YYYY-MM-DD`               |
| `time`     | time string      | No       | ISO 8601 format `HH:MM`                    |
| `location` | object           | Yes      | See location fields below                  |
| `oninn`    | string           | No       | Venue name for the on-in                   |
| `hares`    | string[]         | No       | Array of hare names, minItems: 1 if present|
| `notes`    | string           | No       | Free text                                  |
| `website`  | URI string       | No       | URL associated with the event              |
 
### Location Object
 
| Field      | Type    | Required | Notes                                                              |
|------------|---------|----------|--------------------------------------------------------------------|
| `name`     | string  | No       | Venue or area name                                                 |
| `address`  | string  | No       | Street address                                                     |
| `postcode` | string  | No       | Postcode                                                           |
| `lat`      | number  | No       | Latitude `-90` to `90`                                             |
| `lng`      | number  | No       | Longitude `-180` to `180`                                          |
| `osgrid`   | string  | No       | OS Grid ref, pattern: `^[A-Z]{2}[0-9]{4}([0-9]{2}([0-9]{2}([0-9]{2})?)?)?$` |
| `w3s`      | string  | No       | What Three Words, pattern: `^[a-z]+\.[a-z]+\.[a-z]+$`             |
 
---
 
## TTL Circuit Breaker
 
Each scraper has a `ttl_max` defined in `config.yaml`. Runtime TTL state is persisted in `state/state.json`.
 
### TTL Behaviour
 
| Event                        | TTL Change              |
|------------------------------|-------------------------|
| Successful scrape            | Reset to `ttl_max`      |
| Transient failure (404, 500, parse error) | Decrement by 1 |
| Auth failure (401, 403)      | Decrement by 2          |
| Fatal failure (endpoint gone, structure change) | Zero immediately |
| TTL reaches 0                | Scraper disabled        |
 
### Failure Modes
Defined as an enum in `scrapers/base.py`:
 
```python
class FailureMode(Enum):
    TRANSIENT = 1   # 404, 500, parse/mapping errors
    AUTH = 2        # 401, 403
    FATAL = None    # zeros TTL immediately
```
 
Scrapers raise a single `ScraperException` carrying the appropriate `FailureMode`:
 
```python
raise ScraperException("Blocked", FailureMode.AUTH)
raise ScraperException("Endpoint removed", FailureMode.FATAL)
raise ScraperException("Parse failed", FailureMode.TRANSIENT)
```
 
### State File (`state/state.json`)
Initialised on first successful run for new scrapers. Can be reconstructed from logs if lost.
 
```json
{
  "nh4": {
    "ttl_current": 4,
    "last_success": "2026-06-14",
    "last_failure": "2026-06-15",
    "disabled_at": null
  }
}
```
 
---
 
## Error Logging
 
Structured JSON logs, one directory per scraper. Log file count is capped at `ttl_max` — oldest file purged when limit is exceeded. This means on disable (TTL = 0) all N logs represent the complete failure history of the current TTL cycle.
 
On scraper re-enable, logs are cleared so the next cycle starts fresh.
 
### Log Schema (`schemas/log.schema.json`)
 
```json
{
  "timestamp": "2026-06-15T08:30:00Z",
  "site": "nh4",
  "scraper_version": "1.0.0",
  "status": "failure",
  "failure_mode": "TRANSIENT",
  "ttl_before": 4,
  "ttl_after": 3,
  "records_parsed": 0,
  "exception": {
    "type": "JSONDecodeError",
    "message": "Expecting value: line 1 column 1 (char 0)",
    "stacktrace": []
  },
  "request": {
    "url": "https://example.com/api/runs",
    "method": "GET",
    "headers": {}
  },
  "response": {
    "status_code": 200,
    "headers": {},
    "body_size_bytes": 1024,
    "body_truncated": false,
    "body": ""
  }
}
```
 
---
 
## Data Output & Archiving
 
On each successful scrape:
1. Existing `data/<name>.json` is archived to `data/archive/<name>/<name>_<timestamp>.json`
2. New output is written to `data/<name>.json`
3. Archive files older than `archive_retention_days` (365) are purged
Data is regenerated from scratch on each run — no merging. The SSG is responsible for any sorting of output data.
 
---
 
## CLI
 
### Scraper (`run.py`)

```bash
python3 run.py                           # run all enabled scrapers (default)
python3 run.py --all                     # run all enabled scrapers
python3 run.py --site <name>             # run a single scraper
python3 run.py --status                  # show TTL state of all scrapers
python3 run.py --reset <name>            # re-enable a disabled scraper, clears logs
python3 run.py --getlogs <name>          # print logs for a named scraper
python3 run.py --dry-run --site <name>   # run scraper, validate output, do not write
python3 run.py --validate <name>         # validate existing output JSON against schema
```

### Generator (`generate.py`)

```bash
python3 generate.py                                     # JSON to stdout (all runs, all sites)
python3 generate.py --json output/runs.json             # JSON to file
python3 generate.py --html output/index.html            # self-contained HTML to file
python3 generate.py --json --html output/index.html     # both outputs
python3 generate.py --json --transform latest           # latest run per kennel, future only
```

`--json` and `--html` each accept an optional filename; omitting the filename writes to stdout. Not specifying either flag defaults to `--json` (stdout). `--transform` is independent of format and applies to all active writers.

#### Supported transforms

| Query | Behaviour |
|---|---|
| `latest` | Filter past runs, then return the next upcoming run per kennel sorted by date |
 
---
 
## Location Enrichment

Run by `generate.py` as a post-processing step after loading scraped data, before writing output. Populates `location.lat` / `location.lng` on records where the scraper did not supply coordinates.

### Enrichment chain (per record)

```
lat + lng already present? → skip
↓
location.w3s present?
    → check cache (data/w3w_cache.json) → hit: use it
                                        → miss: scrape what3words.com → populate lat/lng, write cache
```

### W3W workaround

What Three Words does not offer a free API. As a workaround, `generators/enrichment.py` scrapes `https://what3words.com/<word>.<word>.<word>` directly using a spoofed browser `User-Agent`, then extracts `lat=` / `lng=` values from a minimap image URL embedded in the page HTML.

**This is a best-effort scrape, not an official API.** It may break if W3W changes their page structure. A TTL circuit breaker (`ttl_max=5`, `−2` per error, state key `"enrich_w3w"` in `state/state.json`) disables the step automatically on repeated failures and logs a `WARNING`.

### W3W cache (`data/w3w_cache.json`)

Results are cached indefinitely (up to 1000 entries, FIFO eviction). Cache is always checked before making an HTTP request. Concurrent-write safety is handled with `fcntl.flock()` + atomic `os.replace()`. Cache file is gitignored.

---

## MCP Interface

A stdio MCP server implemented in `mcpserver/server.py` using the `mcp` SDK (Python ≥ 3.10 required). Run with `python -m mcpserver.server`.

### Scraper tools

| Tool                     | Description                                                   |
|--------------------------|---------------------------------------------------------------|
| `get_runs`               | Query scraped records by site and/or date range               |
| `get_scraper_status`     | TTL state and config for a named scraper                      |
| `get_all_scraper_status` | Status overview of all scrapers                               |
| `get_logs`               | Retrieve structured logs for a named scraper (newest first)   |
| `run_scraper`            | Trigger a named scraper on demand                             |

### Generate tools

| Tool            | Description                                                                    |
|-----------------|--------------------------------------------------------------------------------|
| `generate_json` | Return run data as JSON. Default: `latest` transform. `all_runs=True` for all. |
| `generate_html` | Return self-contained HTML as a string. Same `all_runs` flag.                  |

### Config management tools

| Tool                  | Description                                                               |
|-----------------------|---------------------------------------------------------------------------|
| `reset_scraper`       | Re-enable a circuit-breaker-disabled scraper, clears logs                 |
| `set_scraper_enabled` | Toggle `enabled` in `config.yaml` (persists across restarts)              |
| `set_scraper_ttl_max` | Set `ttl_max` in `config.yaml`                                            |
 
---
 
## Scraper Classes
 
Each scraper lives in `scrapers/sites/<name>.py` and must:
- Set `name = "<name>"` matching the key in `config.yaml`
- Set `version = "1.0.0"` using semver, bumped on every change
- Extend `BaseScraper`
- Implement `map(self, raw) -> list[dict]` to transform raw data to the run schema
- Raise `ScraperException` with the appropriate `FailureMode` on failure
### Base Class Interface (`scrapers/base.py`)
```python
class BaseScraper(ABC):
    name: str
    version: str
 
    def fetch(self) -> str: ...         # handles HTTP, raises ScraperException
    def validate(self, data: dict): ... # validates against run.schema.json
    
    @abstractmethod
    def map(self, raw) -> list[dict]: ...  # site-specific mapping
 
    def run(self) -> list[dict]: ...    # fetch → map → validate
```
 
---
 
## Adding a New Scraper
 
1. Investigate the site — identify the raw data source (API, inline script, static file, HTML) using DevTools Network tab
2. Create `docs/<name>.md` documenting the site strategy (see existing docs/ for format)
3. Create `scrapers/sites/<name>.py` with the scraper class
   - Set `name`, `version = "1.0.0"`
   - Implement `map()`
   - Add any required env var to `.env` and `.env.example`
4. Add site entry to `config.yaml`
5. Create `tests/fixtures/<name>/raw_response.*` with real raw input captured from the site
6. Create `tests/synthetic/<name>/output.json` with expected mapped output
   - If the scraper resolves Google Maps short URLs (`maps.app.goo.gl`), also run:
     `python scripts/regen_synthetic.py --capture <name>` (online, once) to create
     `tests/fixtures/<NAME>/gmaps_expansions.json`, then
     `python scripts/regen_synthetic.py <name>` (offline) to generate `output.json`.
   - Re-run `--capture` whenever `raw_response.*` is updated.
7. Create `tests/test_<name>.py` to validate the mapping
   - Geo scrapers: use the `gmaps_expander` fixture from `conftest.py` so tests stay offline.
No other files need modification — the registry handles discovery automatically from `config.yaml`.
 
---
 
## Site Strategy Documents
 
Per-site strategy is documented in `docs/<name>.md` and referenced here.
 
| Scraper | Doc | Display Name |
|---------|-----|--------------|
| `nh4`    | [docs/NH4.md](./docs/NH4.md)       | North Hampshire Hash House Harriers |
| `dh3`    | [docs/DH3.md](./docs/DH3.md)       | Deepcut Hash House Harriers |
| `gh3`    | [docs/GH3.md](./docs/GH3.md)       | Guildford Hash House Harriers |
| `r2d2h3` | [docs/R2D2H3.md](./docs/R2D2H3.md) | R2D2 Hash House Harriers |
| `hh3`    | [docs/HH3.md](./docs/HH3.md)       | Hursley Hash House Harriers |
| `chi3`   | [docs/CHI3.md](./docs/CHI3.md)     | Chichester Hash House Harriers |
| `sh3`    | [docs/SH3.md](./docs/SH3.md)       | Surrey Hash House Harriers |
| `wwh3`   | [docs/WWH3.md](./docs/WWH3.md)     | Worthy Winchester Hash House Harriers |