"""Live outage collector: snapshots of MEMA, Eversource and National Grid, archived under data/live/.

  python -m collector.run              one snapshot, then exit (exit 1 unless every source is "ok")
  python -m collector.run --every 15   a snapshot every 15 minutes, on the quarter hour, until stopped

Each snapshot writes data/live/snapshots/<UTC time>/<source>/<file>.gz (the raw responses) and
manifest.json, then appends normalized rows to data/live/towns.csv and data/live/outages.csv.
A source's status is "ok", "incomplete" (fewer outages located in the map tiles than the utility
reports; its rows are still appended) or "error" (nothing appended). One source failing never stops
the others.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

import requests

from collector import sources
from collector.sources import OUTAGE_FIELDS, TOWN_FIELDS, Fetch, FetchError, SourceResult
from pipeline.common import ROOT

LIVE = ROOT / "data" / "live"
USER_AGENT = "lifeline-city-collector/0.1 (+https://github.com/MadhanJ05/lifeline-city)"
SOURCES: dict[str, Callable[[Fetch, SourceResult], None]] = {
    "mema": sources.collect_mema,
    "eversource": sources.collect_eversource,
    "national_grid": sources.collect_national_grid,
}


def make_fetch(timeout: float = 20, retries: int = 2) -> Fetch:
    """requests-based fetch: None for a response matching `missing`; retries network errors, 429 and 5xx."""
    local = threading.local()

    def fetch(url: str, missing: sources.Missing = (404,)) -> bytes | None:
        if not hasattr(local, "session"):
            local.session = requests.Session()
            local.session.headers["User-Agent"] = USER_AGENT
        err = ""
        for attempt in range(retries + 1):
            try:
                r = local.session.get(url, timeout=timeout)
            except requests.RequestException as e:
                err = type(e).__name__
            else:
                if sources.is_missing(r.status_code, r.content, missing):
                    return None
                if r.ok:
                    body = r.content
                    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
                err = f"HTTP {r.status_code}"
                if r.status_code < 500 and r.status_code != 429:
                    break
            if attempt < retries:
                time.sleep(2 ** attempt)
        raise FetchError(f"{err}: {url}")

    return fetch


def _append_csv(path: Path, fields: tuple[str, ...], rows: Iterable[dict]) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=("snapshot_utc",) + fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def snapshot(now: datetime, fetch: Fetch, live: Path = LIVE,
             collectors: dict[str, Callable[[Fetch, SourceResult], None]] = SOURCES) -> dict:
    """Collect every source once; archive raw files, append rows, return the manifest."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    snap = live / "snapshots" / stamp
    manifest: dict = {"snapshot_utc": stamp, "sources": {}}
    towns, outages = [], []
    for name, collect in collectors.items():
        res, t0 = SourceResult(name), time.monotonic()
        try:
            collect(fetch, res)
            status, error = ("incomplete" if res.meta.get("complete") is False else "ok"), None
        except Exception as e:  # one bad feed must not stop the others
            status, error = "error", f"{type(e).__name__}: {e}"
        for fname, body in res.raw.items():
            out = snap / name / f"{fname}.gz"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(gzip.compress(body))
        manifest["sources"][name] = {"status": status, "error": error,
                                     "seconds": round(time.monotonic() - t0, 1),
                                     "towns": len(res.towns), "outages": len(res.outages), **res.meta}
        if status != "error":
            towns += [{"snapshot_utc": stamp, **r} for r in res.towns]
            outages += [{"snapshot_utc": stamp, **r} for r in res.outages]
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _append_csv(live / "towns.csv", TOWN_FIELDS, towns)
    _append_csv(live / "outages.csv", OUTAGE_FIELDS, outages)
    return manifest


def summary_line(manifest: dict) -> str:
    parts = []
    for name, s in manifest["sources"].items():
        if s["status"] == "error":
            parts.append(f"{name} ERROR {s['error']}")
            continue
        text = f"{name} {s['towns']} towns"
        if "outages_found" in s:
            text += f", {s['outages_found']}/{s['outages_reported']} outages located, {s['tile_requests']} tile req"
            if s.get("tile_errors"):
                text += f", {s['tile_errors']} tile errors"
        if s["status"] == "incomplete":
            text += " INCOMPLETE"
        if s.get("page_mode") not in (None, "BLUESKY"):
            text += f" [{s['page_mode']}]"
        parts.append(text)
    return f"{manifest['snapshot_utc']}  " + " | ".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--every", type=int, metavar="MINUTES", help="repeat on this interval until stopped")
    ap.add_argument("--live-dir", type=Path, default=LIVE)
    args = ap.parse_args(argv)
    fetch = make_fetch()
    while True:
        manifest = snapshot(datetime.now(UTC).replace(microsecond=0), fetch, args.live_dir)
        print(summary_line(manifest), flush=True)
        if not args.every:
            return 0 if all(s["status"] == "ok" for s in manifest["sources"].values()) else 1
        period = args.every * 60
        time.sleep(period - time.time() % period)


if __name__ == "__main__":
    raise SystemExit(main())
