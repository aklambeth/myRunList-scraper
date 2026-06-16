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


@pytest.fixture
def fixture():
    return load_fixture


@pytest.fixture
def synthetic():
    return load_synthetic
