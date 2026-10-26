"""Map-tile and polyline helpers for the outage-map feeds.

Both utility maps (Kubra Storm Center) serve outages in Bing-style quadkey tiles, and store each
outage location as a Google encoded polyline.
"""
from __future__ import annotations

import math

MAX_LAT = 85.05112878  # Web Mercator limit

# Massachusetts, padded slightly (south, west, north, east). Tiles at the edges also cover parts of
# RI, CT, NY, NH and VT; outages there are kept here and dropped later by tract assignment.
MA_BBOX = (41.18, -73.51, 42.89, -69.85)


def tile_xy(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Tile column and row containing (lat, lon) at `zoom`."""
    lat = max(min(lat, MAX_LAT), -MAX_LAT)
    n = 1 << zoom
    x = int((lon + 180.0) / 360.0 * n)
    s = math.sin(math.radians(lat))
    y = int((0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def quadkey(x: int, y: int, zoom: int) -> str:
    digits = []
    for i in range(zoom, 0, -1):
        mask = 1 << (i - 1)
        digits.append(str((1 if x & mask else 0) + (2 if y & mask else 0)))
    return "".join(digits)


def quadkey_xy(q: str) -> tuple[int, int, int]:
    """Inverse of quadkey(): (x, y, zoom)."""
    x = y = 0
    zoom = len(q)
    for i, ch in enumerate(q):
        mask = 1 << (zoom - 1 - i)
        d = int(ch)
        if d & 1:
            x |= mask
        if d & 2:
            y |= mask
    return x, y, zoom


def children(q: str) -> list[str]:
    return [q + c for c in "0123"]


def bbox_quadkeys(bbox: tuple[float, float, float, float], zoom: int) -> list[str]:
    """Every quadkey at `zoom` that intersects bbox = (south, west, north, east)."""
    south, west, north, east = bbox
    x0, y0 = tile_xy(north, west, zoom)
    x1, y1 = tile_xy(south, east, zoom)
    return [quadkey(x, y, zoom) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def encode_polyline(points: list[tuple[float, float]], precision: int = 5) -> str:
    """Inverse of decode_polyline() (used to build test fixtures)."""
    factor = 10 ** precision
    out, prev = [], (0, 0)
    for lat, lon in points:
        cur = (round(lat * factor), round(lon * factor))
        for d in (cur[0] - prev[0], cur[1] - prev[1]):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev = cur
    return "".join(out)


def decode_polyline(s: str, precision: int = 5) -> list[tuple[float, float]]:
    """Google encoded polyline -> [(lat, lon), ...]."""
    factor = 10 ** precision
    out: list[tuple[float, float]] = []
    i = lat = lon = 0
    while i < len(s):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        out.append((lat / factor, lon / factor))
    return out
