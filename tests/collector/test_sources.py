"""Tests for collector/sources.py: parsers on fixtures shaped like the live feeds (2026-10-26), and the
tile crawl's rule that each customer is counted once."""
import json

import pytest

from collector import geo, sources
from collector.sources import FetchError, SourceResult

BARNSTABLE, FALMOUTH, BOURNE = (41.65290, -70.28690), (41.55150, -70.61530), (41.74120, -70.59890)


def item(point, cust, cluster=False, inc_id=None, **desc):
    return {"id": "x", "title": "Area Outage",
            "desc": {"cluster": cluster, "cust_a": {"val": cust}, "n_out": 1, "inc_id": inc_id, **desc},
            "geom": {"p": [geo.encode_polyline([point])]}}


def tile(*items):
    return json.dumps({"file_title": "t", "file_data": list(items)}).encode()


def fake_fetch(pages: dict[str, bytes], fail: tuple[str, ...] = ()):
    def fetch(url, missing=(404,)):
        if url in fail:
            raise FetchError(f"HTTP 500: {url}")
        if url in pages:
            return pages[url]
        if 404 in missing:
            return None
        raise FetchError(f"HTTP 404: {url}")
    return fetch


# ---------------------------------------------------------------- MEMA


def test_parse_mema():
    body = (b"Town,County,MEMA Region,Utility,Total Customers,Without Power,Percent Without Power,Notes,Last Updated\n"
            b'BOURNE,BARNSTABLE,2,Eversource - Eastern MA,13302,1,0.00,"",2026/10/26 03:10 pm\n'
            b'WARE,HAMPSHIRE,3,National Grid,"4,986",17,0.34,"",2026/10/26 03:14 pm\n')
    rows = sources.parse_mema(body)
    assert rows[0] == {"source": "mema", "utility": "Eversource - Eastern MA", "town": "BOURNE",
                       "county": "BARNSTABLE", "cust_served": 13302, "cust_out": 1, "cust_out_masked": False,
                       "source_updated": "2026-10-26T15:10:00-04:00"}
    assert (rows[1]["cust_served"], rows[1]["cust_out"]) == (4986, 17)


# ---------------------------------------------------------------- tile items and crawl


def test_outage_row_eversource_and_national_grid_shapes():
    ev = sources.outage_row("eversource", "0302332", item(BARNSTABLE, 4, inc_id="W1-0", cause="TREI",
                                                          start="2026-10-26T12:37:32-0400"))
    assert ev["lat"] == BARNSTABLE[0] and ev["lon"] == BARNSTABLE[1] and ev["zoom"] == 7
    assert (ev["outage_id"], ev["cause"], ev["cust_out_masked"]) == ("W1-0", "TREI", False)
    ng_item = item(FALMOUTH, 4, cause={"EN-US": "Under Investigation", "orig": "Null"},
                   crew_status={"EN-US": "Arrived", "orig": "Arrived"})
    ng_item["desc"]["cust_a"] = {"val": 4, "mask": 5}
    ng = sources.outage_row("national_grid", "03023320", ng_item)
    assert (ng["cause"], ng["crew_status"], ng["cust_out_masked"]) == ("Under Investigation", "Arrived", True)
    assert sources.outage_row("eversource", "0", {"desc": {}, "geom": {}}) is None


def crawl(pages, roots=("0", "1"), **kw):
    return sources.crawl(lambda q: q, fake_fetch(pages), "test", roots, **kw)


def test_crawl_splits_only_clusters_and_counts_each_outage_once():
    pages = {"0": tile(item(BARNSTABLE, 10, cluster=True)),
             "00": tile(item(BARNSTABLE, 6, inc_id="A")),
             "01": tile(item(FALMOUTH, 4, inc_id="B")),
             "1": tile(item(BOURNE, 3, inc_id="C"))}
    tiles, outages, stats = crawl(pages, max_zoom=3)
    assert sorted((o["outage_id"], o["cust_out"]) for o in outages) == [("A", 6), ("B", 4), ("C", 3)]
    assert stats["tile_requests"] == 2 + 4  # roots, then the children of the one tile with a cluster
    assert set(tiles) == {"0", "00", "01", "1"} and stats["truncated"] is False


def test_crawl_keeps_the_deepest_copy_of_an_outage():
    pages = {"0": tile(item(BARNSTABLE, 5, inc_id="A"), item(FALMOUTH, 9, cluster=True)),
             "02": tile(item(BARNSTABLE, 5, inc_id="A"), item(FALMOUTH, 9, inc_id="B"))}
    _, outages, _ = crawl(pages, roots=("0",))
    assert sorted((o["outage_id"], o["zoom"]) for o in outages) == [("A", 2), ("B", 2)]


@pytest.mark.parametrize("pages, kw", [
    ({"0": tile(item(BARNSTABLE, 10, cluster=True))}, {"max_zoom": 1}),      # at max zoom
    ({"0": tile(item(BARNSTABLE, 10, cluster=True))}, {}),                   # no child tile came back
    ({"0": tile(item(BARNSTABLE, 10, cluster=True)),
      "00": tile(item(BARNSTABLE, 10, inc_id="A"))}, {"max_requests": 1}),  # request cap hit
])
def test_crawl_keeps_a_cluster_it_could_not_split(pages, kw):
    _, outages, stats = crawl(pages, roots=("0",), **kw)
    assert [(o["cluster"], o["cust_out"]) for o in outages] == [(True, 10)]
    assert stats["truncated"] is ("max_requests" in kw)


def test_crawl_counts_tile_errors_without_raising():
    pages = {"0": tile(item(BARNSTABLE, 2, inc_id="A"))}
    _, outages, stats = sources.crawl(lambda q: q, fake_fetch(pages, fail=("1",)), "test", ["0", "1"])
    assert len(outages) == 1 and stats["tile_errors"] == 1


# ---------------------------------------------------------------- Eversource


EV = sources.EVERSOURCE


def ev_report(region, towns):
    return json.dumps({"file_title": "r", "file_data": {"areas": [{"area_name": "EVERSOURCE", "cust_a": {"val": 0},
        "cust_s": 0, "areas": [{"area_name": "MA", "cust_a": {"val": 0}, "cust_s": 0, "areas": [
            {"area_name": region, "cust_a": {"val": 0}, "cust_s": 0, "areas": towns}]}]}]}}).encode()


def test_parse_eversource_report():
    body = ev_report("EMA", [{"area_name": "BARNSTABLE", "cust_a": {"val": 0}, "cust_s": 31220, "percent_out": 0.0},
                             {"area_name": "BOSTON", "cust_a": {"val": 3, "masked": True}, "cust_s": 343700,
                              "percent_out": 0.01}])
    rows = sources.parse_eversource_report(body)
    assert [(r["utility"], r["town"], r["cust_served"], r["cust_out"], r["cust_out_masked"]) for r in rows] == [
        ("Eversource EMA", "BARNSTABLE", 31220, 0, False), ("Eversource EMA", "BOSTON", 343700, 3, True)]


S3_403 = b'<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>'
WAF_403 = b"<HTML><HEAD><TITLE>ERROR: The request could not be satisfied</TITLE></HEAD><BODY>Request blocked.</BODY></HTML>"


def test_is_missing():
    assert sources.is_missing(404, b"", (404,))
    assert sources.is_missing(403, S3_403, (404, sources.S3_MISSING))
    assert not sources.is_missing(403, WAF_403, (404, sources.S3_MISSING))
    assert not sources.is_missing(403, S3_403, (404,))
    assert not sources.is_missing(200, S3_403, (404, sources.S3_MISSING))


def s3_fetch(pages, body_403=S3_403):
    """Like S3 behind the map: unknown keys answer 403 with `body_403`."""
    def fetch(url, missing=(404,)):
        if url in pages:
            return pages[url]
        if sources.is_missing(403, body_403, missing):
            return None
        raise FetchError(f"HTTP 403: {url}")
    return fetch


def eversource_pages(directory="2026_10_26_19_09_30", outage_tile=None, total_outages=1):
    base = f"{EV}/{directory}"
    cape = geo.quadkey(*geo.tile_xy(*BARNSTABLE, sources.ROOT_ZOOM), sources.ROOT_ZOOM)
    assert cape in geo.bbox_quadkeys(sources.EVERSOURCE_BBOX, sources.ROOT_ZOOM)
    return {
        f"{EV}/metadata.json": json.dumps({"directory": directory}).encode(),
        f"{base}/data.json": json.dumps({"summaryFileData": {
            "date_generated": "2026-10-26T15:07:10-0400", "total_outages": total_outages, "total_cust_a": {"val": 40},
            "page_mode": {"mode": "BLUESKY", "pausePublish": False}}}).encode(),
        f"{base}/report_east.json": ev_report("EMA", [{"area_name": "BARNSTABLE", "cust_a": {"val": 40}, "cust_s": 31220}]),
        f"{base}/report_west.json": ev_report("WMA", [{"area_name": "AGAWAM", "cust_a": {"val": 0}, "cust_s": 13124}]),
        f"{base}/outages/{cape}.json": outage_tile or tile(item(BARNSTABLE, 40, inc_id="W1-0", cause="TREE")),
    }


def test_collect_eversource_treats_s3_403_tiles_as_empty():
    res = SourceResult("eversource")
    sources.collect_eversource(s3_fetch(eversource_pages()), res)
    assert [(t["town"], t["cust_out"], t["source_updated"]) for t in res.towns] == [
        ("BARNSTABLE", 40, "2026-10-26T15:07:10-0400"), ("AGAWAM", 0, "2026-10-26T15:07:10-0400")]
    assert [(o["outage_id"], o["cust_out"]) for o in res.outages] == [("W1-0", 40)]
    assert res.meta["page_mode"] == "BLUESKY" and res.meta["tile_errors"] == 0
    assert (res.meta["outages_found"], res.meta["outages_reported"], res.meta["complete"]) == (1, 1, True)
    assert {"metadata.json", "data.json", "report_east.json", "report_west.json", "tiles.jsonl"} <= set(res.raw)


def test_collect_eversource_blocked_tiles_are_errors_and_incomplete():
    pages = eversource_pages()
    del pages[next(u for u in pages if "/outages/" in u)]  # the one tile with the outage is blocked too
    res = SourceResult("eversource")
    sources.collect_eversource(s3_fetch(pages, body_403=WAF_403), res)
    assert res.meta["tile_errors"] == len(geo.bbox_quadkeys(sources.EVERSOURCE_BBOX, sources.ROOT_ZOOM))
    assert (res.meta["outages_found"], res.meta["outages_reported"], res.meta["complete"]) == (0, 1, False)


def test_unsplit_cluster_counts_all_its_outages():
    cluster = item(BARNSTABLE, 30, cluster=True)
    cluster["desc"]["n_out"] = 3
    res = SourceResult("eversource")
    sources.collect_eversource(s3_fetch(eversource_pages(outage_tile=tile(cluster), total_outages=3)), res)
    assert [(o["cluster"], o["n_out"]) for o in res.outages] == [(True, 3)]
    assert res.meta["complete"] is True


def test_collect_eversource_missing_report_raises_but_keeps_raw():
    pages = eversource_pages()
    del pages[f"{EV}/2026_10_26_19_09_30/report_west.json"]
    res = SourceResult("eversource")
    with pytest.raises(FetchError):
        sources.collect_eversource(fake_fetch(pages), res)
    assert "report_east.json" in res.raw


# ---------------------------------------------------------------- National Grid


def test_kubra_layers():
    text = json.dumps({"reports": {"data": {"interval_generation_data": [
        {"source": "public/reports/b_report.json"}, {"source": "public/reports/a_report.json"}]}},
        "layers": ["public/summary-1/data.json", "public/cluster-1/{q}.json"]})
    assert sources.kubra_layers(text) == (["public/reports/a_report.json", "public/reports/b_report.json"],
                                          "public/summary-1/data.json", "public/cluster-1/{q}.json")
    with pytest.raises(ValueError):
        sources.kubra_layers("{}")


def ng_town(name, county, out, served):
    return {"key": "ctv", "name": name, "county": county, "cust_a": {"val": out}, "cust_s": served,
            "areaId": f"MA|{county}|MA|{name}|ctv", "n_out": 1 if out else 0}


def test_collect_national_grid_dedupes_towns_across_reports():
    inst, view = sources.NATIONAL_GRID_MA
    api = f"{sources.KUBRA}/stormcenter/api/v1/stormcenters/{inst}/views/{view}"
    data, cluster = "data/D1", "cluster-data/{qkh}/C1/D1"
    q = geo.quadkey(*geo.tile_xy(42.2626, -71.8023, sources.ROOT_ZOOM), sources.ROOT_ZOOM)  # Worcester
    town_report = {"file_data": {"areas": [ng_town("WORCESTER", "Worcester", 26, 82349), ng_town("LENOX", "Berkshire", 0, 3284)]}}
    county_report = {"file_data": {"areas": [{"key": "county", "name": "Worcester", "cust_a": {"val": 26},
                                              "cust_s": 312705, "areas": [ng_town("WORCESTER", "Worcester", 26, 82349)]}]}}
    pages = {
        f"{api}/currentState?preview=false": json.dumps({"stormcenterDeploymentId": "DEP", "data": {
            "interval_generation_data": data, "cluster_interval_generation_data": cluster}}).encode(),
        f"{api}/configuration/DEP?preview=false": json.dumps({"x": ["public/reports/t_report.json", "public/reports/c_report.json",
                                                                    "public/summary-1/data.json", "public/cluster-1/{q}.json"]}).encode(),
        f"{sources.KUBRA}/{data}/public/summary-1/data.json": json.dumps({"summaryFileData": {
            "totals": [{"summaryTotalId": "total-1", "total_cust_a": {"val": 26}, "total_outages": 1}],
            "date_generated": "2026-10-26T19:22:16Z", "page_mode": {"mode": "BLUESKY", "pausePublish": False}}}).encode(),
        f"{sources.KUBRA}/{data}/public/reports/t_report.json": json.dumps(town_report).encode(),
        f"{sources.KUBRA}/{data}/public/reports/c_report.json": json.dumps(county_report).encode(),
        f"{sources.KUBRA}/cluster-data/{q[-3:][::-1]}/C1/D1/public/cluster-1/{q}.json": tile(item((42.2626, -71.8023), 26)),
    }
    res = SourceResult("national_grid")
    sources.collect_national_grid(fake_fetch(pages), res)
    assert sorted((t["town"], t["county"], t["cust_out"]) for t in res.towns) == [
        ("LENOX", "Berkshire", 0), ("WORCESTER", "Worcester", 26)]
    assert [o["cust_out"] for o in res.outages] == [26]
    assert all(t["source_updated"] == "2026-10-26T19:22:16Z" for t in res.towns)
    assert (res.meta["outages_found"], res.meta["outages_reported"], res.meta["complete"]) == (1, 1, True)
    assert (res.meta["cust_out_found"], res.meta["cust_out_reported"]) == (26, 26)
