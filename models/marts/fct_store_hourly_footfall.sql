with hourly_traffic as (
    select *
    from {{ ref('int_store_hourly_traffic') }}
)

select
    concat(store_id, '|', cast(traffic_hour_utc as varchar)) as store_hour_key,
    store_id,
    store_name,
    store_status,
    traffic_hour_utc,
    cast(traffic_hour_utc as date) as traffic_date_utc,
    extract(hour from traffic_hour_utc) as event_hour_utc,
    {{ traffic_daypart('traffic_hour_utc') }} as daypart,
    unique_visitors,
    ping_count,
    avg_accuracy_m,
    avg_distance_to_store_m,
    first_ping_at_utc,
    last_ping_at_utc
from hourly_traffic
