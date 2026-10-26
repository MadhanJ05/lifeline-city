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
5. Empty tiles return **403**, not 404. The file host is S3, which answers 403 for missing objects. Only tile requests treat 403 as empty; a 403 on any other file is an error.

### National Grid

1. `currentState` gives the current data folders and the `stormcenterDeploymentId`.
2. `configuration/<deploymentId>` names the files:
   - two reports: town (`key: "ctv"`) and county, where the county report nests the same towns
   - `public/summary-1/data.json`
   - the cluster tiles: `cluster-data/{qkh}/…/public/cluster-1/{q}.json`, where `{qkh}` is the last three quadkey digits, reversed
3. Outages carry crew status and cause. Small counts carry `"mask": 5`.

## How the collector finds every outage

Both maps serve outages in quadkey map tiles. A tile lists single outages (`cluster: false`) and clusters of nearby outages. The collector:

1. **Starts from the 3 tiles at zoom 7** that cover Massachusetts.
2. **Fetches the 4 child tiles of any tile that still contains a cluster.** It repeats this down to zoom 16; on a quiet day nothing needs splitting past zoom 10.
3. **Keeps each outage once,** from the deepest tile it appears in. It keys on the incident ID, or on location plus start time when the ID is blank.
4. **Keeps a cluster only when it could not be split.** That covers three cases: maximum zoom, the request cap (4,000 tiles per source per snapshot), or no child tile came back. This way customers are neither counted twice nor dropped.

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

## Next: from points to neighborhoods

1. **Place each outage in a census tract.**
2. **Spread its customers over nearby homes,** using Census block housing counts.
3. **Scale the tract numbers to the town totals.** This also corrects the masked counts.
4. **Estimate customers per tract** from ACS housing units, scaled to each town's `cust_served`.
5. **Label the result on screen** "Estimated from outage locations."
