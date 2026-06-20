"""Shared geo helpers for Google Maps short-URL expansion and lat/lng parsing.

Used by site scrapers (GH3, SH3, etc.) to resolve compressed Google Maps URLs
to latitude/longitude coordinates.

Both functions are pure and stateless — import and call directly.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple

import requests

from models.run import Location


def expand_gmaps_short_url(url: str) -> str | None:
    """Follow a ``maps.app.goo.gl/...`` redirect and return the final URL.

    Returns ``None`` on any network error.
    """
    try:
        r = requests.head(url, allow_redirects=True, timeout=5)
        return r.url
    except requests.RequestException:
        return None


def expand_gmaps_short_urls_parallel(urls: list[str], max_workers: int = 10) -> dict[str, str | None]:
    """Expand a list of ``maps.app.goo.gl`` short URLs concurrently.

    Returns a mapping of ``original_url -> expanded_url`` (or ``None`` on error).
    """
    results: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_url = {pool.submit(expand_gmaps_short_url, url): url for url in urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            results[url] = future.result()
    return results


def parse_latlng_from_gmaps_url(url: str) -> Tuple[float, float] | Tuple[None, None]:
    """Extract ``/lat,lng,`` from a Google Maps URL.

    Returns ``(lat, lng)`` on match, ``(None, None)`` otherwise.
    """
    m = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+),", url)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def parse_latlng_from_button_links(
    soup,
    url_expander=expand_gmaps_short_url,
) -> dict:
    """Extract lat/lng from button links in parsed Elementor HTML.

    Checks Waze ``ll=`` query params first, then Google Maps short URLs.
    Returns a dict suitable for ``Location(**result)``.
    """
    # Check for Waze links with ll= query param
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "waze.com" in href and "ll=" in href:
            from urllib.parse import parse_qs, unquote, urlparse

            ll = parse_qs(urlparse(href).query).get("ll", [None])[0]
            if ll:
                parts = unquote(ll).split(",")
                if len(parts) == 2:
                    try:
                        return {"lat": float(parts[0]), "lng": float(parts[1])}
                    except ValueError:
                        pass

    # Check for Google Maps short URLs
    for a in soup.find_all("a", href=True):
        if "maps.app.goo.gl" in a["href"]:
            expanded = url_expander(a["href"])
            if expanded:
                lat, lng = parse_latlng_from_gmaps_url(expanded)
                if lat is not None:
                    return {"lat": lat, "lng": lng}
    return {}
