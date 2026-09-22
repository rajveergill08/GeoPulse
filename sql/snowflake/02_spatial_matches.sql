-- GeoPulse Week 2: Snowflake landing table for Apache Sedona match output.
-- Upload the Parquet part files from data/output/spatial/matches to the internal stage,
-- then run the COPY statement below. Partition folders may be preserved in stage paths.

CREATE SCHEMA IF NOT EXISTS GEOPULSE.SPATIAL;

CREATE FILE FORMAT IF NOT EXISTS GEOPULSE.SPATIAL.SPATIAL_MATCH_PARQUET_FORMAT
    TYPE = PARQUET;

CREATE STAGE IF NOT EXISTS GEOPULSE.SPATIAL.SPATIAL_MATCH_STAGE
    FILE_FORMAT = GEOPULSE.SPATIAL.SPATIAL_MATCH_PARQUET_FORMAT;

CREATE TABLE IF NOT EXISTS GEOPULSE.SPATIAL.PING_STORE_MATCHES (
    device_id VARCHAR NOT NULL,
    event_ts TIMESTAMP_NTZ NOT NULL COMMENT 'UTC timestamp from the Sedona job',
    ping_latitude FLOAT,
    ping_longitude FLOAT,
    accuracy_m FLOAT,
    activity_type VARCHAR,
    store_id VARCHAR NOT NULL,
    store_name VARCHAR,
    store_status VARCHAR,
    catchment_radius_m FLOAT,
    distance_to_store_m FLOAT,
    source_filename VARCHAR,
    loaded_at TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (TO_DATE(event_ts), store_id);

-- Development full refresh. Replace with batch-aware incremental loading before production.
TRUNCATE TABLE GEOPULSE.SPATIAL.PING_STORE_MATCHES;

COPY INTO GEOPULSE.SPATIAL.PING_STORE_MATCHES (
    device_id,
    event_ts,
    ping_latitude,
    ping_longitude,
    accuracy_m,
    activity_type,
    store_id,
    store_name,
    store_status,
    catchment_radius_m,
    distance_to_store_m,
    source_filename
)
FROM (
    SELECT
        source.$1:device_id::VARCHAR,
        source.$1:event_ts::TIMESTAMP_NTZ,
        source.$1:ping_latitude::FLOAT,
        source.$1:ping_longitude::FLOAT,
        source.$1:accuracy_m::FLOAT,
        source.$1:activity_type::VARCHAR,
        source.$1:store_id::VARCHAR,
        source.$1:store_name::VARCHAR,
        source.$1:store_status::VARCHAR,
        source.$1:catchment_radius_m::FLOAT,
        source.$1:distance_to_store_m::FLOAT,
        METADATA$FILENAME
    FROM @GEOPULSE.SPATIAL.SPATIAL_MATCH_STAGE source
)
FILE_FORMAT = (FORMAT_NAME = GEOPULSE.SPATIAL.SPATIAL_MATCH_PARQUET_FORMAT)
PATTERN = '.*[.]parquet'
ON_ERROR = ABORT_STATEMENT;

SELECT
    COUNT(*) AS total_matches,
    COUNT(DISTINCT device_id) AS unique_devices,
    COUNT(DISTINCT store_id) AS matched_stores,
    MIN(event_ts) AS first_match_at_utc,
    MAX(event_ts) AS last_match_at_utc
FROM GEOPULSE.SPATIAL.PING_STORE_MATCHES;
