import json

import pytest

from scrapers.base import FailureMode
from scrapers.logwriter import LogWriter
from scrapers.output import OutputWriter
from scrapers.state import StateStore

TTL_MAX = 5


@pytest.fixture
def state(tmp_path):
    return StateStore(path=tmp_path / "state.json")


def test_transient_decrements_by_one(state):
    state.record_success("nh4", TTL_MAX)
    entry = state.record_failure("nh4", TTL_MAX, FailureMode.TRANSIENT)
    assert entry["ttl_current"] == 4
    assert entry["disabled_at"] is None


def test_auth_decrements_by_two(state):
    state.record_success("nh4", TTL_MAX)
    entry = state.record_failure("nh4", TTL_MAX, FailureMode.AUTH)
    assert entry["ttl_current"] == 3


def test_fatal_zeros_and_disables(state):
    state.record_success("nh4", TTL_MAX)
    entry = state.record_failure("nh4", TTL_MAX, FailureMode.FATAL)
    assert entry["ttl_current"] == 0
    assert entry["disabled_at"] is not None
    assert state.is_disabled("nh4")


def test_ttl_floors_at_zero_and_disables(state):
    state.record_success("nh4", TTL_MAX)
    for _ in range(3):
        state.record_failure("nh4", TTL_MAX, FailureMode.AUTH)
    assert state.get("nh4")["ttl_current"] == 0
    assert state.is_disabled("nh4")


def test_success_resets_and_reenables(state):
    state.record_failure("nh4", TTL_MAX, FailureMode.FATAL)
    assert state.is_disabled("nh4")
    entry = state.record_success("nh4", TTL_MAX)
    assert entry["ttl_current"] == TTL_MAX
    assert entry["disabled_at"] is None


def test_reset_reenables(state):
    state.record_failure("nh4", TTL_MAX, FailureMode.FATAL)
    entry = state.reset("nh4", TTL_MAX)
    assert entry["ttl_current"] == TTL_MAX
    assert not state.is_disabled("nh4")


def test_state_persists_across_instances(tmp_path):
    path = tmp_path / "state.json"
    StateStore(path=path).record_success("nh4", TTL_MAX)
    assert StateStore(path=path).get("nh4")["ttl_current"] == TTL_MAX


def test_log_file_count_capped(tmp_path):
    writer = LogWriter(max_body_size_bytes=1024, root=tmp_path)
    site_dir = tmp_path / "nh4"
    # Pre-seed more than ttl_max dated files, then write once to trigger purge.
    site_dir.mkdir()
    for day in range(1, 9):
        (site_dir / f"2026-01-0{day}.json").write_text("{}")
    writer.write(
        site="nh4", version="1.0.0", status="failure", ttl_before=1, ttl_after=0,
        records_parsed=0, ttl_max=TTL_MAX, failure_mode=FailureMode.TRANSIENT,
    )
    assert len(list(site_dir.glob("*.json"))) == TTL_MAX


def test_log_body_truncated(tmp_path):
    writer = LogWriter(max_body_size_bytes=10, root=tmp_path)
    path = writer.write(
        site="nh4", version="1.0.0", status="failure", ttl_before=1, ttl_after=0,
        records_parsed=0, ttl_max=TTL_MAX, failure_mode=FailureMode.TRANSIENT,
        response={"status_code": 200, "headers": {}, "body_size_bytes": 100,
                  "body": "x" * 100},
    )
    entry = json.loads(path.read_text())
    assert entry["response"]["body_truncated"] is True
    assert len(entry["response"]["body"]) == 10


def test_log_clear(tmp_path):
    writer = LogWriter(root=tmp_path)
    writer.write(site="nh4", version="1.0.0", status="success", ttl_before=5,
                 ttl_after=5, records_parsed=3, ttl_max=TTL_MAX)
    writer.clear("nh4")
    assert writer.read("nh4") == []


def test_output_archives_previous(tmp_path):
    writer = OutputWriter(archive_retention_days=365, root=tmp_path)
    writer.write("nh4", [{"runno": 1}])
    writer.write("nh4", [{"runno": 2}])
    current = json.loads((tmp_path / "nh4.json").read_text())
    assert current == [{"runno": 2}]
    archives = list((tmp_path / "archive" / "nh4").glob("nh4_*.json"))
    assert len(archives) == 1
    assert json.loads(archives[0].read_text()) == [{"runno": 1}]


def test_output_purges_old_archives(tmp_path):
    import os
    import time

    writer = OutputWriter(archive_retention_days=1, root=tmp_path)
    archive_dir = tmp_path / "archive" / "nh4"
    archive_dir.mkdir(parents=True)
    old = archive_dir / "nh4_20200101T000000.json"
    old.write_text("[]")
    old_time = time.time() - 5 * 86400
    os.utime(old, (old_time, old_time))

    writer.write("nh4", [{"runno": 1}])  # triggers purge
    assert not old.exists()
