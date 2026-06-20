import pytest

from scrapers.sites.gh3 import GH3Scraper, parse_latlng


def test_gh3_map_matches_synthetic(fixture, synthetic, gmaps_expander):
    raw = fixture("GH3", "raw_response.html")
    scraper = GH3Scraper()
    records = scraper.map(raw, url_expander=gmaps_expander("GH3", raw))
    assert records == synthetic("gh3")


def test_gh3_records_validate(fixture, gmaps_expander):
    raw = fixture("GH3", "raw_response.html")
    scraper = GH3Scraper()
    for record in scraper.map(raw, url_expander=gmaps_expander("GH3", raw)):
        scraper.validate(record)


def test_parse_latlng_falls_back_to_gmaps():
    html = "<a href='https://maps.app.goo.gl/ABC123'>Google maps</a>"
    fake_expanded = "https://www.google.com/maps/place/Foo/@51.1234,-0.5678,17z/data=..."
    lat, lng = parse_latlng(html, url_expander=lambda _: fake_expanded)
    assert lat == pytest.approx(51.1234)
    assert lng == pytest.approx(-0.5678)


def test_parse_latlng_gmaps_expander_failure():
    html = "<a href='https://maps.app.goo.gl/ABC123'>Google maps</a>"
    lat, lng = parse_latlng(html, url_expander=lambda _: None)
    assert lat is None
    assert lng is None
