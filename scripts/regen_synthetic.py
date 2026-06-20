#!/usr/bin/env python3
"""Regenerate synthetic test output for scrapers that resolve goo.gl map links.

Two modes:

  python scripts/regen_synthetic.py --capture <site>
      Online. Runs the scraper against its raw fixture with a *capturing*
      expander that calls the live goo.gl service once per short URL, then writes
      tests/fixtures/<DIR>/gmaps_expansions.json (short URL -> full URL) tagged
      with a SHA-256 of the raw fixture. The only step that touches the network.

  python scripts/regen_synthetic.py <site>
      Offline. Loads the cached expansions (verifying the raw-fixture hash) and
      regenerates tests/synthetic/<site>/output.json deterministically.

Run --capture once (and again whenever a raw fixture changes), then commit the
expansion cache; offline regen and the test suite never call goo.gl after that.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.geo import expand_gmaps_short_url  # noqa: E402
from scrapers.sites.gh3 import GH3Scraper  # noqa: E402
from scrapers.sites.sh3 import SH3Scraper  # noqa: E402
from tests.conftest import make_gmaps_expander  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
SYNTHETIC = ROOT / "tests" / "synthetic"

# site key -> (raw fixture dir, raw filename, scraper class)
SITES = {
    "gh3": ("GH3", "raw_response.html", GH3Scraper),
    "sh3": ("SH3", "raw_response.json", SH3Scraper),
}


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def capture(site: str) -> None:
    fixture_dir, raw_name, scraper_cls = SITES[site]
    raw = (FIXTURES / fixture_dir / raw_name).read_text()

    recorded: dict[str, str] = {}

    def capturing_expander(short_url: str) -> str | None:
        expanded = expand_gmaps_short_url(short_url)
        if expanded is not None:
            recorded[short_url] = expanded
        return expanded

    # Running map() drives the scraper's own URL extraction, so recorded keys
    # match exactly what the scraper passes to the expander.
    scraper_cls().map(raw, url_expander=capturing_expander)

    cache = {
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "expansions": dict(sorted(recorded.items())),
    }
    out = FIXTURES / fixture_dir / "gmaps_expansions.json"
    _write_json(out, cache)
    print(f"captured {len(recorded)} expansion(s) -> {out.relative_to(ROOT)}")


def regen(site: str) -> None:
    fixture_dir, raw_name, scraper_cls = SITES[site]
    raw = (FIXTURES / fixture_dir / raw_name).read_text()

    expander = make_gmaps_expander(fixture_dir, raw)
    records = scraper_cls().map(raw, url_expander=expander)

    out = SYNTHETIC / site / "output.json"
    _write_json(out, records)
    print(f"wrote {len(records)} record(s) -> {out.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", choices=sorted(SITES), help="site key")
    parser.add_argument(
        "--capture",
        action="store_true",
        help="online: refresh the goo.gl expansion cache from the raw fixture",
    )
    args = parser.parse_args()

    if args.capture:
        capture(args.site)
    else:
        regen(args.site)


if __name__ == "__main__":
    main()
