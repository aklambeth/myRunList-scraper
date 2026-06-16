#!/usr/bin/env python3
"""CLI entry point for the myRunList generator pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from generators import transformer
from generators.writers.html_writer import HTMLWriter
from generators.writers.json_writer import JSONWriter

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_records(data_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                records.extend(data)
        except (json.JSONDecodeError, OSError):
            print(f"[generate] warning: could not read {path.name}, skipping.", file=sys.stderr)
    return records


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="myRunList generator")
    parser.add_argument(
        "--json",
        metavar="FILE",
        nargs="?",
        const="",
        default=None,
        help="write JSON output (omit FILE to write to stdout)",
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        nargs="?",
        const="",
        default=None,
        help="write HTML output (omit FILE to write to stdout)",
    )
    parser.add_argument(
        "--transform",
        metavar="QUERY",
        help=f"apply a named transform (supported: {', '.join(transformer.QUERIES)})",
    )
    args = parser.parse_args(argv)

    json_dest: Path | None
    html_dest: Path | None

    json_requested = args.json is not None
    html_requested = args.html is not None

    # default: JSON to stdout
    if not json_requested and not html_requested:
        json_requested = True
        args.json = ""

    json_dest = Path(args.json) if args.json else None
    html_dest = Path(args.html) if args.html else None

    records = _load_records(_DATA_DIR)

    if args.transform:
        try:
            records = transformer.transform(records, args.transform)
        except ValueError as exc:
            print(f"[generate] error: {exc}", file=sys.stderr)
            return 1

    if json_requested:
        JSONWriter().write(records, json_dest)
    if html_requested:
        HTMLWriter().write(records, html_dest)

    return 0


if __name__ == "__main__":
    sys.exit(main())
