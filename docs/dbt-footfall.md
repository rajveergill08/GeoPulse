# dbt hourly footfall models

The Week 2 dbt layer turns Apache Sedona point-to-catchment matches into reliable hourly retail
traffic metrics. It is designed for Snowflake and is executed against DuckDB fixtures in CI so
model logic can be validated without warehouse credentials or compute.

## Lineage and grain

```text
GEOPULSE.SPATIAL.PING_STORE_MATCHES
  -> stg_ping_store_matches
  -> int_store_hourly_traffic
  -> fct_store_hourly_footfall
```

The final model has exactly one row per `(store_id, traffic_hour_local)`. A device with several GPS
pings inside one catchment during the same hour contributes one unique visitor but multiple pings.
A ping in overlapping catchments contributes independently to each store; this preserves the
evidence required for the Week 3 cannibalization model.

`unique_visitors` is distinct within one store-hour, not across the whole day. Summing its 24
hourly values would count a device again if it returns in another hour. The dashboard's hour
scrubber therefore presents one hourly observation at a time and does not call that sum daily
unique reach. A missing store-hour is absent source coverage, not a proved zero.

Raw observations remain canonical UTC timestamps. Before hourly bucketing and daypart assignment,
dbt converts them to `geopulse_retail_timezone`, which defaults to `Asia/Kolkata`. This prevents a
07:30 Bengaluru commute from being classified as an overnight UTC observation and correctly
handles local dates that cross a UTC midnight boundary.

The downstream store-pair logic and its decision guardrails are documented in
`docs/cannibalization.md`.

## Citywide H3 hourly feed (Week 4 groundwork)

The H3 mart is a separate path from store catchment footfall:

```text
GEOPULSE.RAW.MOBILE_PINGS (GEOGRAPHY location)
  -> stg_h3_ping_cells (resolution-8 hexadecimal H3 ID)
  -> fct_h3_hourly_footfall
```

This model starts with the canonical raw pings, **not** Sedona's many-to-many store matches;
otherwise a ping falling in two catchments would be counted twice in a citywide hexagon.
Snowflake converts each raw `location` using `H3_POINT_TO_CELL_STRING(location, 8)` and retains
the result as text to avoid losing H3 integer precision in JavaScript. The raw `TIMESTAMP_TZ`
is converted to UTC before the existing retail-local hour conversion. Each mart row is one
`(hex_id, traffic_hour_local)` with `unique_visitors = count(distinct device_id)` and
`ping_count = count(*)`. Neither device IDs nor exact coordinates appear in the mart. As with
store-hour counts, a missing H3-hour is unreported rather than an inferred zero, and summing
hourly unique visitors would double-count returning devices.

The DuckDB CI seed contains real resolution-8 H3 indexes precomputed from synthetic Bengaluru
coordinates. It tests repeated-device counting, separate cells, and the UTC-to-Kolkata date
boundary. It does **not** exercise Snowflake's geography-to-H3 function; Snowflake parsing only
checks the project manifest, not the execution of the SQL. A live development-account build
and cell-level spot check are still needed. The dbt transformer role additionally requires
`USAGE` on the raw schema and `SELECT` on `RAW.MOBILE_PINGS`. If the raw schema is not `RAW`, set
`DBT_SNOWFLAKE_RAW_SCHEMA`.

This mart is internal groundwork for a future 3D Kepler H3 layer; it is **not** part of the
current dashboard JSON export. The existing browser map still displays store-level aggregate
markers, not actual street-level footfall hexagons. Real-mobility H3 publication remains blocked
until a reviewed small-cell suppression, retention, and access policy is in place. The H3
fixture is synthetic and must not be loaded into a production schema.

The native function and expected string format follow [Snowflake's H3 point-to-cell
reference](https://docs.snowflake.com/en/sql-reference/functions/h3_point_to_cell_string).
The chosen `hex_id` contract follows [Kepler.gl's H3 layer
format](https://docs.kepler.gl/docs/user-guides/c-types-of-layers/j-h3).

## Metrics

| Field | Definition |
| --- | --- |
| `traffic_hour_local` | Start of the retail-local hour used for aggregation. |
| `traffic_date_local` | Retail-local calendar date derived from the observation. |
| `retail_timezone` | IANA timezone used for local bucketing and dayparts. |
| `unique_visitors` | Distinct anonymized `device_id` values per store and retail-local hour. |
| `ping_count` | Valid point-to-catchment rows per store and retail-local hour. |
| `avg_accuracy_m` | Mean reported GPS accuracy for matched pings. |
| `avg_distance_to_store_m` | Mean great-circle distance between matched pings and the store. |
| `daypart` | Morning commute (05-09), midday (10-15), evening commute (16-19), or off-peak, in retail-local time. |

`first_ping_at_utc` and `last_ping_at_utc` preserve canonical event-time evidence. Their local
counterparts support dashboard labels and audits without changing the source timestamps.

The current local-hour key is intended for retail timezones without daylight-saving transitions,
including the default `Asia/Kolkata`. A DST-observing city requires an offset-aware hour key before
changing this variable, otherwise the repeated fall-back hour could be merged.

## Local validation

Requirements: Python 3.11 or newer.

```powershell
python -m pip install --editable ".[analytics]"

dbt seed --profiles-dir profiles/ci --target ci --full-refresh
dbt build --profiles-dir profiles/ci --target ci --exclude-resource-type seed
dbt parse --profiles-dir profiles/snowflake --target snowflake --no-partial-parse
```

The CI seeds are synthetic. The catchment fixture includes repeated pings, overlapping
catchments, an alternative Store C neighborhood, and morning/evening hours. The separate H3
fixture contains pre-indexed raw pings. They must never be loaded into a production schema. CI
also checks that each reported local hour matches the model's local timestamp, date, and
timezone.

## Snowflake execution

1. Run `sql/snowflake/02_spatial_matches.sql` after uploading Sedona match Parquet files to the
   internal stage.
2. Export the environment variables referenced by `profiles/snowflake/profiles.yml`; credentials
   stay outside Git.
3. Validate connectivity with `dbt debug --profiles-dir profiles/snowflake`.
4. Run `dbt build --profiles-dir profiles/snowflake --target snowflake`.

The default sources are `GEOPULSE.SPATIAL.PING_STORE_MATCHES` and
`GEOPULSE.RAW.MOBILE_PINGS`. Override `DBT_SNOWFLAKE_SOURCE_SCHEMA` or
`DBT_SNOWFLAKE_RAW_SCHEMA` when a different landing schema is required.
