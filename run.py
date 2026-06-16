#!/usr/bin/env python3
"""CLI entry point for the Hash scraper pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from scrapers.base import ScraperException
from scrapers.logwriter import LogWriter
from scrapers.output import OutputWriter
from scrapers.registry import (
    build_scraper,
    enabled_sites,
    load_config,
    site_config,
)
from scrapers.state import StateStore

_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "run.schema.json"


def _writers(config: dict) -> tuple[LogWriter, OutputWriter]:
    log_writer = LogWriter(
        max_body_size_bytes=config["logging"]["max_body_size_bytes"]
    )
    output_writer = OutputWriter(
        archive_retention_days=config["data"]["archive_retention_days"]
    )
    return log_writer, output_writer


def run_site(site: str, config: dict, *, dry_run: bool = False) -> int:
    """Run a single scraper. Returns process-style exit code (0 ok)."""
    cfg = site_config(site, config)
    ttl_max = cfg["ttl_max"]
    state = StateStore()
    log_writer, output_writer = _writers(config)

    if state.is_disabled(site) and not dry_run:
        print(f"[{site}] disabled (TTL=0). Use --reset {site} to re-enable.")
        return 1

    entry = state.get(site) or {"ttl_current": ttl_max}
    ttl_before = entry["ttl_current"]
    scraper = build_scraper(site, config)

    try:
        records = scraper.run()
    except ScraperException as exc:
        if dry_run:
            print(f"[{site}] DRY RUN failed: {exc}")
            return 1
        new_entry = state.record_failure(site, ttl_max, exc.mode)
        log_writer.write(
            site=site,
            version=scraper.version,
            status="failure",
            ttl_before=ttl_before,
            ttl_after=new_entry["ttl_current"],
            records_parsed=0,
            ttl_max=ttl_max,
            failure_mode=exc.mode,
            exception=exc,
            request=scraper.last_request,
            response=scraper.last_response,
        )
        disabled = " — SCRAPER DISABLED" if new_entry["ttl_current"] == 0 else ""
        print(
            f"[{site}] FAILURE ({exc.mode.name}): TTL {ttl_before} -> "
            f"{new_entry['ttl_current']}{disabled}\n  {exc}"
        )
        return 1

    if dry_run:
        print(f"[{site}] DRY RUN ok: {len(records)} records validated (not written).")
        print(json.dumps(records, indent=2))
        return 0

    output_writer.write(site, records)
    new_entry = state.record_success(site, ttl_max)
    log_writer.write(
        site=site,
        version=scraper.version,
        status="success",
        ttl_before=ttl_before,
        ttl_after=new_entry["ttl_current"],
        records_parsed=len(records),
        ttl_max=ttl_max,
        request=scraper.last_request,
        response=scraper.last_response,
    )
    print(f"[{site}] OK: {len(records)} records. TTL reset to {ttl_max}.")
    return 0


def run_all(config: dict) -> int:
    rc = 0
    for site in enabled_sites(config):
        if StateStore().is_disabled(site):
            print(f"[{site}] skipped (disabled).")
            continue
        rc |= run_site(site, config)
    return rc


def cmd_status(config: dict) -> int:
    state = StateStore()
    print(f"{'SITE':<10} {'TTL':>4} {'MAX':>4}  {'STATUS':<9} "
          f"{'LAST SUCCESS':<12} {'LAST FAILURE':<12}")
    for site, cfg in config["sites"].items():
        entry = state.get(site)
        ttl_max = cfg["ttl_max"]
        if entry is None:
            print(f"{site:<10} {'-':>4} {ttl_max:>4}  {'new':<9}")
            continue
        status = "disabled" if entry.get("disabled_at") else (
            "enabled" if cfg.get("enabled") else "off"
        )
        print(
            f"{site:<10} {entry['ttl_current']:>4} {ttl_max:>4}  {status:<9} "
            f"{entry.get('last_success') or '-':<12} "
            f"{entry.get('last_failure') or '-':<12}"
        )
    return 0


def cmd_reset(site: str, config: dict) -> int:
    cfg = site_config(site, config)
    state = StateStore()
    state.reset(site, cfg["ttl_max"])
    LogWriter(
        max_body_size_bytes=config["logging"]["max_body_size_bytes"]
    ).clear(site)
    print(f"[{site}] reset: TTL={cfg['ttl_max']}, logs cleared, enabled.")
    return 0


def cmd_getlogs(site: str, config: dict) -> int:
    logs = LogWriter(
        max_body_size_bytes=config["logging"]["max_body_size_bytes"]
    ).read(site)
    print(json.dumps(logs, indent=2))
    return 0


def cmd_validate(site: str) -> int:
    from jsonschema import Draft7Validator

    out_path = Path("data") / f"{site}.json"
    if not out_path.exists():
        print(f"[{site}] no output file at {out_path}")
        return 1
    with open(_SCHEMA_PATH, encoding="utf-8") as fh:
        validator = Draft7Validator(json.load(fh))
    with open(out_path, encoding="utf-8") as fh:
        records = json.load(fh)
    ok = True
    for i, rec in enumerate(records):
        for err in validator.iter_errors(rec):
            ok = False
            print(f"[{site}] record {i}: {err.message}")
    print(f"[{site}] {'valid' if ok else 'INVALID'} ({len(records)} records).")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Hash scraper pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="run all enabled scrapers")
    group.add_argument("--site", metavar="NAME", help="run a single scraper")
    group.add_argument("--status", action="store_true", help="show TTL state")
    group.add_argument("--reset", metavar="NAME", help="re-enable a scraper, clear logs")
    group.add_argument("--getlogs", metavar="NAME", help="print logs for a scraper")
    group.add_argument("--validate", metavar="NAME", help="validate existing output")
    parser.add_argument("--dry-run", action="store_true", help="run + validate, no write")
    args = parser.parse_args(argv)

    config = load_config()

    if args.status:
        return cmd_status(config)
    if args.reset:
        return cmd_reset(args.reset, config)
    if args.getlogs:
        return cmd_getlogs(args.getlogs, config)
    if args.validate:
        return cmd_validate(args.validate)
    if args.all:
        return run_all(config)
    if args.site:
        return run_site(args.site, config, dry_run=args.dry_run)
    return 1


if __name__ == "__main__":
    sys.exit(main())
