from scrapers.sites.dh3 import DH3Scraper


def test_dh3_map_matches_synthetic(fixture, synthetic):
    scraper = DH3Scraper()
    records = scraper.map(fixture("DH3", "raw_response.json"))
    assert records == synthetic("dh3")


def test_dh3_records_validate(fixture):
    scraper = DH3Scraper()
    for record in scraper.map(fixture("DH3", "raw_response.json")):
        scraper.validate(record)
