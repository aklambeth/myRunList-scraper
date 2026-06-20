from scrapers.sites.sh3 import SH3Scraper


def test_sh3_map_matches_synthetic(fixture, synthetic, gmaps_expander):
    raw = fixture("SH3", "raw_response.json")
    scraper = SH3Scraper()
    records = scraper.map(raw, url_expander=gmaps_expander("SH3", raw))
    assert records == synthetic("sh3")


def test_sh3_records_validate(fixture, gmaps_expander):
    raw = fixture("SH3", "raw_response.json")
    scraper = SH3Scraper()
    for record in scraper.map(raw, url_expander=gmaps_expander("SH3", raw)):
        scraper.validate(record)
