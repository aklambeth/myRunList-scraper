# myRunList Scraper

A Python scraping pipeline that collects run data from multiple Hash House Harriers websites, transforms it into a standardised JSON format, and outputs it for consumption by a static site generator (SSG).

## Sites

| Site | Display Name | Data Source |
|------|-------------|-------------|
| `nh4` | North Hampshire Hash House Harriers | Google Sheets CSV |
| `dh3` | Deepcut Hash House Harriers | Fouita widget API |
| `gh3` | Guildford Hash House Harriers | Server-rendered HTML (EventOn) |
| `r2d2h3` | R2D2 Hash House Harriers | Custom ASPX endpoint |

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
NH4_API_KEY=   # Google Sheet gid (see docs/NH4.md)
DH3_API_KEY=   # Fouita widget UID (see docs/DH3.md)
```

GH3 and R2D2H3 require no API keys.

## Usage

```bash
python run.py --all                    # run all enabled scrapers
python run.py --site nh4               # run a single scraper
python run.py --dry-run --site gh3     # validate output without writing
python run.py --status                 # show TTL state for all scrapers
python run.py --reset dh3              # re-enable a disabled scraper
python run.py --getlogs r2d2h3         # print scraper logs as JSON
python run.py --validate nh4           # validate existing data/nh4.json
```

Output is written to `data/<name>.json`. Previous output is archived to `data/archive/<name>/` before each run.

## Circuit breaker

Each scraper has a `ttl_max` (default 5). A failed run decrements the TTL; three consecutive auth failures or one fatal failure disables the scraper automatically. Use `--reset <name>` to re-enable.

| Failure type | TTL change |
|---|---|
| Transient (404, 500, parse error) | −1 |
| Auth (401, 403) | −2 |
| Fatal (endpoint gone, schema change) | → 0 immediately |

## Tests

```bash
pytest
```

Tests run entirely offline using fixtures in `tests/fixtures/` and expected outputs in `tests/synthetic/`.

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
├── run.py                     CLI entry point
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
├── tests/
│   ├── fixtures/              raw input fixtures (per site)
│   ├── synthetic/             expected mapped output (per site)
│   ├── test_<name>.py         per-site mapping tests
│   └── test_framework.py      TTL, logging, archiving tests
├── data/                      SSG output (gitignored)
├── logs/                      structured scraper logs (gitignored)
└── state/                     runtime TTL state (gitignored)
```
