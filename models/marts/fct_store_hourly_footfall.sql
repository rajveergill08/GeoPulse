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
    case
        when extract(hour from traffic_hour_utc) between 5 and 9 then 'morning_commute'
        when extract(hour from traffic_hour_utc) between 10 and 15 then 'midday'
        when extract(hour from traffic_hour_utc) between 16 and 19 then 'evening_commute'
        else 'off_peak'
    end as daypart,
    unique_visitors,
    ping_count,
    avg_accuracy_m,
    avg_distance_to_store_m,
    first_ping_at_utc,
    last_ping_at_utc
from hourly_traffic
