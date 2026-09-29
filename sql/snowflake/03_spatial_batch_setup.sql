-- One-time setup for the GeoPulse daily batch publisher.
-- Run in the GEOPULSE database with a provisioning role. No existing rows are deleted.
-- For a custom database/schema, adjust these identifiers and the worker settings together.

CREATE SCHEMA IF NOT EXISTS GEOPULSE.SPATIAL;

CREATE TABLE IF NOT EXISTS GEOPULSE.SPATIAL.PING_STORE_MATCHES (
    device_id VARCHAR NOT NULL,
    event_ts TIMESTAMP_NTZ NOT NULL COMMENT 'Canonical UTC timestamp from Sedona',
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

-- The runtime role needs USAGE on the database, schema, and warehouse;
-- SELECT, INSERT, DELETE on this table; and CREATE STAGE on this schema.
-- Temporary tables do not require the schema's CREATE TABLE privilege.
-- Apply grants with an administrator-managed role; credentials never belong in this file.
