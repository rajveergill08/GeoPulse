# Daily Snowflake spatial publisher

`geopulse-load-spatial` publishes the validated output of one logical Asia/Kolkata calendar day
to the dbt source `GEOPULSE.SPATIAL.PING_STORE_MATCHES`. Repeating the same day replaces its rows
and retains observations from other days.

## Provision and configure

Run `sql/snowflake/03_spatial_batch_setup.sql` once with a provisioning role. It creates the
landing table if absent and preserves existing data. The older `02_spatial_matches.sql` is a
development full-refresh example and must not be used as the daily loader.

Install the publisher in the worker environment used by the loading command:

```bash
python -m pip install --editable '.[warehouse]'
```

Connection settings use the existing dbt worker environment. Supply credentials through the
worker secret backend or protected environment, rather than command-line arguments.

| Setting | Required/default |
| --- | --- |
| `DBT_SNOWFLAKE_ACCOUNT` | Required account identifier. |
| `DBT_SNOWFLAKE_USER` | Required service user. |
| `DBT_SNOWFLAKE_WAREHOUSE` | Required loading warehouse. |
| `DBT_SNOWFLAKE_ROLE` | Defaults to `GEOPULSE_TRANSFORMER`; choose a role with loading privileges. |
| `DBT_SNOWFLAKE_DATABASE` | Defaults to `GEOPULSE`. |
| `DBT_SNOWFLAKE_SOURCE_SCHEMA` | Defaults to `SPATIAL`, matching the dbt source. |
| `GEOPULSE_SNOWFLAKE_PRIVATE_KEY_FILE` | Optional private-key path; preferred for scheduled service users. |
| `GEOPULSE_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE` | Optional encrypted-key passphrase. |
| `DBT_SNOWFLAKE_PASSWORD` | Required when a private-key file is not supplied. |

Database and schema names must be simple unquoted identifiers. The session sets its timezone
to UTC, uses autocommit for preparation, and tags queries `geopulse_spatial_publisher`.
The loading role needs warehouse/database/schema usage, table SELECT/INSERT/DELETE, and schema
CREATE STAGE. dbt retains its own authentication configuration.

## Validate a plan without connecting

```bash
geopulse-load-spatial \
  --run-date 2026-09-29 \
  --audit data/output/spatial/20260929/audit \
  --matches data/output/spatial/20260929/matches \
  --expected-ping-rows 9600000 \
  --dry-run
```

The preview reruns the spatial quality gate and reports file paths, audit counts, target table,
and timestamp bounds. It does not import the connector or request credentials. Remove
`--dry-run` to publish after provisioning and configuring the worker.

September 29 in Asia/Kolkata corresponds to the half-open UTC interval
`[2026-09-28 18:30:00, 2026-09-29 18:30:00)`. The publisher uses those event-time bounds to
replace rows. The input's UTC partition folders can span two dates; they are not the batch key.
This boundary is aligned with GeoPulse's Bengaluru generator and retail-local dbt models.

## Publication sequence

1. Validate the local audit and every discovered Parquet part using the existing quality policy.
2. Create a unique session-scoped temporary stage and temporary table shaped like the source.
3. Upload each exact Parquet path to a separate numbered stage directory and confirm its PUT
   result. Numbered directories preserve parts with identical basenames across UTC partitions.
4. COPY that isolated stage into the temporary table with `ON_ERROR=ABORT_STATEMENT`, explicit
   Parquet field types, and logical timestamp handling.
5. Reconcile COPY and temporary-table row counts plus unique devices with the audit. Reject
   out-of-day timestamps, blank identifiers, unsupported statuses, and duplicate ping/store keys.
6. Begin a transaction, delete only the local day's UTC interval, insert the validated rows,
   verify the target count, and commit. Roll back on failure.

DDL occurs before the replacement transaction because Snowflake DDL implicitly commits an
active transaction. The transaction contains only DELETE, INSERT, and a verification query.
See the official [transaction rules](https://docs.snowflake.com/en/sql-reference/transactions)
and [COPY options](https://docs.snowflake.com/en/sql-reference/sql/copy-into-table).

Each attempt has a fresh temporary stage/table, preventing a retry from loading stale parts or
relying on COPY's prior-file history. Closing the dedicated session removes those objects and
their staged data. Keep the input directory stable throughout validation and publication.

## Airflow integration

The existing `GEOPULSE_WAREHOUSE_LOAD_COMMAND` boundary remains required. Install the warehouse
extra in the spatial worker environment, then set the command in the worker environment:

```bash
export GEOPULSE_WAREHOUSE_LOAD_COMMAND='"$GEOPULSE_PYTHON_BIN" -m geopulse.warehouse --run-date "$GEOPULSE_RUN_DATE" --audit "$GEOPULSE_SPATIAL_AUDIT_PATH" --matches "$GEOPULSE_SPATIAL_MATCHES_PATH" --expected-ping-rows "$GEOPULSE_EXPECTED_PING_ROWS" --max-ping-rejection-rate "$GEOPULSE_MAX_PING_REJECTION_RATE" --max-rejected-store-rows "$GEOPULSE_MAX_REJECTED_STORE_ROWS"'
```

The existing gate runs before this command; the publisher checks the policy again when invoked
independently. dbt remains downstream and builds only after publication succeeds.

## Recovery and verification scope

Use one publisher for this target. Airflow's `max_active_runs=1` serializes its daily runs, but
independent CLI processes writing the same date are not coordinated by a global lock.
An upload or validation failure leaves the permanent table untouched. A replacement failure
rolls back. If acknowledgement of COMMIT is lost, retry the same logical date; replacement
retains one copy of that batch. The CLI prints domain errors or a connector error class without
echoing credential-bearing connector messages.

Tests exercise upload and count failures, timestamp boundaries, rollback, same-day replacement,
and preservation of neighboring days using an in-memory connector simulation. They do not
confirm live Snowflake connectivity or execute SQL against an account. Before enabling a daily
schedule, publish a small synthetic batch twice in a development account and verify the row
counts and neighboring-day retention there.
