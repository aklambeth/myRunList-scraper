import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"
SYNTHETIC = ROOT / "tests" / "synthetic"


def load_fixture(site: str, filename: str) -> str:
    return (FIXTURES / site / filename).read_text()


def load_synthetic(name: str) -> list:
    return json.loads((SYNTHETIC / name / "output.json").read_text())


def make_gmaps_expander(site: str, raw: str):
    """Build an offline goo.gl expander from the committed expansion cache.

    Verifies the cache's ``raw_sha256`` against ``raw`` (the raw fixture text);
    a mismatch means the raw fixture changed and the cache is stale. A per-URL
    miss also raises. Both errors name the ``--capture`` command to re-run.
    """
    cache = json.loads((FIXTURES / site / "gmaps_expansions.json").read_text())
    if hashlib.sha256(raw.encode()).hexdigest() != cache["raw_sha256"]:
        raise AssertionError(
            f"{site}: raw_response changed — gmaps cache stale; "
            f"re-run scripts/regen_synthetic.py --capture {site.lower()}"
        )
    expansions = cache["expansions"]

    def expander(short_url: str) -> str:
        if short_url not in expansions:
            raise KeyError(
                f"{short_url} not cached for {site} — "
                f"re-run scripts/regen_synthetic.py --capture {site.lower()}"
            )
        return expansions[short_url]

    return expander


@pytest.fixture
def fixture():
    return load_fixture


@pytest.fixture
def synthetic():
    return load_synthetic


@pytest.fixture
def gmaps_expander():
    return make_gmaps_expander
