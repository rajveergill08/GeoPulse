# Spatial catchment join

The Week 2 spatial job converts validated WGS84 store coordinates into configurable catchment
polygons and matches mobility pings that intersect each polygon. The default reference data uses
a 500-metre radius for every location.

## Processing contract

1. Read ping and store CSV files with explicit schemas; never infer numeric production fields.
2. Reject missing identifiers, malformed timestamps, invalid coordinates, negative accuracy, and
   catchment radii outside 1-10,000 metres.
3. Retain one deterministic record for each ping `(device_id, event_ts)` key and each `store_id`;
   route duplicates to rejected outputs with a reason.
4. Create longitude/latitude points with SRID 4326.
5. Call `ST_Buffer(store_geom, catchment_radius_m, true)`. The `true` flag enables spheroidal
   buffering, so the radius is measured in metres rather than decimal degrees.
6. Broadcast the small store-catchment table and apply `ST_Intersects` against distributed pings.
7. Calculate great-circle distance from each matched ping to its store with
   `ST_DistanceSphere`, also in metres.

All timestamps are normalized to UTC by the Spark session. The match output is partitioned by
`event_date` and `event_hour_utc`, ready for the next dbt hourly-footfall model.

## Outputs

| Directory | Format | Purpose |
| --- | --- | --- |
| `matches/` | Partitioned Parquet | One row per ping/store catchment match. |
| `catchments/` | Parquet | Store definitions plus portable catchment WKT. |
| `rejected_pings/` | Parquet | Invalid or duplicate pings with a rejection reason. |
| `rejected_stores/` | Parquet | Invalid or duplicate stores with a rejection reason. |
| `audit/` | JSON | Raw, valid, rejected, match, and unique-device counts. |

One ping may match multiple overlapping catchments. That behavior is intentional: it preserves
the overlap needed to calculate Store A/Store B cannibalization in Week 3.

## Run locally

Java 17 and Python 3.11 or newer are required.

```powershell
python -m pip install --editable ".[spatial]"

geopulse-spatial-join `
  --pings data/generated/mobile_pings.csv.gz `
  --stores data/reference/stores.csv `
  --output data/output/spatial `
  --shuffle-partitions 8
```

The pinned Python and Maven versions are intentionally aligned. The GeoTools wrapper is included
because Sedona's spheroidal buffer resolves an appropriate projected coordinate system before
buffering. For a managed Spark cluster, override `--master` and, only when the cluster supplies
compatible Sedona and GeoTools JARs, override `--maven-packages`.

## Scale considerations

- The join broadcasts only the store table, not the ping data. This is appropriate for thousands
  of catchments and millions of pings.
- Only validated pings, stores, and match results are cached; raw and rejected inputs are not kept
  as extra in-memory copies.
- Adaptive query execution is enabled and shuffle partitions are configurable per environment.
- Input validation occurs before geometry construction, avoiding failures caused by corrupt
  coordinates.
- Date/hour partitioning allows downstream models to process only new mobility windows.
