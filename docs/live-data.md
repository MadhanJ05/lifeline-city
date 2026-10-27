# Live outage data

The storm replay reconstructs outages from reports filed after the fact. In a live storm, Lifeline needs
the outage numbers as they happen, and down to the neighborhood. `collector/` records them: every 15
minutes it saves a snapshot of three public feeds under `data/live/` (gitignored).

```sh
.venv/bin/python -m collector.run              # one snapshot (exit 1 if any source failed)
.venv/bin/python -m collector.run --every 15   # a snapshot every 15 minutes, on the quarter hour
```

## Sources (checked 2026-10-26)

| Source | Geography | Updates | Endpoint the public map uses |
|---|---|---|---|
| MEMA statewide outage map | Town × utility (Eversource, National Grid, Unitil) | ~15 min | `http://mema.mapsonline.net/power_outage_public.csv` (HTTP only) |
| Eversource outage map (Kubra Storm Center, iFactor version) | Town, plus one point per outage | 15–30 min | `outagemap.eversource.com/resources/data/external/interval_generation_data/` |
| National Grid MA outage map (Kubra Storm Center) | Town and county, plus one point per outage | ~15 min | `kubra.io/stormcenter/api/v1/stormcenters/<instance>/views/<view>/currentState` |

None of these endpoints is documented or covered by published terms. They are the files each public map loads, and they can change without notice. Each snapshot archives the raw responses, so the parsing can be redone later. For a deployment run by an agency, a data-sharing agreement with MEMA, which already receives these numbers from the utilities, is the better route.

### MEMA

- Columns: `Town, County, MEMA Region, Utility, Total Customers, Without Power, Percent Without Power, Notes, Last Updated`.
- Only towns that currently have outages are listed. On a quiet day that is a handful of rows.
- Not covered: the roughly 40 municipal light plants (e.g., Concord, Braintree). None of them serve the Cape.

### Eversource

1. `metadata.json` names the current interval folder, e.g. `{"directory": "2026_10_26_19_09_30"}`.
2. That folder holds:
   - `data.json`: the summary, with `date_generated` and `page_mode`.
   - `report_east.json` and `report_west.json`: Eastern and Western MA, nested as EVERSOURCE > MA > EMA|WMA > town.
   - `outages/<quadkey>.json`: outage map tiles.
3. Each town row has `cust_a.val` (customers out), `cust_s` (customers served) and `percent_out`. `percent_out` is in percent and never drops below 0.01, so the fraction is computed from the counts.
4. Small counts are rounded for privacy and flagged `"masked": true`. An outage of 1 to 4 customers shows as 4.
5. Empty tiles return **403**, not 404. The file host is S3, which answers 403 for missing objects. A 403 counts as an empty tile only when two things hold: it is a tile request, and the body is S3's `<Code>AccessDenied</Code>` XML. A 403 with any other body, such as a firewall or rate-limit page, is a tile error. A 403 on any other file is a source error.

### National Grid

1. `currentState` gives the current data folders and the `stormcenterDeploymentId`.
2. `configuration/<deploymentId>` names the files:
   - two reports: town (`key: "ctv"`) and county, where the county report nests the same towns
   - `public/summary-1/data.json`
   - the cluster tiles: `cluster-data/{qkh}/…/public/cluster-1/{q}.json`, where `{qkh}` is the last three quadkey digits, reversed
3. Outages carry crew status and cause. Small counts carry `"mask": 5`.

## How the collector finds every outage

Both maps serve outages in quadkey map tiles. A tile lists single outages (`cluster: false`) and clusters of nearby outages. The collector:

1. **Starts from the zoom-7 tiles over the area the utility's summary counts.** For National Grid that is Massachusetts (3 tiles). For Eversource it is CT, MA and NH (12 tiles), because its summary counts all three states.
2. **Fetches the 4 child tiles of any tile that still contains a cluster.** It repeats this down to zoom 16; on a quiet day nothing needs splitting past zoom 10.
3. **Keeps each outage once,** from the deepest tile it appears in. It keys on the incident ID, or on location plus start time when the ID is blank.
4. **Keeps a cluster only when it could not be split.** That covers three cases: maximum zoom, the request cap (4,000 tiles per source per snapshot), or no child tile came back. This way customers are neither counted twice nor dropped.

### Completeness check

A tile that silently fails would look like "no outages here." So every snapshot compares two numbers from the same interval:
- the outages it located in the tiles, counting each unsplit cluster as its `n_out`
- the utility's own total in its summary file

**Outage counts are compared because they are exact on both sides.** Customer counts are recorded but not compared, because the tiles round small outages up. The manifest records `outages_found`, `outages_reported`, `cust_out_found`, `cust_out_reported` and `complete`.

**If fewer outages are found than reported, the source's status is `incomplete`.** Its rows are still saved, the summary line says INCOMPLETE, and a one-shot run exits 1.

First live check (2026-10-26 20:15 UTC):
- **Eversource:** 24 of 24 located, 138 customers from points vs 81 reported.
- **National Grid:** 7 of 7 located, 86 customers from points vs 68 reported.

## Output

```
data/live/
  snapshots/<UTC time>/manifest.json        status, timings, tile counts, page_mode per source
  snapshots/<UTC time>/<source>/<file>.gz   raw responses (tiles packed into tiles.jsonl.gz)
  towns.csv     snapshot_utc, source, utility, town, county, cust_served, cust_out, cust_out_masked, source_updated
  outages.csv   snapshot_utc, source, outage_id, lat, lon, cust_out, cust_out_masked, n_out, cluster, zoom,
                start, etr, cause, crew_status
```

A quiet-day snapshot is about 112 KB, or about 10 MB a day.

## Checked against the town totals (2026-10-26)

The outage points were placed in Massachusetts towns (TIGER county subdivisions) and summed:
- **Larger outages matched exactly:** Springfield 39 = 39 (Eversource), Bellingham 62 = 62 (National Grid).
- **Masked outages read high:** every point under 5 customers reads as 4, so towns with only small outages sum higher. Boston, for example, showed 2 in the report and 8 from points.

So the points are where the outages are, and the town report is the count. The next step reconciles the two.

## Open questions only a storm can answer

- **Storm mode.** Both feeds have `page_mode` (now `BLUESKY`) and `pausePublish`. Whether a utility pauses or simplifies its map during a major event is unknown. The manifest records both flags every snapshot, and the summary line prints the mode when it isn't `BLUESKY`.
- **What a point marks.** One point can stand for thousands of customers on a circuit. Whether it sits at the fault, at the device that opened, or at the middle of the affected area changes how far its customers should be spread.

## Locate: from points to neighborhoods (`pipeline/locate.py`)

```sh
.venv/bin/python -m pipeline.locate                              # the latest snapshot
.venv/bin/python -m pipeline.locate --snapshot 20261026T201554Z
```

Step by step, for the Cape (Barnstable County):

1. **Place.** Each outage point goes to the Cape town it falls in. A point outside every town but within 2 km of one (on a pier or in a harbor) goes to the nearest town; anything farther drops.
2. **Spread.** An outage's customers fill the nearest homes in its town, block by block, never past a block's homes. Larger outages are placed first.
3. **Reconcile.** The utility's town report is the count:
   - Each town's spread is scaled to its reported total and clipped to each block's homes, with any excess moved to the town's remaining homes. This also corrects the privacy-rounded counts.
   - A town with a total but no points is spread over all its homes and labeled "Estimated from the town total."
   - A town reporting 0 is set to 0.
4. **Year-round homes.** Customers out become year-round homes out, using each block's year-round share. This way, summer homes standing empty in a winter storm aren't counted as people in the dark. The share comes from:
   - **2020 Census P.L. 94-171, table H1, by block:** H1_001N housing units and H1_002N occupied homes. "Occupied" means someone's usual residence on Census Day, so summer homes count as vacant.
   - **ACS households (B11001_001E) per tract,** which brings the 2020 occupied count up to date.

The Cape has 164,885 homes. 103,368 were occupied year-round in 2020, or 104,301 after scaling to the ACS.

**Block locations** are TIGERweb 2020 block internal points (`tigerWMS_Census2020` layer 10), downloaded once and cached under `data/raw/cache/`.

**Output** goes to `data/live/located/<snapshot>.csv`, one row per tract:
- `homes`, `year_round_homes`, `customers_out`, `year_round_out`, `pct_year_round_out`
- `label`: "Estimated from outage locations," "Estimated from the town total," or "No outages reported"

`<snapshot>.json` records, per town, the reported total, the total from points, the estimate and the method used.

**What-if on the real Cape geography** (2026-10-26): with 1,000 customers out and a town total of 1,000,
- **Truro:** 375 year-round homes, all in tract 208 (37% of its year-round homes).
- **Hyannis:** 893 year-round homes, mostly tract 153 (36%).

**Limits:**
- **Homes stand in for customers.** Utility customers also include businesses, so in commercial areas an outage is spread over a slightly wider area than it really covers.
- **A point's meaning is unknown.** Whether a point marks the fault, the device that opened, or the middle of the affected area, it is treated as the center.
- **Year-round shares are from 2020,** scaled per tract, not per block, to current households.
