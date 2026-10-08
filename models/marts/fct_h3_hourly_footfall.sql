with ping_cells as (
    select *
    from {{ ref('stg_h3_ping_cells') }}
),

localized as (
    select
        device_id,
        hex_id,
        {{ utc_to_retail_local('event_ts_utc') }} as event_ts_local
    from ping_cells
),

hourly as (
    select
        hex_id,
        date_trunc('hour', event_ts_local) as traffic_hour_local,
        count(distinct device_id) as unique_visitors,
        count(*) as ping_count
    from localized
    group by hex_id, date_trunc('hour', event_ts_local)
)

select
    concat(
        hex_id,
        '|',
        cast(traffic_hour_local as varchar),
        '|',
        '{{ var("geopulse_retail_timezone", "Asia/Kolkata") }}'
    ) as h3_hour_key,
    hex_id,
    8 as h3_resolution,
    traffic_hour_local,
    cast(traffic_hour_local as date) as traffic_date_local,
    extract(hour from traffic_hour_local) as event_hour_local,
    '{{ var("geopulse_retail_timezone", "Asia/Kolkata") }}' as retail_timezone,
    unique_visitors,
    ping_count
from hourly
