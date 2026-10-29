# Synthetic commercial-zone overlay

The original GeoPulse use case calls for an overlay of mobility pings and commercial zoning
polygons. The repository now includes an **isolated demonstration** of that spatial operation.
`data/reference/synthetic_commercial_zones.csv` contains three fictional Bengaluru polygons. They
are not official land-use boundaries, a zoning classification, or evidence that a location is
permitted for a store. Every zone ID and its `source_label` identify it as synthetic.

The existing 500-metre store catchment job remains the source of store metrics. The zone overlay
does not change that job, Snowflake tables, dbt marts, Airflow, or the dashboard. A real zoning
feed needs an approved authoritative dataset, licensing, effective dates, category definitions,
geometry/CRS checks, versioning, and a separately tested publication path.

## Data contract

Zone CSV columns are `zone_id`, `zone_name`, `zoning_class`, `polygon_wkt`, and `source_label`.
The WKT polygon uses longitude then latitude (WGS84, SRID 4326). This demonstration accepts
only `source_label=synthetic`. Missing fields, non-synthetic labels, duplicate IDs, empty or
invalid polygons are rejected. Malformed WKT that Sedona cannot parse fails the job rather than
silently dropping a zone. GPS pings use the same validation and deduplication rules as the store
catchment job. `ST_Intersects` retains every point/zone match, including boundary intersections.

The output under the selected directory contains partitioned `matches/` Parquet, normalized
`zones/` Parquet, `rejected_pings/`, `rejected_zones/`, and an `audit/` JSON directory. Matches
contain the anonymized device ID, UTC event time, coordinates, zone fields, and
`source_label=synthetic`; they are restricted intermediate data, not a browser feed. The quality
gate requires the exact expected ping count, row reconciliation, zero rejected synthetic inputs,
at least one valid zone and match, and a plausible distinct-device count. A root
`_GEOPULSE_SUCCESS` marker is written only after every output succeeds. An interrupted overwrite
has no valid marker.

## Run a small synthetic batch

On Linux or WSL2, install Java 17 and the spatial Python extra. Use a dedicated output directory
for each run:

```bash
python -m pip install --editable '.[spatial]'
geopulse-generate --devices 100 --days 1 --interval-minutes 15 \
  --start-date 2026-09-22 --output data/output/zoning-demo-pings.csv.gz
geopulse-zone-overlay \
  --pings data/output/zoning-demo-pings.csv.gz \
  --zones data/reference/synthetic_commercial_zones.csv \
  --output data/output/zoning-demo \
  --expected-ping-rows 9600 \
  --shuffle-partitions 4
```

The CI suite uses a few known synthetic points to test an actual Sedona polygon intersection
and rejection of a non-synthetic source label. It does not prove production scale. Before a
warehouse or dashboard integration, build a separate zone-hour mart from validated zone matches,
count distinct devices per zone and local hour, and prevent device IDs or exact coordinates from
reaching the browser.
