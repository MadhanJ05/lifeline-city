"""Tests for collector/geo.py: quadkeys round-trip and polylines match Google's reference example."""
from hypothesis import given
from hypothesis import strategies as st

from collector import geo


def test_decode_polyline_reference_example():
    # The worked example in Google's encoded polyline algorithm documentation.
    assert geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [
        (38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_encode_polyline_reference_example():
    assert geo.encode_polyline([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"


coords = st.tuples(st.floats(-85, 85), st.floats(-180, 180)).map(lambda p: (round(p[0], 5), round(p[1], 5)))


@given(st.lists(coords, min_size=1, max_size=20))
def test_polyline_round_trip(points):
    decoded = geo.decode_polyline(geo.encode_polyline(points))
    assert len(decoded) == len(points)
    assert all(abs(a - c) < 1e-9 and abs(b - d) < 1e-9 for (a, b), (c, d) in zip(decoded, points, strict=True))


tiles = st.integers(1, 20).flatmap(
    lambda z: st.tuples(st.just(z), st.integers(0, 2 ** z - 1), st.integers(0, 2 ** z - 1)))


@given(tiles)
def test_quadkey_round_trip(zxy):
    z, x, y = zxy
    q = geo.quadkey(x, y, z)
    assert len(q) == z and set(q) <= set("0123")
    assert geo.quadkey_xy(q) == (x, y, z)


@given(st.floats(-85, 85), st.floats(-180, 179.999), st.integers(1, 18))
def test_child_tile_of_a_point_extends_its_parent(lat, lon, z):
    parent = geo.quadkey(*geo.tile_xy(lat, lon, z), z)
    child = geo.quadkey(*geo.tile_xy(lat, lon, z + 1), z + 1)
    assert child in geo.children(parent)


def test_massachusetts_roots():
    roots = geo.bbox_quadkeys(geo.MA_BBOX, 7)
    assert len(roots) == 3
    corners = {"Barnstable": (41.65, -70.30), "Boston": (42.36, -71.06), "Pittsfield": (42.45, -73.25),
               "Provincetown": (42.05, -70.19), "Nantucket": (41.28, -70.10), "Williamstown": (42.71, -73.20)}
    for lat, lon in corners.values():
        assert geo.quadkey(*geo.tile_xy(lat, lon, 7), 7) in roots
