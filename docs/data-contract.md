# Synthetic mobility ping data contract

The generator creates artificial GPS activity for pipeline development. No row represents a
real person or real device.

## Grain

One row represents one simulated observation for one anonymous device at one event timestamp.
The natural key for development purposes is `(device_id, event_ts)`.

## Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `device_id` | string | Yes | Stable SHA-256-derived identifier prefixed with `dev_`. |
| `event_ts` | ISO-8601 timestamp | Yes | Timezone-aware observation time. |
| `latitude` | decimal | Yes | WGS84 latitude in the configured city bounds. |
| `longitude` | decimal | Yes | WGS84 longitude in the configured city bounds. |
| `accuracy_m` | decimal | Yes | Simulated horizontal GPS accuracy in metres. |
| `activity_type` | string | Yes | Synthetic truth label used only to validate traffic patterns. |

## Generation guarantees

- A fixed configuration and seed produce identical rows.
- Output row count is exactly `devices * days * (1440 / interval_minutes)`.
- Device identifiers do not contain a source device number or personal identifier.
- Coordinates remain within the configured city bounds.
- Output is streamed rather than accumulated in memory.
- Weekdays include home, commute, work, retail, and return-home periods.
- Weekends include home, leisure travel, retail, and return-home periods.

## Privacy boundary

This dataset is synthetic and safe for development demonstrations. The hash scheme is not a
replacement for a production privacy program. Real mobility data must use a secret managed salt,
documented retention limits, aggregation thresholds, access controls, and legal/privacy review.
Raw identifiers must never enter the analytics warehouse.

## Snowflake mapping

The raw CSV lands in `GEOPULSE.RAW.MOBILE_PINGS_STAGE`. Valid rows are converted into
`GEOPULSE.RAW.MOBILE_PINGS`, where `ST_MAKEPOINT(longitude, latitude)` creates the native
`GEOGRAPHY` value. Invalid timestamps and out-of-range coordinates remain queryable through
`GEOPULSE.RAW.REJECTED_MOBILE_PINGS`.
