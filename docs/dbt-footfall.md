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

The final model has exactly one row per `(store_id, traffic_hour_utc)`. A device with several GPS
pings inside one catchment during the same hour contributes one unique visitor but multiple pings.
A ping in overlapping catchments contributes independently to each store; this preserves the
evidence required for the Week 3 cannibalization model.

The downstream store-pair logic and its decision guardrails are documented in
`docs/cannibalization.md`.

## Metrics

| Field | Definition |
| --- | --- |
| `unique_visitors` | Distinct anonymized `device_id` values per store and UTC hour. |
| `ping_count` | Valid point-to-catchment rows per store and UTC hour. |
| `avg_accuracy_m` | Mean reported GPS accuracy for matched pings. |
| `avg_distance_to_store_m` | Mean great-circle distance between matched pings and the store. |
| `daypart` | Morning commute (05-09), midday (10-15), evening commute (16-19), or off-peak, in UTC. |

UTC is intentional at this layer. A later presentation model can convert timestamps to a selected
store timezone without changing the canonical aggregation grain.

## Local validation

Requirements: Python 3.11 or newer.

```powershell
python -m pip install --editable ".[analytics]"

dbt seed --profiles-dir profiles/ci --target ci --full-refresh
dbt build --profiles-dir profiles/ci --target ci --exclude-resource-type seed
dbt parse --profiles-dir profiles/snowflake --target snowflake --no-partial-parse
```

The CI seed is synthetic and includes repeated pings, overlapping catchments, and morning/evening
hours. It must never be loaded into a production schema.

## Snowflake execution

1. Run `sql/snowflake/02_spatial_matches.sql` after uploading Sedona match Parquet files to the
   internal stage.
2. Export the environment variables referenced by `profiles/snowflake/profiles.yml`; credentials
   stay outside Git.
3. Validate connectivity with `dbt debug --profiles-dir profiles/snowflake`.
4. Run `dbt build --profiles-dir profiles/snowflake --target snowflake`.

The default source is `GEOPULSE.SPATIAL.PING_STORE_MATCHES`. Override
`DBT_SNOWFLAKE_SOURCE_SCHEMA` when a different landing schema is required.
