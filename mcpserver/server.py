"""MCP stdio server exposing hash scraper pipeline tools."""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

import logging

import yaml
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

logging.getLogger("mcp").setLevel(logging.WARNING)

load_dotenv(override=True)

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config.yaml"
_DATA_DIR = _ROOT / "data"

mcp = FastMCP("myRunList")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    from scrapers.registry import load_config
    return load_config(_CONFIG_PATH)


def _load_records(enrich: bool) -> list[dict]:
    import json
    records: list[dict] = []
    for path in sorted(_DATA_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                records.extend(data)
        except (json.JSONDecodeError, OSError):
            pass
    if enrich:
        from generators.enrichment import enrich_records
        from scrapers.state import StateStore
        state = StateStore(_ROOT / "state" / "state.json")
        records = enrich_records(records, state)
        state.save()
    return records


def _update_site_config(site: str, updates: dict) -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if site not in cfg.get("sites", {}):
        raise ValueError(f"Unknown site: {site!r}")
    cfg["sites"][site].update(updates)
    tmp = _CONFIG_PATH.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False, allow_unicode=True)
    os.replace(tmp, _CONFIG_PATH)


# ---------------------------------------------------------------------------
# Group A — Scraper tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_runs(
    site: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    enrich: bool = False,
) -> list[dict]:
    """Return scraped run records, optionally filtered by site and/or date range.

    Records are loaded from data/*.json (one file per kennel). Dates use ISO 8601
    format (YYYY-MM-DD). Set enrich=True to resolve W3W addresses to lat/lng
    coordinates (cache-first; may make HTTP requests for cache misses).
    """
    records = _load_records(enrich)
    if site:
        records = [r for r in records if r.get("kennel") == site]
    if start_date:
        records = [r for r in records if r.get("date", "") >= start_date]
    if end_date:
        records = [r for r in records if r.get("date", "") <= end_date]
    return records


@mcp.tool()
def get_scraper_status(site: str) -> dict:
    """Return TTL state and config for a single scraper by site key.

    Returns a dict combining runtime state (ttl_current, last_success,
    last_failure, disabled_at) with config values (ttl_max, display_name, enabled).
    Returns null state fields for scrapers that have never run.
    """
    from scrapers.state import StateStore
    config = _load_config()
    if site not in config.get("sites", {}):
        raise ValueError(f"Unknown site: {site!r}")
    cfg = config["sites"][site]
    state = StateStore(_ROOT / "state" / "state.json")
    entry = state.get(site) or {}
    return {
        "site": site,
        "display_name": cfg.get("display_name"),
        "enabled": cfg.get("enabled"),
        "ttl_max": cfg.get("ttl_max"),
        **entry,
    }


@mcp.tool()
def get_all_scraper_status() -> list[dict]:
    """Return TTL state and config for every configured scraper.

    Each entry combines runtime state with config values. Sites that have never
    run will have null state fields.
    """
    from scrapers.registry import all_sites
    from scrapers.state import StateStore
    config = _load_config()
    state = StateStore(_ROOT / "state" / "state.json")
    result = []
    for site in all_sites(config):
        cfg = config["sites"][site]
        entry = state.get(site) or {}
        result.append({
            "site": site,
            "display_name": cfg.get("display_name"),
            "enabled": cfg.get("enabled"),
            "ttl_max": cfg.get("ttl_max"),
            **entry,
        })
    return result


@mcp.tool()
def get_logs(site: str) -> list[dict]:
    """Return structured JSON logs for a named scraper (most recent first).

    Log files are capped at ttl_max entries. Each entry includes timestamp,
    status, failure_mode, TTL before/after, records parsed, and full
    request/response details.
    """
    config = _load_config()
    from scrapers.logwriter import LogWriter
    logs = LogWriter(
        max_body_size_bytes=config["logging"]["max_body_size_bytes"]
    ).read(site)
    return list(reversed(logs))


@mcp.tool()
def run_scraper(site: str, dry_run: bool = False) -> dict:
    """Trigger a named scraper on demand.

    Runs the full fetch → map → validate pipeline. When dry_run=False (default)
    also writes output and updates TTL state. When dry_run=True, validates output
    but does not write data files or update state. If the scraper is disabled by
    the circuit breaker, use reset_scraper first (dry_run bypasses this check).
    """
    import run as run_module
    config = _load_config()
    buf = io.StringIO()
    if dry_run:
        collect: list[dict] = []
        with redirect_stdout(buf):
            rc = run_module.run_site(site, config, dry_run=True, _collect=collect)
        message = buf.getvalue().strip() or f"[{site}] dry-run OK: {len(collect)} records validated, nothing written."
        return {"success": rc == 0, "records": len(collect), "message": message}
    with redirect_stdout(buf):
        rc = run_module.run_site(site, config)
    message = buf.getvalue().strip()
    records_written = 0
    if rc == 0:
        import json
        out_path = _DATA_DIR / f"{site}.json"
        if out_path.exists():
            try:
                records_written = len(json.loads(out_path.read_text(encoding="utf-8")))
            except Exception:
                pass
    return {"success": rc == 0, "records": records_written, "message": message}


@mcp.tool()
def run_all_scrapers(dry_run: bool = False) -> dict:
    """Trigger all enabled scrapers on demand.

    Runs every enabled scraper concurrently. When dry_run=False (default) writes
    output and updates TTL state for each site. When dry_run=True, validates
    output but does not write data files or update state. Returns a per-site
    result list and a top-level all_succeeded flag.
    """
    import run as run_module
    from scrapers.registry import all_sites
    config = _load_config()
    sites = [s for s in all_sites(config) if config["sites"][s].get("enabled", True)]
    results = []
    all_succeeded = True
    for site in sites:
        buf = io.StringIO()
        if dry_run:
            collect: list[dict] = []
            with redirect_stdout(buf):
                rc = run_module.run_site(site, config, dry_run=True, _collect=collect)
            message = buf.getvalue().strip() or f"[{site}] dry-run OK: {len(collect)} records validated, nothing written."
            results.append({"site": site, "success": rc == 0, "records": len(collect), "message": message})
        else:
            with redirect_stdout(buf):
                rc = run_module.run_site(site, config)
            message = buf.getvalue().strip()
            records_written = 0
            if rc == 0:
                import json
                out_path = _DATA_DIR / f"{site}.json"
                if out_path.exists():
                    try:
                        records_written = len(json.loads(out_path.read_text(encoding="utf-8")))
                    except Exception:
                        pass
            results.append({"site": site, "success": rc == 0, "records": records_written, "message": message})
        if rc != 0:
            all_succeeded = False
    return {"all_succeeded": all_succeeded, "results": results}


# ---------------------------------------------------------------------------
# Group B — Generate tools
# ---------------------------------------------------------------------------

@mcp.tool()
def generate_json(all_runs: bool = False, enrich: bool = True) -> list[dict]:
    """Return run data as a JSON-serialisable list.

    By default applies the 'latest' transform: the next upcoming run per kennel
    (future dates only), sorted by date. Set all_runs=True to return the full
    record set without filtering. Enrichment resolves W3W addresses to lat/lng
    from cache; set enrich=False to skip it.
    """
    from generators import transformer
    records = _load_records(enrich)
    if not all_runs:
        records = transformer.transform(records, "latest")
    return records


@mcp.tool()
def generate_html(all_runs: bool = False, enrich: bool = True) -> str:
    """Return a self-contained HTML page as a string.

    By default applies the 'latest' transform (next upcoming run per kennel).
    Set all_runs=True to include all records. Enrichment resolves W3W addresses
    to lat/lng from cache; set enrich=False to skip it.
    """
    from generators import transformer
    from generators.writers.html_writer import HTMLWriter
    records = _load_records(enrich)
    if not all_runs:
        records = transformer.transform(records, "latest")
    buf = io.StringIO()
    with redirect_stdout(buf):
        HTMLWriter().write(records, dest=None)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Group C — Config management tools
# ---------------------------------------------------------------------------

@mcp.tool()
def reset_scraper(site: str) -> dict:
    """Re-enable a scraper that was disabled by the circuit breaker.

    Restores TTL to ttl_max and clears the scraper's log history so the next
    cycle starts fresh. This operates on state/state.json and logs/ — it does
    not modify config.yaml. To permanently disable scheduling, use set_scraper_enabled.
    """
    import run as run_module
    config = _load_config()
    buf = io.StringIO()
    with redirect_stdout(buf):
        run_module.cmd_reset(site, config)
    return {"site": site, "reset": True, "message": buf.getvalue().strip()}


@mcp.tool()
def set_scraper_enabled(site: str, enabled: bool) -> dict:
    """Enable or disable a scraper in config.yaml.

    This controls whether the scraper is included in scheduled/all runs.
    Unlike reset_scraper, this persists to config.yaml and survives restarts.
    Use reset_scraper to re-enable a scraper that was tripped by the circuit breaker.
    """
    _update_site_config(site, {"enabled": enabled})
    return {"site": site, "enabled": enabled}


@mcp.tool()
def set_scraper_ttl_max(site: str, ttl_max: int) -> dict:
    """Set the TTL max for a scraper in config.yaml.

    ttl_max controls how many consecutive failures are tolerated before the
    circuit breaker disables the scraper. Also caps the number of log files
    retained. Changes persist to config.yaml.
    """
    if ttl_max < 1:
        raise ValueError("ttl_max must be at least 1")
    _update_site_config(site, {"ttl_max": ttl_max})
    return {"site": site, "ttl_max": ttl_max}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.path.insert(0, str(_ROOT))
    mcp.run(transport="stdio")
