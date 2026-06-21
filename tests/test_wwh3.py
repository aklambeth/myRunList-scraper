from scrapers.sites.wwh3 import WWH3Scraper


def test_wwh3_map_matches_synthetic(fixture, synthetic):
    raw = fixture("WWH3", "raw_response.json")
    scraper = WWH3Scraper()
    records = scraper.map(raw)
    assert records == synthetic("wwh3")


def test_wwh3_records_validate(fixture):
    raw = fixture("WWH3", "raw_response.json")
    scraper = WWH3Scraper()
    for record in scraper.map(raw):
        scraper.validate(record)
