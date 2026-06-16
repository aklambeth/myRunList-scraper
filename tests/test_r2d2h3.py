from scrapers.sites.r2d2h3 import R2D2H3Scraper

FIXTURE = "raw_response.html"


def test_r2d2h3_map_matches_synthetic(fixture, synthetic):
    scraper = R2D2H3Scraper()
    records = scraper.map(fixture("R2D2H3", FIXTURE))
    assert records == synthetic("r2d2h3")


def test_r2d2h3_records_validate(fixture):
    scraper = R2D2H3Scraper()
    for record in scraper.map(fixture("R2D2H3", FIXTURE)):
        scraper.validate(record)
