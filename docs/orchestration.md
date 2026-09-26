# Daily Airflow orchestration

The Week 4 orchestration milestone coordinates the existing synthetic mobility, Apache Sedona,
warehouse publishing, and dbt workloads. The DAG uses Airflow 3's public authoring interface and
keeps credentials and network access out of DAG parsing.

## Task graph

```text
validate_runtime_configuration
  -> generate_daily_pings
  -> run_sedona_spatial_join
  -> load_spatial_matches
  -> build_dbt_analytics
```

The preflight task checks the loader command, executables, store reference, dbt profile, and data
root before the 9.6-million-row default workload can start.

`geopulse_daily_pipeline` runs at 02:00 in `Asia/Kolkata`, does not create historical runs
automatically (`catchup=False`), and permits only one active run. Each task retries twice after a
10-minute delay. A run processes the date at the start of its logical data interval, rather than
the worker's wall clock, so manual retries always address the same data.

The default development paths for a logical date such as 26 September 2026 are:

```text
data/generated/20260926/mobile_pings.csv.gz
data/output/spatial/20260926/
data/output/spatial/20260926/matches/
```

Generation replaces its date-specific file and Sedona uses `--write-mode overwrite`. Those
behaviors make the compute tasks safe to retry without appending duplicate files. The warehouse
loader must provide the same idempotency guarantee for its batch.

## Install and validate

Apache Airflow is supported on Linux. On Windows, run these commands inside WSL2 or a Linux
container. Python 3.12 is used by CI.

```bash
AIRFLOW_VERSION=3.3.2
PYTHON_VERSION="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

python -m pip install --editable ".[orchestration]" --constraint "$CONSTRAINT_URL"

# Build task runtimes separately so Spark/dbt cannot replace constrained Airflow packages.
python -m venv .venv-spatial
.venv-spatial/bin/python -m pip install --editable ".[spatial]"
python -m venv .venv-analytics
.venv-analytics/bin/python -m pip install --editable ".[analytics]"

export AIRFLOW_HOME=/tmp/geopulse-airflow
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/dags"
export GEOPULSE_PROJECT_ROOT="$PWD"
export GEOPULSE_PYTHON_BIN="$PWD/.venv-spatial/bin/python"
export GEOPULSE_DBT_BIN="$PWD/.venv-analytics/bin/dbt"

python -m unittest discover -s tests -p "test_airflow_dag.py" -v
airflow db migrate
airflow dags list
```

The parse test validates the schedule, timezone, task set, and exact dependency chain without
executing Spark, Snowflake, or dbt. Their execution paths remain covered by the separate spatial
and dbt CI jobs. The SQLite metadata database created by `airflow db migrate` is suitable for this
local listing only, not for production.

## Runtime configuration

Most configuration is captured from the DAG processor environment when it parses the file, and
relative paths are resolved against `GEOPULSE_PROJECT_ROOT`. Set these values on the DAG processor
and mount the project, data root, store file, task environments, and dbt profile at the same
absolute paths on every worker. `GEOPULSE_WAREHOUSE_LOAD_COMMAND` is checked from the task's
runtime worker environment and is not embedded in the serialized DAG.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEOPULSE_PROJECT_ROOT` | Repository containing the DAG | Installed GeoPulse project root. |
| `GEOPULSE_DATA_ROOT` | `<project>/data` | Shared input and output root. |
| `GEOPULSE_STORES_PATH` | `<data>/reference/stores.csv` | Store catchment definitions. |
| `GEOPULSE_PYTHON_BIN` | `python` | Python executable with GeoPulse and spatial dependencies. |
| `GEOPULSE_DBT_BIN` | `dbt` | dbt executable available to the worker. |
| `GEOPULSE_DEVICES` | `100000` | Daily synthetic devices; at 15-minute intervals this creates 9.6 million pings. |
| `GEOPULSE_INTERVAL_MINUTES` | `15` | Ping interval; must divide 1,440 exactly. |
| `GEOPULSE_GENERATOR_SEED` | `42` | Deterministic generator seed. |
| `GEOPULSE_SPARK_MASTER` | `local[*]` | Spark master URL; replace for a distributed cluster. |
| `GEOPULSE_SHUFFLE_PARTITIONS` | `200` | Spark shuffle partition count. |
| `GEOPULSE_DBT_PROFILES_DIR` | `<project>/profiles/snowflake` | Production dbt profile directory. |
| `GEOPULSE_DBT_TARGET` | `snowflake` | dbt target name. |
| `GEOPULSE_WAREHOUSE_LOAD_COMMAND` | No default | Required batch-aware Parquet publishing command. |

Use a smaller value such as `GEOPULSE_DEVICES=1000` for a development run. Production workers
also require Java 17, access to compatible Sedona Maven packages, Snowflake connectivity, and the
environment variables referenced by `profiles/snowflake/profiles.yml`.

## Required warehouse publishing boundary

Sedona writes Parquet files, while the dbt source is
`GEOPULSE.SPATIAL.PING_STORE_MATCHES`. Local files do not appear in Snowflake automatically. The
preflight task therefore fails with exit code 64 when `GEOPULSE_WAREHOUSE_LOAD_COMMAND` is absent,
before generation or Spark consumes resources. `load_spatial_matches` executes the command only
after Sedona succeeds.

The loader receives these rendered environment variables:

- `GEOPULSE_RUN_DATE` and `GEOPULSE_RUN_PARTITION`
- `GEOPULSE_PINGS_PATH`
- `GEOPULSE_SPATIAL_OUTPUT`
- `GEOPULSE_SPATIAL_MATCHES_PATH`

The deployment-specific command must upload only the indicated match partition, then replace or
merge that logical batch transactionally. `sql/snowflake/02_spatial_matches.sql` remains a
development full-refresh reference; its `TRUNCATE` workflow is not a batch-aware daily loader and
must not be used unchanged for this task.

The final dbt command uses `--exclude-resource-type seed`, ensuring the CI-only
`seeds/ping_store_matches.csv` fixture is never loaded into the production target.

For a dry-run of the preflight and loader tasks, the command may be set to
`echo publish-boundary-validated`. That value proves task wiring only and must never be used for a
real scheduled run. Parsing the DAG does not require a loader command.

## Operations and recovery

- Store `GEOPULSE_DATA_ROOT` on shared storage when tasks may run on different workers. A local
  worker path is not automatically visible to another machine.
- Re-run a failed task or the same logical DAG run; do not create a new wall-clock partition. The
  generator and Sedona tasks overwrite only that run's dated paths.
- If warehouse publishing partially fails, clean or roll back that one batch using the loader's
  transaction rules, then retry `load_spatial_matches`. dbt remains blocked until publishing
  succeeds.
- Manual historical runs must use the intended logical date and a loader that can safely replace
  that batch. Automatic catchup stays disabled to prevent an accidental multi-day Spark surge.
- Keep Snowflake passwords, keys, and tokens in the Airflow secret backend or protected worker
  environment. Never place credentials in the DAG, loader command, logs, or repository.
