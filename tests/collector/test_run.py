"""Tests for collector/run.py: snapshots archive raw files, append rows once per source, and keep going
when a source fails; the HTTP fetch maps statuses the way the sources expect."""
import csv
import gzip
import json
from datetime import UTC, datetime

import pytest
import requests

from collector import run
from collector.sources import FetchError

NOW = datetime(2026, 10, 26, 19, 45, tzinfo=UTC)


def good(fetch, res):
    res.raw["report.json"] = b'{"ok": 1}'
    res.towns.append({"source": "good", "utility": "U", "town": "BARNSTABLE", "county": None, "cust_served": 100,
                      "cust_out": 7, "cust_out_masked": False, "source_updated": None})
    res.outages.append({"source": "good", "outage_id": "A", "lat": 41.6, "lon": -70.3, "cust_out": 7})


def bad(fetch, res):
    res.raw["partial.json"] = b"{}"
    raise FetchError("HTTP 500: https://example.org")


def rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_snapshot_archives_and_isolates_failures(tmp_path):
    m = run.snapshot(NOW, fetch=None, live=tmp_path, collectors={"good": good, "bad": bad})
    snap = tmp_path / "snapshots" / "20261026T194500Z"
    assert m["sources"]["good"]["status"] == "ok" and m["sources"]["bad"]["status"] == "error"
    assert "HTTP 500" in m["sources"]["bad"]["error"]
    assert json.loads(gzip.decompress((snap / "good" / "report.json.gz").read_bytes())) == {"ok": 1}
    assert (snap / "bad" / "partial.json.gz").exists()  # raw kept for a failed source
    assert json.loads((snap / "manifest.json").read_text()) == m
    towns = rows(tmp_path / "towns.csv")
    assert [(t["snapshot_utc"], t["source"], t["town"], t["cust_out"]) for t in towns] == [
        ("20261026T194500Z", "good", "BARNSTABLE", "7")]


def test_csv_header_written_once(tmp_path):
    run.snapshot(NOW, None, tmp_path, {"good": good})
    run.snapshot(NOW.replace(hour=20), None, tmp_path, {"good": good})
    lines = (tmp_path / "outages.csv").read_text().splitlines()
    assert lines[0].startswith("snapshot_utc,source,outage_id") and len(lines) == 3


def test_summary_line_flags_storm_mode_and_errors(tmp_path):
    m = {"snapshot_utc": "20261026T194500Z", "sources": {
        "eversource": {"status": "ok", "towns": 165, "outages": 2, "tile_requests": 9, "page_mode": "STORM"},
        "mema": {"status": "error", "error": "FetchError: HTTP 500"}}}
    line = run.summary_line(m)
    assert "eversource 165 towns, 2 outages, 9 tile req [STORM]" in line and "mema ERROR" in line


class FakeResponse:
    def __init__(self, status, body=b""):
        self.status_code, self.content = status, body
        self.ok = 200 <= status < 400


@pytest.fixture
def responses(monkeypatch):
    queue: list = []

    def get(self, url, timeout):
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    return queue


def test_fetch_statuses(responses):
    fetch = run.make_fetch()
    responses += [FakeResponse(404)]
    assert fetch("u") is None
    responses += [FakeResponse(403)]
    assert fetch("u", (403, 404)) is None
    responses += [FakeResponse(200, gzip.compress(b"hello"))]
    assert fetch("u") == b"hello"
    responses += [FakeResponse(403)]
    with pytest.raises(FetchError, match="HTTP 403"):
        fetch("u")


def test_fetch_retries_server_errors(responses):
    responses += [FakeResponse(503), requests.ConnectionError(), FakeResponse(200, b"ok")]
    assert run.make_fetch(retries=2)("u") == b"ok"
    responses += [FakeResponse(500)] * 3
    with pytest.raises(FetchError, match="HTTP 500"):
        run.make_fetch(retries=2)("u")
