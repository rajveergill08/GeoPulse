-- GeoPulse Week 1: raw mobility ingestion with native GEOGRAPHY points.
-- Run with a Snowflake role allowed to create objects in the GEOPULSE database.

CREATE DATABASE IF NOT EXISTS GEOPULSE;
CREATE SCHEMA IF NOT EXISTS GEOPULSE.RAW;

CREATE FILE FORMAT IF NOT EXISTS GEOPULSE.RAW.MOBILITY_CSV_FORMAT
    TYPE = CSV
    COMPRESSION = AUTO
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    SKIP_HEADER = 1
    EMPTY_FIELD_AS_NULL = TRUE
    ERROR_ON_COLUMN_COUNT_MISMATCH = TRUE;

CREATE STAGE IF NOT EXISTS GEOPULSE.RAW.MOBILITY_STAGE
    FILE_FORMAT = GEOPULSE.RAW.MOBILITY_CSV_FORMAT;

CREATE TABLE IF NOT EXISTS GEOPULSE.RAW.MOBILE_PINGS_STAGE (
    device_id VARCHAR,
    event_ts_raw VARCHAR,
    latitude_raw VARCHAR,
    longitude_raw VARCHAR,
    accuracy_m_raw VARCHAR,
    activity_type VARCHAR,
    source_filename VARCHAR,
    staged_at TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS GEOPULSE.RAW.MOBILE_PINGS (
    ping_id VARCHAR DEFAULT UUID_STRING(),
    device_id VARCHAR NOT NULL,
    event_ts TIMESTAMP_TZ NOT NULL,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    accuracy_m FLOAT,
    activity_type VARCHAR,
    location GEOGRAPHY NOT NULL,
    source_filename VARCHAR,
    ingested_at TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (TO_DATE(event_ts));

-- Upload a generated file before running COPY. Example for SnowSQL:
-- PUT file://data/generated/mobile_pings.csv.gz
--     @GEOPULSE.RAW.MOBILITY_STAGE
--     AUTO_COMPRESS = FALSE
--     OVERWRITE = TRUE;

TRUNCATE TABLE GEOPULSE.RAW.MOBILE_PINGS_STAGE;

COPY INTO GEOPULSE.RAW.MOBILE_PINGS_STAGE (
    device_id,
    event_ts_raw,
    latitude_raw,
    longitude_raw,
    accuracy_m_raw,
    activity_type,
    source_filename
)
FROM (
    SELECT
        source.$1,
        source.$2,
        source.$3,
        source.$4,
        source.$5,
        source.$6,
        METADATA$FILENAME
    FROM @GEOPULSE.RAW.MOBILITY_STAGE source
)
ON_ERROR = CONTINUE
FORCE = TRUE;

-- Make the typed load repeatable when the same staged file is processed again.
DELETE FROM GEOPULSE.RAW.MOBILE_PINGS
WHERE source_filename IN (
    SELECT DISTINCT source_filename
    FROM GEOPULSE.RAW.MOBILE_PINGS_STAGE
);

INSERT INTO GEOPULSE.RAW.MOBILE_PINGS (
    device_id,
    event_ts,
    latitude,
    longitude,
    accuracy_m,
    activity_type,
    location,
    source_filename
)
SELECT
    device_id,
    TRY_TO_TIMESTAMP_TZ(event_ts_raw),
    TRY_TO_DOUBLE(latitude_raw),
    TRY_TO_DOUBLE(longitude_raw),
    TRY_TO_DOUBLE(accuracy_m_raw),
    activity_type,
    ST_MAKEPOINT(TRY_TO_DOUBLE(longitude_raw), TRY_TO_DOUBLE(latitude_raw)),
    source_filename
FROM GEOPULSE.RAW.MOBILE_PINGS_STAGE
WHERE TRY_TO_TIMESTAMP_TZ(event_ts_raw) IS NOT NULL
  AND TRY_TO_DOUBLE(latitude_raw) BETWEEN -90 AND 90
  AND TRY_TO_DOUBLE(longitude_raw) BETWEEN -180 AND 180;

CREATE OR REPLACE VIEW GEOPULSE.RAW.REJECTED_MOBILE_PINGS AS
SELECT *
FROM GEOPULSE.RAW.MOBILE_PINGS_STAGE
WHERE TRY_TO_TIMESTAMP_TZ(event_ts_raw) IS NULL
   OR TRY_TO_DOUBLE(latitude_raw) IS NULL
   OR TRY_TO_DOUBLE(longitude_raw) IS NULL
   OR TRY_TO_DOUBLE(latitude_raw) NOT BETWEEN -90 AND 90
   OR TRY_TO_DOUBLE(longitude_raw) NOT BETWEEN -180 AND 180;

-- Basic post-load validation.
SELECT
    COUNT(*) AS total_pings,
    COUNT(DISTINCT device_id) AS unique_devices,
    MIN(event_ts) AS first_ping_at,
    MAX(event_ts) AS last_ping_at,
    COUNT_IF(location IS NULL) AS null_geographies
FROM GEOPULSE.RAW.MOBILE_PINGS;
