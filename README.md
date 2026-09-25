# GeoPulse

GeoPulse is a hyper-local retail mobility analytics platform for evaluating proposed store
locations and quantifying possible traffic cannibalization. It combines synthetic mobility data,
Snowflake geospatial storage, Apache Sedona spatial joins, dbt models, Airflow orchestration, and
a React/Kepler.gl decision dashboard.

## Current implementation

The current implementation provides:

- A deterministic, streaming Python generator for anonymized mobile GPS pings.
- Weekday commuter and weekend retail movement patterns around Bengaluru.
- CSV and compressed CSV output suitable for large development datasets.
- Snowflake DDL and loading SQL using native `GEOGRAPHY` points.
- A PySpark/Apache Sedona job that validates pings and builds metric store catchments.
- A broadcast spatial intersection join with Parquet matches, rejects, and audit metrics.
- Snowflake-ready dbt models for hourly unique visitors, ping volume, and traffic dayparts.
- Store-pair cannibalization metrics for shared visitors, traffic at risk, and incremental reach.
- A React/Kepler.gl decision dashboard with KPI cards, scenario selection, and mobility arcs.
- Data-contract documentation, unit tests, and GitHub Actions validation.

## Architecture roadmap

| Phase | Data engineering | Analytics and UI |
| --- | --- | --- |
| Week 1 | Generate mobility pings and load native Snowflake `GEOGRAPHY` points | Define the raw data contract and validate traffic patterns |
| Week 2 | Build 500 m catchments and Apache Sedona point-in-polygon joins | Create dbt hourly footfall and unique-visitor models |
| Week 3 | Track devices shared by existing and proposed catchments | Build cannibalization metrics and the React/Kepler.gl map |
| Week 4 | Orchestrate PySpark and dbt with Airflow | Add animated H3 layers, quality checks, and final documentation |

## Quick start

Requirements: Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --editable .

geopulse-generate `
  --devices 1000 `
  --days 1 `
  --interval-minutes 15 `
  --start-date 2026-09-19 `
  --output data/generated/mobile_pings.csv.gz
```

The example writes 96,000 records. Increase `--devices` or `--days` to exercise larger loads;
generation remains streaming so rows are not held in memory.

Run the validation suite:

```powershell
python -m unittest discover -s tests -v
```

## Run the spatial catchment join

Install the optional Spark dependencies (Java 17 is also required):

```powershell
python -m pip install --editable ".[spatial]"

geopulse-spatial-join `
  --pings data/generated/mobile_pings.csv.gz `
  --stores data/reference/stores.csv `
  --output data/output/spatial `
  --shuffle-partitions 8
```

The job creates 500-metre spheroidal catchments around the reference stores and keeps a match
for every catchment intersected by a ping. Overlapping matches are retained for the later
cannibalization model. See `docs/spatial-join.md` for data-quality rules, output contracts, and
scaling notes.

## Build footfall and cannibalization metrics

Install the analytics dependencies and run the complete dbt fixture build:

```powershell
python -m pip install --editable ".[analytics]"
dbt seed --profiles-dir profiles/ci --target ci --full-refresh
dbt build --profiles-dir profiles/ci --target ci --exclude-resource-type seed
```

`fct_store_hourly_footfall` distinguishes unique visitors from raw ping volume. The downstream
`fct_store_cannibalization` model compares existing and proposed catchments by date and daypart;
the deterministic fixture proves a 30% morning traffic-at-risk scenario. See
`docs/dbt-footfall.md` and `docs/cannibalization.md` for metric definitions, interpretation
guardrails, and Snowflake execution instructions.

## Run the mobility dashboard

The dashboard requires Node.js 20.19 or newer. It starts with a synthetic, aggregated fixture so
the full decision workflow can be evaluated without browser access to Snowflake credentials.

```powershell
Set-Location dashboard
npm install
Copy-Item .env.example .env.local
npm run dev
```

Set `VITE_MAPBOX_ACCESS_TOKEN` in `.env.local` to enable the basemap. The KPI cards and scenario
panel remain available without a token. Run `npm run lint`, `npm run test`, and `npm run build`
before publishing a change. See `dashboard/README.md` for the response contract and production
integration boundary.

## Load into Snowflake

1. Generate `data/generated/mobile_pings.csv.gz`.
2. Run `sql/snowflake/01_raw_mobility.sql` with a role allowed to create the GeoPulse objects.
3. Use the `PUT` example in that file to upload the generated data to the internal stage.
4. Run the `COPY`, typed insert, and validation statements.

The loader retains malformed staging rows in a rejected-record view and converts valid
longitude/latitude pairs using `ST_MAKEPOINT(longitude, latitude)`.

## Privacy

All generated records are synthetic. They contain no real mobile identifiers or human movement.
See `docs/data-contract.md` for the schema, generation guarantees, and production privacy
boundary.
