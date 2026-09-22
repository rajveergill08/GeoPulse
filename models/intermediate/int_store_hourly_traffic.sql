with matches as (
    select *
    from {{ ref('stg_ping_store_matches') }}
)

select
    store_id,
    max(store_name) as store_name,
    max(store_status) as store_status,
    traffic_hour_utc,
    count(distinct device_id) as unique_visitors,
    count(*) as ping_count,
    avg(accuracy_m) as avg_accuracy_m,
    avg(distance_to_store_m) as avg_distance_to_store_m,
    min(event_ts_utc) as first_ping_at_utc,
    max(event_ts_utc) as last_ping_at_utc
from matches
group by store_id, traffic_hour_utc
