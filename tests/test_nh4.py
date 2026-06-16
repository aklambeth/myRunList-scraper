from scrapers.sites.nh4 import NH4Scraper


def test_nh4_map_matches_synthetic(fixture, synthetic):
    scraper = NH4Scraper()
    records = scraper.map(fixture("NH4", "raw_response.csv"))
    assert records == synthetic("nh4")


def test_nh4_records_validate(fixture):
    scraper = NH4Scraper()
    for record in scraper.map(fixture("NH4", "raw_response.csv")):
        scraper.validate(record)
