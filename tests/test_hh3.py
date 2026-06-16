from unittest.mock import patch

import pytest

from scrapers.sites.hh3 import (
    HH3Scraper,
    parse_date_time,
    parse_hares,
    parse_location_name,
    parse_runno,
)

FIXTURE = "raw_response.html"


def test_hh3_map_matches_synthetic(fixture, synthetic):
    scraper = HH3Scraper()
    records = scraper.map(fixture("HH3", FIXTURE))
    assert records == synthetic("hh3")


def test_hh3_records_validate(fixture):
    scraper = HH3Scraper()
    for record in scraper.map(fixture("HH3", FIXTURE)):
        scraper.validate(record)


# --- parse_runno ---

def test_parse_runno_plain():
    assert parse_runno("1946") == (1946, None)


def test_parse_runno_fnl_suffix():
    assert parse_runno("1947 FNL") == (1947, "FNL")


def test_parse_runno_word_suffix():
    assert parse_runno("1951 Solstice") == (1951, "Solstice")


def test_parse_runno_invalid():
    with pytest.raises(ValueError):
        parse_runno("no number here")


# --- parse_date_time ---

def test_parse_date_only():
    assert parse_date_time("31/05/26") == ("2026-05-31", None)


def test_parse_date_with_time():
    assert parse_date_time("21/06/26 04:30") == ("2026-06-21", "04:30")


# --- parse_hares ---

def test_parse_hares_ampersand():
    assert parse_hares("OMO & Tinkerbell") == ["OMO", "Tinkerbell"]


def test_parse_hares_trailing_ampersand():
    assert parse_hares("Mudlark &") == ["Mudlark"]


def test_parse_hares_comma_and_ampersand():
    assert parse_hares("Mudlark,Sunny D, K9 & Yellow Peril") == [
        "Mudlark", "Sunny D", "K9", "Yellow Peril"
    ]


def test_parse_hares_single():
    assert parse_hares("Duckbutt") == ["Duckbutt"]


def test_parse_hares_empty():
    assert parse_hares("") == []


# --- parse_location_name ---

def test_parse_location_name_valid():
    assert parse_location_name("Netley") == "Netley"


def test_parse_location_name_empty():
    assert parse_location_name("") is None


def test_parse_location_name_question_mark():
    assert parse_location_name("?") is None


# --- integration: dry-run pipeline ---

def test_run_filters_past_dates(fixture):
    """Full pipeline (map → date filter → validate) must drop records before today."""
    html = fixture("HH3", FIXTURE)
    scraper = HH3Scraper()
    with patch.object(scraper, "fetch", return_value=html):
        records = scraper.run()
    for record in records:
        assert record["date"] >= "2026-06-16", (
            f"Past record leaked into output: {record['date']}"
        )
