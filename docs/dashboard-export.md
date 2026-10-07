# Publish a dashboard snapshot

GeoPulse keeps Snowflake credentials on the worker. The dashboard reads a JSON snapshot, not
the warehouse: after dbt builds its marts, `geopulse-export-dashboard` selects the requested
retail-local date from the aggregate cannibalization and hourly-footfall marts, then combines
those results with the approved store reference CSV. No device identifier or raw GPS point is
queried for this export.

## Run one logical day

Install `.[warehouse]` in the export worker, provision a Snowflake role with `SELECT` on the
mart, and provide the `DBT_SNOWFLAKE_ACCOUNT`, `DBT_SNOWFLAKE_USER`,
`DBT_SNOWFLAKE_WAREHOUSE`, `DBT_SNOWFLAKE_DATABASE`, and `DBT_SNOWFLAKE_ROLE` worker settings.
Use either `DBT_SNOWFLAKE_PASSWORD` or the private-key file settings documented in
`docs/warehouse-loading.md`. Do not place credentials in the command, JSON file, or frontend.
Set `GEOPULSE_DASHBOARD_SNOWFLAKE_ROLE` to a dedicated read-only role if you want the export
session to use a narrower role than the dbt transformation role. That role needs warehouse,
database, and mart-schema usage plus `SELECT` on both the cannibalization and hourly-footfall
marts.
The repository's default dbt target is password-based; a key-only scheduled deployment also
needs a key-pair dbt target/profile configured before the `build_dbt_analytics` task can run.

```bash
geopulse-export-dashboard \
  --run-date 2026-09-30 \
  --stores data/reference/stores.csv \
  --output data/output/dashboard/geopulse-dashboard.json \
  --synthetic
```

`--synthetic` labels an export based on generated mobility data and is currently required.
The exporter rejects a run without it before connecting to Snowflake. This is a synthetic-only
project feature, not approval to publish real store-hour cohorts or daypart overlaps. Real
mobility publication needs a reviewed small-cell suppression, retention, and access policy
first; do not mark real data as synthetic. The flag is an operator assertion, not independent
proof of data provenance. The date is supplied as a bound query value,
not interpolated into SQL. The exporter reads the `FCT_STORE_CANNIBALIZATION` and
`FCT_STORE_HOURLY_FOOTFALL` marts in
`GEOPULSE.ANALYTICS_MARTS` by default. The `ANALYTICS_MARTS` suffix comes from dbt's target
schema `ANALYTICS` plus the project's `+schema: marts` setting, following [dbt's default
custom-schema naming](https://docs.getdbt.com/docs/build/custom-schemas). If your target
schema differs, set the same `DBT_SNOWFLAKE_SCHEMA` value for dbt and the export worker.

The output follows the existing `dashboard/src/data/types.ts` contract: UTC refresh time,
retail timezone, approved store coordinates, daily store-pair/daypart overlap metrics, and
the ordered candidate-to-existing observation count, plus reported per-store/per-hour footfall.
The ordered count must be a non-negative, JavaScript-safe integer no larger than shared visitors;
it is a daypart diagnostic, not an observed route or causal diversion rate. Hourly
`uniqueVisitors` counts distinct devices within that store-hour only: adding them across hours
would double-count repeat visitors. An absent
store-hour remains unreported, not an inferred zero. A date with no comparison rows, missing
hourly coverage for a compared store, an unknown store, duplicate store-hour, inconsistent
visitor math, invalid rates, unsafe-large counts, or conflicting timezones fails instead of
producing a misleading dashboard. This project's retail timezone is fixed to `Asia/Kolkata`; a conflicting
`GEOPULSE_RETAIL_TIMEZONE` setting fails closed. `refreshedAt` records export time in UTC, not
the time of the original GPS observations. The file
is written to a temporary sibling and atomically replaced only after a complete validated
snapshot is ready. A failed retry leaves the last complete snapshot untouched.

The configured output is a shared **latest-data-date** snapshot. Publication compares the
retail-local `trafficDateLocal` of its flows with the date in the existing output under a
publication lock; it does not compare `refreshedAt`, which becomes newer even when an old day is
re-exported. A first export, a retry for the same day, or a newer day may replace the file. An
older logical day, a mixed-date snapshot, or an existing file whose date cannot be established
fails without replacing the file. To inspect or retain a historical day, export it to a separate
date-specific `--output` path instead of the shared latest path. Review it before any explicit
promotion. The guard preserves ordering by observation date; it does not prove source-data
completeness or compare revisions within the same day. A small sibling `.lock` file is retained
to coordinate publishers; do not remove it while exports may be running.

## Scheduled delivery and hosting

The Airflow DAG runs `export_dashboard_snapshot` after the successful dbt build for the same
logical day. Its default output is
`<GEOPULSE_DATA_ROOT>/output/dashboard/geopulse-dashboard.json`; set
`GEOPULSE_DASHBOARD_SNAPSHOT_PATH` to a different shared file path if needed. This output is
ignored by Git and is not copied into the committed dashboard fixture automatically. The DAG
preflight checks that the configured output path has a writable existing parent (or ancestor)
before starting the expensive generator and spatial join.
Re-running an old Airflow logical day may rebuild that day's marts, but its export task will fail
if the shared snapshot already shows a newer day; the newer dashboard file remains untouched.
Use a separate date-specific output for historical exports rather than rolling back the shared
dashboard feed.

Serve or upload the synthetic JSON through a read-only static endpoint and set
`VITE_GEOPULSE_DATA_URL` to its URL before building the dashboard. The browser must have no
Snowflake credential, raw ping access, or write permission. The exporter currently fails closed
for real mobility data because an aggregate count alone does not establish anonymity,
especially for small store-hour cohorts.

Unit tests use a simulated connector and exercise validation and atomic publication. They do
not prove connectivity or privileges in a live Snowflake account. Before scheduling a real
deployment, build the marts in a development account, export one known synthetic date twice,
and verify the JSON with the dashboard plus the SQL row counts.
