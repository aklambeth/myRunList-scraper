"""Tests for mcpserver tool logic — filtering, config write helper, generate flags."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import mcpserver.server as srv

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RECORDS = [
    {"kennel": "nh4", "date": "2026-07-01", "runno": 1, "name": "NH4", "location": {}},
    {"kennel": "nh4", "date": "2026-08-15", "runno": 2, "name": "NH4", "location": {}},
    {"kennel": "dh3", "date": "2026-07-10", "runno": 10, "name": "DH3", "location": {}},
    {"kennel": "dh3", "date": "2025-12-01", "runno": 9, "name": "DH3", "location": {}},
]


def _patch_load(records=None):
    """Patch _load_records to return synthetic data."""
    return patch.object(srv, "_load_records", return_value=records or _RECORDS)


# ---------------------------------------------------------------------------
# get_runs — filtering
# ---------------------------------------------------------------------------

def test_get_runs_no_filter():
    with _patch_load():
        result = srv.get_runs()
    assert len(result) == 4


def test_get_runs_filter_by_site():
    with _patch_load():
        result = srv.get_runs(site="nh4")
    assert all(r["kennel"] == "nh4" for r in result)
    assert len(result) == 2


def test_get_runs_filter_start_date():
    with _patch_load():
        result = srv.get_runs(start_date="2026-07-05")
    dates = [r["date"] for r in result]
    assert all(d >= "2026-07-05" for d in dates)
    assert "2026-07-01" not in dates
    assert "2025-12-01" not in dates


def test_get_runs_filter_end_date():
    with _patch_load():
        result = srv.get_runs(end_date="2026-07-31")
    assert all(r["date"] <= "2026-07-31" for r in result)


def test_get_runs_site_and_date_combined():
    with _patch_load():
        result = srv.get_runs(site="dh3", start_date="2026-01-01")
    assert len(result) == 1
    assert result[0]["runno"] == 10


# ---------------------------------------------------------------------------
# generate_json — all_runs flag
# ---------------------------------------------------------------------------

def test_generate_json_applies_transform_by_default():
    transformed = [_RECORDS[0]]
    with _patch_load(), \
         patch("generators.transformer.transform", return_value=transformed) as mock_t:
        result = srv.generate_json()
    mock_t.assert_called_once_with(_RECORDS, "latest")
    assert result == transformed


def test_generate_json_all_runs_skips_transform():
    with _patch_load(), \
         patch("generators.transformer.transform") as mock_t:
        result = srv.generate_json(all_runs=True)
    mock_t.assert_not_called()
    assert len(result) == 4


# ---------------------------------------------------------------------------
# generate_html — all_runs flag
# ---------------------------------------------------------------------------

def test_generate_html_returns_string():
    with _patch_load(), \
         patch("generators.transformer.transform", return_value=_RECORDS[:1]):
        html = srv.generate_html()
    assert isinstance(html, str)
    assert len(html) > 0


def test_generate_html_all_runs_skips_transform():
    with _patch_load(), \
         patch("generators.transformer.transform") as mock_t:
        html = srv.generate_html(all_runs=True)
    mock_t.assert_not_called()
    assert isinstance(html, str)


# ---------------------------------------------------------------------------
# _update_site_config — atomic write
# ---------------------------------------------------------------------------

_SAMPLE_CONFIG = {
    "logging": {"max_body_size_bytes": 10240},
    "data": {"archive_retention_days": 365},
    "sites": {
        "nh4": {"name": "nh4", "display_name": "NH4", "ttl_max": 5, "enabled": True},
    },
}


def test_update_site_config_enabled(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(_SAMPLE_CONFIG), encoding="utf-8")
    with patch.object(srv, "_CONFIG_PATH", cfg_path):
        srv._update_site_config("nh4", {"enabled": False})
    updated = yaml.safe_load(cfg_path.read_text())
    assert updated["sites"]["nh4"]["enabled"] is False


def test_update_site_config_ttl_max(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(_SAMPLE_CONFIG), encoding="utf-8")
    with patch.object(srv, "_CONFIG_PATH", cfg_path):
        srv._update_site_config("nh4", {"ttl_max": 3})
    updated = yaml.safe_load(cfg_path.read_text())
    assert updated["sites"]["nh4"]["ttl_max"] == 3


def test_update_site_config_atomic(tmp_path):
    """Tmp file should not be left behind after a successful write."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(_SAMPLE_CONFIG), encoding="utf-8")
    with patch.object(srv, "_CONFIG_PATH", cfg_path):
        srv._update_site_config("nh4", {"enabled": False})
    assert not (tmp_path / "config.yaml.tmp").exists()


def test_update_site_config_unknown_site(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(_SAMPLE_CONFIG), encoding="utf-8")
    with patch.object(srv, "_CONFIG_PATH", cfg_path):
        with pytest.raises(ValueError, match="Unknown site"):
            srv._update_site_config("missing", {"enabled": False})


# ---------------------------------------------------------------------------
# set_scraper_ttl_max — validation
# ---------------------------------------------------------------------------

def test_set_scraper_ttl_max_rejects_zero(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(_SAMPLE_CONFIG), encoding="utf-8")
    with patch.object(srv, "_CONFIG_PATH", cfg_path), \
         patch.object(srv, "_load_config", return_value=_SAMPLE_CONFIG):
        with pytest.raises(ValueError):
            srv.set_scraper_ttl_max("nh4", 0)
