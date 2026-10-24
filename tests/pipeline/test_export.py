"""Tests for pipeline/export.py (Req 1.1, 1.4, 1.5, 1.6, 1.10, 4.10, 4.15, 4.16, 5.3, 5.7, 6.9, 7.8, 25.1, 25.2, 26.7).

Runs the real pipeline (cached fetches, --no-llm) once, then exports into tmp directories.
"""
import json
import re

import numpy as np
import pytest
from shapely.geometry import shape

from pipeline import common, export, privacy_guard
from pipeline.common import CAPE_TOWNS, HOURS, load_languages, load_scoring
from pipeline.run import STEPS, Ctx, run

# The privacy guard's own patterns (design.md).
PHONE = re.compile(privacy_guard.PHONE)
ADDRESS = re.compile(privacy_guard.ADDRESS)


@pytest.fixture(scope="module")
def ctx():
    c = Ctx(scoring=load_scoring(), languages=load_languages(), no_llm=True)
    run(c, [s for s in STEPS if s[0] not in ("export", "privacy_guard")])
    return c


@pytest.fixture(scope="module")
def out(ctx, tmp_path_factory):
    d = tmp_path_factory.mktemp("processed")
    export.export(ctx, d)
    return d


def load(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_writes_every_file_in_place_with_sources_last(ctx, tmp_path, monkeypatch):
    order = []
    real = export.write_json
    monkeypatch.setattr(export, "write_json", lambda p, o: (order.append(p), real(p, o)))
    export.export(ctx, tmp_path)
    assert [p.name for p in order] == [*export.FILES, export.SOURCES]
    assert all(p.parent == tmp_path for p in order)  # no staging directory (Req 1.10)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([*export.FILES, export.SOURCES])


def test_export_is_byte_identical_on_rerun(ctx, out, tmp_path):
    export.export(ctx, tmp_path)
    for name in (*export.FILES, export.SOURCES):
        assert (tmp_path / name).read_bytes() == (out / name).read_bytes(), name


def test_every_file_has_tz(out):
    for name in (*export.FILES, export.SOURCES):
        assert load(out, name)["tz"] == "America/New_York", name


def test_geojson_is_valid_epsg4326(out):
    for name, n in (("cape_tracts.geojson", None), ("cape_towns.geojson", 15)):
        fc = load(out, name)
        assert fc["type"] == "FeatureCollection"
        if n:
            assert len(fc["features"]) == n
        for f in fc["features"]:
            g = shape(f["geometry"])
            assert g.is_valid and not g.is_empty
            minx, miny, maxx, maxy = g.bounds
            assert -71.5 < minx < maxx < -69.5 and 41.0 < miny < maxy < 42.5  # lon/lat on Cape Cod
    tracts = load(out, "cape_tracts.geojson")["features"]
    p = tracts[0]["properties"]
    assert set(p["need"]) == {"seniors_alone", "disability", "limited_english", "no_vehicle", "renter",
                              "elec_dependent"}
    assert p["need"]["elec_dependent"]["unit"] == "per_1000"
    towns = {f["properties"]["name"]: f["properties"] for f in load(out, "cape_towns.geojson")["features"]}
    assert towns["Chatham"]["anchor_count"] == 0
    assert {t for t, v in towns.items() if v["customers_label"]} == {"Chatham", "Sandwich"}


def test_timeline_arrays_align_and_sum(ctx, out):
    tl = load(out, "cape_timeline.json")
    assert tl["hours"] == HOURS and sorted(tl["towns"]) == sorted(CAPE_TOWNS)
    assert tl["provenance"] == {"out_pct": common.PROVENANCE["reconstructed"],
                                "hours_dark": common.PROVENANCE["reconstructed"]}  # Req 4.16
    for T, v in tl["towns"].items():
        for k in ("out_pct", "hours_dark", "wires_raw", "wires", "telecom", "telecom_rule", "telecom_event_ids",
                  "lifelines", "pinned", "lower_bound"):
            assert len(v[k]) == len(HOURS), (T, k)
        total = np.sum([v["contrib"][c] for c in ("out_pct", "hours_dark", "wires", "telecom")], axis=0)
        assert np.allclose(total, v["lifelines"], atol=1e-5)
    need = ctx["need"]["need_t"]
    for g, v in tl["tracts"].items():
        life = np.array(tl["towns"][v["town"]]["lifelines"])
        assert np.allclose(v["priority"], need[g] * life, atol=1e-5)  # Req 7.8
        assert v["channel"] == ["door_knock" if x else "sms" for x in tl["towns"][v["town"]]["telecom"]]
    h = HOURS[40]
    assert [r["geoid"] for r in tl["queue"][h]] == [g for g, v in sorted(
        tl["tracts"].items(), key=lambda kv: kv[1]["rank"][40] or 99) if v["rank"][40]]


def test_sources_cite_used_rows_and_hide_excluded_values(ctx, out):
    s = load(out, "sources.json")
    rows = {(i["file"], i["row"]) for i in s["inputs"]}
    assert all(i["source_name"] and i["source_url"].startswith("http") for i in s["inputs"])
    anchors_file = "data/raw/curated/cape_town_outage_anchors.csv"
    assert {(anchors_file, a.row) for a in ctx["anchors"]} <= rows  # Req 25.2
    assert sum(i["file"].endswith("cape_telecom_events.csv") for i in s["inputs"]) == len(ctx["telecom_events"])
    assert all(set(e) == {"file", "row", "reason"} for e in s["excluded"])  # no values
    assert not rows & {(e["file"], e["row"]) for e in s["excluded"]}
    assert s["towns_without_anchors"] == ["Chatham"]  # Req 4.10
    assert {"town": "PLYMOUTH", "calls": 174} in s["tab5_unmatched_towns"]  # Req 5.3
    assert set(s["customer_count_sources"]) == set(CAPE_TOWNS)
    keys = {a["key"] for a in s["assumptions"]}
    assert {"telecom_model", "telecom_observed_default_hours", "acs_customers", "household_language_mix.Barnstable",
            "household_language_mix.Yarmouth", "towns_without_anchors", "empower_zip_to_tract", "empower_masking",
            "help_line.cape"} <= keys
    assert any(f.get("vintage") for f in s["fetches"])


def test_sitrep_009_row_is_excluded_without_value(ctx, tmp_path, monkeypatch):
    csv = tmp_path / "timeline.csv"
    csv.write_text("datetime_local,customers_out,scope,source_name,source_url,note\n"
                   "2026-02-23T07:00,50000,cape_eversource,Live blog,https://example.org/a,\n"
                   "2026-02-26T09:00,133000,cape_eversource,County situation report #009,https://example.org/b,\n",
                   encoding="utf-8")
    monkeypatch.setattr(export, "TIMELINE_CSV", csv)
    inputs, extra = export.curated_inputs(ctx)
    mine = [i for i in inputs if i["file"] == "timeline.csv"]
    assert [i["row"] for i in mine] == [2]
    assert [e["row"] for e in extra if e["file"] == "timeline.csv"] == [3]
    text = json.dumps([inputs, extra])
    assert "133" not in text and "example.org/b" not in text  # Req 4.15


def test_no_phone_numbers_addresses_or_call_rows(out):
    for p in out.iterdir():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            assert not PHONE.search(line), f"{p.name}:{i}: phone_number"  # Req 26.7
            assert not ADDRESS.search(line), f"{p.name}:{i}: street_address"
    hh = load(out, "households.json")["households"]
    assert hh and all(h["synthetic"] is True and set(h) <= set(export.HOUSEHOLD_KEYS) for h in hh)
    assert all(r["synthetic"] is True for r in load(out, "responders.json")["responders"])
    tl = (out / "cape_timeline.json").read_text(encoding="utf-8")
    assert "received" not in tl and "street" not in tl.casefold()  # town-hour aggregates only (Req 5.7)


def test_telecom_events_exported_regardless_of_flag(ctx, out):
    ev = load(out, "telecom_events.json")["events"]
    assert len(ev) == len(ctx["telecom_events"]) and not any(e["drives_reach_flag"] for e in ev)
    for e in ev:  # Req 6.9
        for k in ("system", "status", "affects", "start_local", "end_local", "source_name", "source_url"):
            assert k in e
