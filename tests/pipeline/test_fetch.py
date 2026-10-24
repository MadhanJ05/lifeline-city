"""Tests for pipeline/fetch.py: cache hits make no network call, failures raise and write nothing."""
import json

import pandas as pd
import pytest

from pipeline import common, fetch
from pipeline.common import PipelineError

DEAD = "http://127.0.0.1:9/never"  # discard port: any real network attempt fails


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CACHE", tmp_path)
    fetch.LOG.clear()
    return tmp_path


def test_cache_hit_skips_network(cache):
    (cache / "thing.json").write_text('{"ok": 1}')
    assert json.loads(fetch.cached_get("thing", DEAD)) == {"ok": 1}
    assert fetch.LOG == [{"name": "thing", "url": DEAD, "cached": True}]


def test_failed_fetch_without_cache_raises_and_writes_nothing(cache):
    with pytest.raises(PipelineError) as e:
        fetch.cached_get("thing", DEAD, ext="zip")
    assert e.value.args[:2] == ("thing", DEAD)
    assert list(cache.iterdir()) == []


def test_census_key_is_not_recorded(cache):
    (cache / "a.json").write_text("[]")
    fetch.cached_get("a", "https://example.org/x", {"get": "NAME", "key": "SECRET"})
    assert "SECRET" not in fetch.LOG[0]["url"] and "get=NAME" in fetch.LOG[0]["url"]


def _fake_census(vintage_ok):
    """Stub for the network boundary: answers ACS calls for `vintage_ok`, fails every other vintage."""
    def get(name, url, params=None, ext="json", vintage=None):
        if vintage != vintage_ok:
            raise PipelineError(name, url, "HTTPError: 404")
        if params is None:
            return json.dumps({"variables": {"B25001_001E": {"label": "Estimate!!Total"}}}).encode()
        return json.dumps([["NAME", "B25001_001E", "state", "county", "county subdivision"],
                           ["Bourne town", "10000", "25", "001", "08085"],
                           ["Barnstable Town city", "-666666666", "25", "001", "03690"]]).encode()
    return get


def test_acs_falls_back_one_vintage(cache, monkeypatch):
    monkeypatch.setattr(fetch, "cached_get", _fake_census(2024))
    frame, vintage, labels = fetch.acs(["B25001_001E"], "cousub", vintages=(2025, 2024))
    assert vintage == 2024 and labels == {"B25001_001E": "Estimate!!Total"}
    assert list(frame["GEOID"]) == ["2500103690", "2500108085"]
    assert pd.api.types.is_numeric_dtype(frame["B25001_001E"])


def test_acs_fails_when_both_vintages_fail(cache, monkeypatch):
    monkeypatch.setattr(fetch, "cached_get", _fake_census(2020))
    with pytest.raises(PipelineError, match="2025: .*2024: "):
        fetch.acs(["B25001_001E"], "cousub", vintages=(2025, 2024))


def test_acs_missing_variable_fails_loudly(cache, monkeypatch):
    monkeypatch.setattr(fetch, "cached_get", _fake_census(2024))
    with pytest.raises(PipelineError, match="B25001_002E"):
        fetch.acs(["B25001_001E", "B25001_002E"], "cousub", vintages=(2024,))
