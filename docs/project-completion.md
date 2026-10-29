# GeoPulse completion and acceptance checklist

GeoPulse is a working **synthetic-data demonstration**, not a validated live mobility service.
The repository implements the four-week architecture, but local tests and GitHub CI cannot
establish Snowflake account permissions, production-scale Spark performance, or deployed-map
behavior. A 30% shared-catchment rate is an overlap proxy, not measured diversion or lost sales.

## Acceptance against the project plan

| Milestone | Repository evidence | Current acceptance boundary |
| --- | --- | --- |
| Week 1: synthetic GPS and Snowflake `GEOGRAPHY` | `src/geopulse/synthetic.py`, `src/geopulse/raw_warehouse.py`, `sql/snowflake/04_raw_batch_setup.sql`, `tests/test_synthetic.py`, `tests/test_raw_warehouse.py` | Streaming generation and the daily loader are implemented; the loader has only been exercised with a simulated connector, not a development Snowflake account. |
| Week 2: metric catchments, Sedona join, hourly footfall | `src/geopulse/spatial.py`, `models/marts/fct_store_hourly_footfall.sql`, `tests/test_spatial.py`, dbt fixture tests | Small Sedona integration tests and DuckDB-backed dbt models pass. No recorded 10-million-point/5,000-polygon run proves memory safety or elapsed time at the proposed scale. |
| Week 3: shared visitors and location comparison | `models/marts/fct_store_cannibalization.sql`, `models/intermediate/int_store_pair_ordered_evidence.sql`, `dashboard/src/components/ScenarioComparison.tsx`, `dashboard/src/components/FootfallTimeline.tsx` | Synthetic fixtures and dashboard tests verify overlap, ordered-observation diagnostics, candidate comparison, and hourly playback. They do not prove purchases, sales cannibalization, or representativeness. |
| Week 4: orchestration, H3, and map | `dags/geopulse_daily_pipeline.py`, `src/geopulse/dashboard_export.py`, `models/marts/fct_h3_hourly_footfall.sql`, `dashboard/src/components/MobilityMap.tsx`, `.github/workflows/ci.yml` | The DAG parses, modeled fixtures pass, and the dashboard builds. A credentialed Airflow-to-Snowflake run, hosted daily snapshot, and deployed interactive-map check remain unverified. A Mapbox token is optional for a street basemap. |
| Original use case: commercial zoning overlay | `src/geopulse/zoning.py`, `data/reference/synthetic_commercial_zones.csv`, and `tests/test_zoning.py` provide a separate Sedona intersection with three fictional polygons. | The example proves only the synthetic join. No official zoning feed, zone mart, Snowflake publication, Airflow task, or dashboard zone layer is present. Real zoning claims require an approved dataset, category definitions, effective dates, and geometry/CRS validation. |

The dashboard intentionally consumes an aggregate JSON export rather than connecting from the
browser to Snowflake. This keeps warehouse credentials and raw device-level records on workers.
The exporter and browser currently require synthetic data; the flag is an assertion, not proof
of provenance. Real mobility data needs a separate privacy, retention, access, and small-cell
review before publication.

## What automated checks establish

GitHub CI runs Python unit tests and lint/format checks, small Sedona store and synthetic-zone
integration suites, an end-to-end synthetic spatial smoke batch, a
DuckDB-backed dbt fixture build plus Snowflake project parsing, an Airflow DAG-structure test,
and dashboard lint/tests/production build. Publisher tests simulate connector responses and
transaction failures. These checks establish local contracts and regression behavior, **not**
live Snowflake SQL execution, production permissions, distributed scale, or a hosted dashboard.
The dashboard's `audit:critical` gate is a severity threshold; it does not mean the dependency
tree has no lower-severity advisories. Review and resolve those before public hosting.

## Manual acceptance in a development environment

Use only generated mobility data for these checks. Keep credentials in a protected worker
environment or secret backend; never put them in Git, a shell command, screenshots, JSON, or
browser variables. Record the run date, commit SHA, component versions, row counts, and results
in a private test log without copying device IDs or secrets.

1. **Provision and isolate.** In a Snowflake development account, run
   `sql/snowflake/04_raw_batch_setup.sql` and `sql/snowflake/03_spatial_batch_setup.sql` with a
   provisioning role. Grant the loader and dbt roles only the usage and table privileges listed
   in `docs/raw-warehouse-loading.md` and `docs/warehouse-loading.md`. Keep CI seed tables out
   of the development target. Verify `dbt debug --profiles-dir profiles/snowflake --target snowflake`.
2. **Publish one small synthetic day.** Generate a known local day (for example 100 devices at
   15-minute intervals produce 9,600 pings), then run `geopulse-load-raw --dry-run` with its
   exact date, file, expected rows, and devices. Remove `--dry-run` only after the preview
   passes. Query `GEOPULSE.RAW.MOBILE_PINGS` for that local day's half-open UTC interval:
   confirm 9,600 rows, 100 distinct devices, and no null `location` values. Record counts for
   an adjacent day before retrying, so retention can be checked.
3. **Join and publish spatial matches.** Run `geopulse-spatial-join` with the generated file and
   `data/reference/stores.csv`; then run `geopulse-validate-spatial` against its `audit/` and
   `matches/` paths with `--expected-ping-rows 9600`. Confirm completion markers, audit
   reconciliation, and valid Parquet parts. Run `geopulse-load-spatial --dry-run` and then the
   actual publisher for that same date. Compare Snowflake's match and distinct-device counts
   with the audit; check that every stored timestamp is within the retail-day UTC interval.
4. **Verify retry and marts.** Rerun both publishers for the same logical day; confirm its row
   counts are unchanged rather than doubled and adjacent-day counts are retained. Run
   `dbt build --profiles-dir profiles/snowflake --target snowflake --exclude-resource-type seed`.
   Confirm all dbt tests pass and inspect store-hour, store-pair/daypart, and H3 cell-hour rows
   for the requested local day. Cross-check rate numerators/denominators and ensure no device
   identifier appears in the marts intended for dashboard export.
5. **Export and orchestrate.** Run `geopulse-export-dashboard --synthetic` for the same day to a
   protected output path. Verify that the JSON contains only approved aggregate fields, its
   local date and UTC refresh timestamp are correct, and a same-day retry preserves one complete
   snapshot. On Linux/WSL2, configure the documented Airflow worker environments and real
   `GEOPULSE_WAREHOUSE_LOAD_COMMAND`; run one small logical day through the DAG. Confirm each
   task's audit, retry behavior, and downstream blocking when a quality gate fails. Never use
   the documented `echo` wiring example as a real publisher.
6. **Host and inspect.** Serve the completed synthetic JSON from a read-only static endpoint and
   build the dashboard with `VITE_GEOPULSE_DATA_URL` pointing to it. The token-free `no_map`
   mode should still render interactive H3 columns and store markers; a Mapbox token adds an
   optional street basemap. Verify that no Snowflake secret, raw ping, or device ID is in browser
   assets or network responses. In a browser, switch candidates, scrub and play all 24 local
   hours, check missing-hour wording, and inspect 3D H3 cells against the exported counts.
   Hosting and visual deployment checks are not completed by this repository's CI.

For the exact CLI arguments, role settings, recovery rules, and day-boundary examples, follow
`docs/raw-warehouse-loading.md`, `docs/spatial-join.md`, `docs/warehouse-loading.md`,
`docs/orchestration.md`, `docs/dashboard-export.md`, and `docs/zoning-overlay.md`. Do not use
the legacy full-refresh SQL scripts as scheduled loaders.

## Reproducible synthetic spatial verification

On Linux or WSL2, install Java 17 and `.[spatial]`, then run the opt-in verifier with a **new**
output directory. It runs the existing streaming generator, Sedona join, and spatial quality
gate in sequence. It never replaces an existing directory. The default 100 devices at 15-minute
intervals produce 9,600 pings against the four reference stores:

```bash
geopulse-verify-spatial-scale \
  --run-date 2026-09-22 \
  --stores data/reference/stores.csv \
  --output data/output/verification/smoke-20260922 \
  --devices 100
```

To prepare the originally proposed 10-million-point/5,000-polygon experiment, use a properly
provisioned Spark environment and a path visible to every worker. The synthetic store option
retains the four reference locations and fills the rest with a reproducible Bengaluru grid of
500-metre candidate catchments. `--plan` prints commands without writing data:

```bash
geopulse-verify-spatial-scale \
  --run-date 2026-09-22 \
  --stores data/reference/stores.csv \
  --output data/output/verification/scale-20260922 \
  --devices 104167 \
  --synthetic-stores 5000 \
  --master 'spark://YOUR-CLUSTER:7077' \
  --shuffle-partitions 200 \
  --plan
```

Remove `--plan` only after checking cluster capacity, storage, paths, and costs. That device
count yields 10,000,032 pings. A completed run writes `verification.json` and per-stage logs;
the JSON records elapsed times, Spark settings, machine context, audit counts, rejection rates,
and pass/fail status. It does **not** measure peak Spark/JVM worker memory. To claim the scale
target was demonstrated, retain a successful report, Spark executor and driver memory metrics,
cluster sizing, and the exact commit SHA. A planned workload or a small smoke pass is not such
proof. This verifier does not execute Snowflake, dbt, Airflow, or the dashboard.
