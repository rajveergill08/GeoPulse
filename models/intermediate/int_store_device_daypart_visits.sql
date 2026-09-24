with matches as (
    select *
    from {{ ref('stg_ping_store_matches') }}
),

classified as (
    select
        device_id,
        store_id,
        store_name,
        store_status,
        cast(event_ts_utc as date) as traffic_date_utc,
        {{ traffic_daypart('event_ts_utc') }} as daypart
    from matches
)

select
    device_id,
    store_id,
    max(store_name) as store_name,
    max(store_status) as store_status,
    traffic_date_utc,
    daypart
from classified
group by device_id, store_id, traffic_date_utc, daypart
