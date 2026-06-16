from scrapers.sites.gh3 import GH3Scraper


def test_gh3_map_matches_synthetic(fixture, synthetic):
    scraper = GH3Scraper()
    records = scraper.map(fixture("GH3", "raw_response.html"))
    assert records == synthetic("gh3")


def test_gh3_records_validate(fixture):
    scraper = GH3Scraper()
    for record in scraper.map(fixture("GH3", "raw_response.html")):
        scraper.validate(record)
