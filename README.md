# myRunList Scraper

A Python scraping pipeline that collects run data from multiple Hash House Harriers websites, transforms it into a standardised JSON format, and generates HTML and JSON output for display or downstream consumption.

## Sites

| Site | Display Name | Data Source |
|------|-------------|-------------|
| `nh4` | North Hampshire Hash House Harriers | Google Sheets CSV |
| `dh3` | Deepcut Hash House Harriers | Fouita widget API |
| `gh3` | Guildford Hash House Harriers | Server-rendered HTML (EventOn) |
| `r2d2h3` | R2D2 Hash House Harriers | Custom ASPX endpoint |
| `hh3` | Hursley Hash House Harriers | Server-rendered HTML table |
| `chi3` | Chichester Hash House Harriers | Server-rendered HTML table |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and add your API keys
```

### Environment variables

```bash
NH4_API_KEY=                 # Google Sheet gid (see docs/NH4.md)
DH3_API_KEY=                 # Fouita widget UID (see docs/DH3.md)
GOOGLE_GEOCODING_API_KEY=    # optional; shared key for the geocoding enrichment fallback
```

GH3 and R2D2H3 require no API keys.

`GOOGLE_GEOCODING_API_KEY` is optional and not tied to any single site. When set, the
generator resolves `location.lat`/`lng` for records that have an address/postcode but no
coordinates and no What3Words (e.g. WWH3). If it is unset, the geocoding step is skipped
entirely.

## Usage

### Scraper

```bash
python3 run.py                          # run all enabled scrapers (default)
python3 run.py --all                    # run all enabled scrapers
python3 run.py --site nh4               # run a single scraper
python3 run.py --dry-run --site gh3     # validate output without writing
python3 run.py --status                 # show TTL state for all scrapers
python3 run.py --reset dh3              # re-enable a disabled scraper
python3 run.py --getlogs r2d2h3         # print scraper logs as JSON
python3 run.py --validate nh4           # validate existing data/nh4.json
```

Scraper output is written to `data/<name>.json` (one file per site). Previous output is archived to `data/archive/<name>/` before each run.

### Generator

```bash
python3 generate.py                                       # JSON to stdout (all runs, all sites)
python3 generate.py --json output/runs.json               # JSON to file
python3 generate.py --html output/index.html              # self-contained HTML to file
python3 generate.py --json --html output/index.html       # both at once
python3 generate.py --json --transform latest             # one record per kennel, future runs only
python3 generate.py --json --transform latest             # one record per kennel, piped JSON
```

The generator reads from `data/*.json` and is independent of the scraper — run them on different schedules as needed.

**`--transform latest`** filters out past runs and returns the next upcoming run per kennel, sorted by date. Transforms are applied before writing regardless of output format.

### MCP server

```bash
python -m mcpserver.server   # start stdio MCP server
```

The MCP server exposes the pipeline as tools for LLM access. Requires Python ≥ 3.10.

| Tool | Description |
|------|-------------|
| `get_runs` | Query scraped records by site and/or date range |
| `get_scraper_status` | TTL state and config for a named scraper |
| `get_all_scraper_status` | Status overview of all scrapers |
| `get_logs` | Structured logs for a named scraper |
| `run_scraper` | Trigger a named scraper on demand |
| `generate_json` | Run data as JSON (default: latest run per kennel) |
| `generate_html` | Self-contained HTML (default: latest run per kennel) |
| `reset_scraper` | Re-enable a circuit-breaker-disabled scraper |
| `set_scraper_enabled` | Toggle a scraper on/off in `config.yaml` |
| `set_scraper_ttl_max` | Set TTL max for a scraper in `config.yaml` |

## Circuit breaker

Each scraper has a `ttl_max` (default 5). A failed run decrements the TTL; three consecutive auth failures or one fatal failure disables the scraper automatically. Use `--reset <name>` to re-enable.

| Failure type | TTL change |
|---|---|
| Transient (404, 500, parse error) | −1 |
| Auth (401, 403) | −2 |
| Fatal (endpoint gone, schema change) | → 0 immediately |

The generator's location-enrichment steps have their own independent breakers — state keys
`enrich_w3w` (What3Words) and `enrich_geocode` (Google Geocoding) — so a failing enrichment
service disables only itself, never a scraper.

## Tests

```bash
pytest
```

Tests run entirely offline using fixtures in `tests/fixtures/` and expected outputs in `tests/synthetic/`.

Scrapers that resolve Google Maps short URLs (GH3, SH3) use a committed expansion cache
(`tests/fixtures/<SITE>/gmaps_expansions.json`) so tests never call the live goo.gl service.
The cache is tagged with a SHA-256 of the raw fixture — if you update a raw fixture you must
refresh the cache and regenerate the synthetic output:

```bash
python scripts/regen_synthetic.py --capture <site>   # online: refresh cache (run once after updating raw fixture)
python scripts/regen_synthetic.py <site>              # offline: regenerate tests/synthetic/<site>/output.json
```

## Adding a new scraper

1. Investigate the site — see existing `docs/*.md` for the pattern.
2. Create `docs/<name>.md` documenting the data source and field mapping.
3. Create `scrapers/sites/<name>.py` extending `BaseScraper` and implementing `map()`.
4. Add a `sites.<name>` entry to `config.yaml`.
5. Add any required env vars to `.env` and `.env.example`.
6. Create `tests/fixtures/<name>/raw_response.*` and `tests/synthetic/<name>/output.json`.
7. Create `tests/test_<name>.py`.

The registry discovers scrapers automatically from `config.yaml` — no other files need editing.

## Project structure

```
├── CLAUDE.md                  project spec and architecture
├── config.yaml                site configuration and TTL settings
├── run.py                     scraper CLI entry point
├── generate.py                generator CLI entry point
├── requirements.txt
├── .env.example
├── docs/                      per-site strategy documents
├── schemas/
│   ├── run.schema.json        output data contract
│   └── log.schema.json        log file contract
├── models/
│   └── run.py                 Pydantic models
├── scrapers/
│   ├── base.py                BaseScraper, ScraperException, FailureMode
│   ├── registry.py            config-driven scraper discovery
│   ├── state.py               TTL circuit breaker (state/state.json)
│   ├── logwriter.py           structured JSON logging
│   ├── output.py              data writing and archiving
│   └── sites/                 one module per scraper
├── generators/
│   ├── transformer.py         named query transforms (e.g. latest)
│   ├── base_writer.py         abstract writer base class
│   └── writers/
│       ├── json_writer.py     writes JSON to file or stdout
│       └── html_writer.py     writes self-contained HTML to file or stdout
├── mcpserver/
│   └── server.py              stdio MCP server (9 tools)
├── scripts/
│   └── regen_synthetic.py     regenerate synthetic output (offline; --capture for one-time goo.gl fetch)
├── tests/
│   ├── fixtures/              raw input fixtures (per site) + gmaps_expansions.json for geo scrapers
│   ├── synthetic/             expected mapped output (per site)
│   ├── test_<name>.py         per-site mapping tests
│   ├── test_framework.py      TTL, logging, archiving tests
│   └── test_mcpserver.py      MCP tool logic tests
├── data/                      scraper output (gitignored)
├── output/                    generator output (gitignored)
├── logs/                      structured scraper logs (gitignored)
└── state/                     runtime TTL state (gitignored)
```
