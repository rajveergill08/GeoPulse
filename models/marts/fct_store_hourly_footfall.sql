with hourly_traffic as (
    select *
    from {{ ref('int_store_hourly_traffic') }}
)

select
    concat(
        store_id,
        '|',
        cast(traffic_hour_local as varchar),
        '|',
        '{{ var("geopulse_retail_timezone", "Asia/Kolkata") }}'
    ) as store_hour_key,
    store_id,
    store_name,
    store_status,
    traffic_hour_local,
    cast(traffic_hour_local as date) as traffic_date_local,
    extract(hour from traffic_hour_local) as event_hour_local,
    '{{ var("geopulse_retail_timezone", "Asia/Kolkata") }}' as retail_timezone,
    {{ traffic_daypart('traffic_hour_local') }} as daypart,
    unique_visitors,
    ping_count,
    avg_accuracy_m,
    avg_distance_to_store_m,
    first_ping_at_utc,
    last_ping_at_utc,
    first_ping_at_local,
    last_ping_at_local
from hourly_traffic
