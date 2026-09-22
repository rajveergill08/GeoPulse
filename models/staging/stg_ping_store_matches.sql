with source_matches as (
    select *
    from {{ source('spatial', 'ping_store_matches') }}
),

normalized as (
    select
        trim(cast(device_id as varchar)) as device_id,
        cast(event_ts as timestamp) as event_ts_utc,
        cast(ping_latitude as double) as ping_latitude,
        cast(ping_longitude as double) as ping_longitude,
        cast(accuracy_m as double) as accuracy_m,
        trim(cast(activity_type as varchar)) as activity_type,
        trim(cast(store_id as varchar)) as store_id,
        trim(cast(store_name as varchar)) as store_name,
        lower(trim(cast(store_status as varchar))) as store_status,
        cast(catchment_radius_m as double) as catchment_radius_m,
        cast(distance_to_store_m as double) as distance_to_store_m
    from source_matches
    where device_id is not null
      and event_ts is not null
      and store_id is not null
),

ranked as (
    select
        *,
        row_number() over (
            partition by device_id, event_ts_utc, store_id
            order by distance_to_store_m asc nulls last
        ) as duplicate_rank
    from normalized
)

select
    device_id,
    event_ts_utc,
    date_trunc('hour', event_ts_utc) as traffic_hour_utc,
    ping_latitude,
    ping_longitude,
    accuracy_m,
    activity_type,
    store_id,
    store_name,
    store_status,
    catchment_radius_m,
    distance_to_store_m
from ranked
where duplicate_rank = 1
