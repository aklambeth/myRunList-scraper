from unittest.mock import patch

import pytest

from scrapers.sites.chi3 import (
    CHI3Scraper,
    parse_datetime,
    parse_hares,
    parse_runno,
)

FIXTURE = "raw_response.html"


def test_chi3_map_matches_synthetic(fixture, synthetic):
    scraper = CHI3Scraper()
    records = scraper.map(fixture("CHI3", FIXTURE))
    assert records == synthetic("chi3")


def test_chi3_records_validate(fixture):
    scraper = CHI3Scraper()
    for record in scraper.map(fixture("CHI3", FIXTURE)):
        scraper.validate(record)


# --- parse_runno ---

def test_parse_runno():
    assert parse_runno("Run 1088") == 1088


def test_parse_runno_no_prefix():
    assert parse_runno("1088") == 1088


# --- parse_datetime ---

def test_parse_datetime():
    assert parse_datetime("2026-06-21 11:00") == ("2026-06-21", "11:00")


# --- parse_hares ---

def test_parse_hares_with_label_and_notes():
    result = parse_hares("Visit: Deepcut Hash. Hares: Yorkie & Yellow Peril")
    assert result["hares"] == ["Yorkie", "Yellow Peril"]
    assert result["notes"] == "Visit: Deepcut Hash"


def test_parse_hares_no_label():
    result = parse_hares("Bika")
    assert result["hares"] == ["Bika"]
    assert "notes" not in result


def test_parse_hares_ampersand_split():
    result = parse_hares("Hares: Alice & Bob")
    assert result["hares"] == ["Alice", "Bob"]


def test_parse_hares_and_split():
    result = parse_hares("Hares: Alice and Bob")
    assert result["hares"] == ["Alice", "Bob"]


def test_parse_hares_comma_split():
    result = parse_hares("Hares: Alice, Bob")
    assert result["hares"] == ["Alice", "Bob"]


# --- integration: past-date filter ---

def test_run_filters_past_dates(fixture):
    """Full pipeline must drop records with dates before today."""
    html = fixture("CHI3", FIXTURE)
    scraper = CHI3Scraper()
    with patch.object(scraper, "fetch", return_value=html):
        records = scraper.run()
    for record in records:
        assert record["date"] >= "2026-06-16", (
            f"Past record leaked into output: {record['date']}"
        )
