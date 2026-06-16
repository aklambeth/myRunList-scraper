"""Discover and instantiate scrapers from config.yaml.

Adding a new scraper requires only a config entry plus the scraper module —
no edits here.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml

from scrapers.base import BaseScraper

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: Path = _CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _resolve_class(site_key: str, class_name: str) -> type[BaseScraper]:
    module = importlib.import_module(f"scrapers.sites.{site_key}")
    cls = getattr(module, class_name, None)
    if cls is None or not issubclass(cls, BaseScraper):
        raise ValueError(
            f"{class_name} not found or not a BaseScraper in scrapers.sites.{site_key}"
        )
    return cls


def build_scraper(site_key: str, config: dict | None = None) -> BaseScraper:
    config = config or load_config()
    site_cfg = config["sites"].get(site_key)
    if site_cfg is None:
        raise KeyError(f"Unknown site: {site_key}")
    cls = _resolve_class(site_key, site_cfg["scraper"])
    return cls()


def site_config(site_key: str, config: dict | None = None) -> dict:
    config = config or load_config()
    return config["sites"][site_key]


def enabled_sites(config: dict | None = None) -> list[str]:
    config = config or load_config()
    return [k for k, v in config["sites"].items() if v.get("enabled")]


def all_sites(config: dict | None = None) -> list[str]:
    config = config or load_config()
    return list(config["sites"].keys())
