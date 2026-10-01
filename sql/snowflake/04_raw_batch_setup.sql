-- One-time, non-destructive setup for the daily raw GPS publisher.
-- Run with a provisioning role. Existing rows are never truncated or replaced here.
-- Keep database/schema names aligned with DBT_SNOWFLAKE_DATABASE and the RAW loader.

CREATE DATABASE IF NOT EXISTS GEOPULSE;
CREATE SCHEMA IF NOT EXISTS GEOPULSE.RAW;

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

-- Grant the runtime role warehouse/database/schema USAGE and SELECT/INSERT/DELETE
-- on MOBILE_PINGS. The landing stage/table are session-temporary objects.
-- Apply grants with an administrator-managed role; never put credentials in SQL.
