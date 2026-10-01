# Daily raw GPS ingestion into Snowflake

`geopulse-load-raw` takes one generated CSV or CSV.GZ file and publishes its valid, typed GPS
observations to `GEOPULSE.RAW.MOBILE_PINGS`. Each row receives a native Snowflake `GEOGRAPHY`
point, constructed as `ST_MAKEPOINT(longitude, latitude)`. The current daily pipeline generates
synthetic observations only; this command is not an approval to ingest real device movements.

## Provision and configure

Run `sql/snowflake/04_raw_batch_setup.sql` once with a provisioning role. It creates the raw
schema and target table if absent, without deleting existing data. The older
`01_raw_mobility.sql` includes shared-stage `TRUNCATE` and a manual full-refresh recipe; do not
run that file as a scheduled daily loader.

Install `.[warehouse]` in the worker running this command. It uses the same
`DBT_SNOWFLAKE_ACCOUNT`, `DBT_SNOWFLAKE_USER`, `DBT_SNOWFLAKE_WAREHOUSE`,
`DBT_SNOWFLAKE_DATABASE`, and `DBT_SNOWFLAKE_ROLE` environment settings as the spatial
publisher. Supply either a protected `DBT_SNOWFLAKE_PASSWORD` or the private-key settings in
`docs/warehouse-loading.md`. The runtime role needs warehouse/database/RAW-schema usage,
`SELECT`/`INSERT`/`DELETE` on `MOBILE_PINGS`. Snowflake does not require schema `CREATE STAGE`
or `CREATE TABLE` for the session-temporary landing objects (see
[stage](https://docs.snowflake.com/en/sql-reference/sql/create-stage) and
[table](https://docs.snowflake.com/en/sql-reference/sql/create-table) privileges). The raw loader
always targets RAW; it does not change the spatial dbt source schema.

## Validate before connecting

```bash
geopulse-load-raw \
  --run-date 2026-10-01 \
  --pings data/generated/20261001/mobile_pings.csv.gz \
  --expected-ping-rows 9600000 \
  --expected-devices 100000 \
  --dry-run
```

The preview streams and validates the six-column input, including its gzip integrity, exact
row/device counts, explicit timestamp offsets, local-day bounds, finite WGS84 coordinates,
positive accuracy, and nonblank identifiers. It does not read credentials or open a Snowflake
session. Remove `--dry-run` to publish after provisioning. One Asia/Kolkata calendar day spans
two UTC dates: October 1 corresponds to
`[2026-09-30T18:30:00Z, 2026-10-01T18:30:00Z)`.

## Publication and retry behavior

Each attempt uses a new session-temporary stage and a six-text-column landing table. The
publisher confirms upload and direct CSV COPY results, then validates typed conversions,
counts, date bounds, and duplicate `(device_id, event_ts)` keys in Snowflake. Direct COPY keeps
CSV column-count enforcement active; Snowflake ignores that option when COPY uses a SELECT
transformation. Only after these checks does a transaction delete the target's one UTC-bounded
retail day, insert typed rows, verify the count and non-null points, and commit. It rolls back
on a failure. Snowflake's [transaction rules](https://docs.snowflake.com/en/sql-reference/transactions),
[CSV transformation limitation](https://docs.snowflake.com/en/user-guide/data-load-transform),
and [`ST_MAKEPOINT` argument order](https://docs.snowflake.com/en/sql-reference/functions/st_makepoint)
are relevant to this design.

The Airflow DAG publishes the raw batch immediately after generation and before Sedona. A later
spatial or dbt failure may therefore leave the raw day published while the analytics run is
incomplete. Retrying the same logical day replaces its raw rows and leaves neighboring days
untouched; the raw and spatial target replacements are separate transactions, not one
cross-table transaction. Do not run independent publishers concurrently against the same
target/date. Airflow's `max_active_runs=1` serializes its own scheduled runs but is not a
global lock.

Raw device IDs and coordinates stay in the restricted RAW schema. They are never included in
the dashboard snapshot. Real mobility data needs a separate privacy/legal review, retention
policy, access control, and aggregation thresholds.

Unit tests use a simulated connector; they do not prove live Snowflake SQL, permissions, or
network connectivity. Before enabling the schedule, load a small synthetic day twice into a
development account and verify row counts, non-null GEOGRAPHY values, and adjacent-day
retention.
