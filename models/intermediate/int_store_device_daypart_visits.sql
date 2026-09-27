with matches as (
    select *
    from {{ ref('stg_ping_store_matches') }}
),

localized as (
    select
        *,
        {{ utc_to_retail_local('event_ts_utc') }} as event_ts_local
    from matches
),

classified as (
    select
        device_id,
        store_id,
        store_name,
        store_status,
        cast(event_ts_local as date) as traffic_date_local,
        {{ traffic_daypart('event_ts_local') }} as daypart
    from localized
)

select
    device_id,
    store_id,
    max(store_name) as store_name,
    max(store_status) as store_status,
    traffic_date_local,
    daypart
from classified
group by device_id, store_id, traffic_date_local, daypart
