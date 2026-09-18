# GeoPulse

GeoPulse is a hyper-local retail mobility analytics platform for evaluating proposed store
locations and quantifying possible traffic cannibalization. It combines synthetic mobility data,
Snowflake geospatial storage, Apache Sedona spatial joins, dbt models, Airflow orchestration, and
a React/Kepler.gl decision dashboard.

## Current implementation

The first implementation milestone provides:

- A deterministic, streaming Python generator for anonymized mobile GPS pings.
- Weekday commuter and weekend retail movement patterns around Bengaluru.
- CSV and compressed CSV output suitable for large development datasets.
- Snowflake DDL and loading SQL using native `GEOGRAPHY` points.
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
