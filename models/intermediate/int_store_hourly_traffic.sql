with matches as (
    select *
    from {{ ref('stg_ping_store_matches') }}
),

localized as (
    select
        *,
        {{ utc_to_retail_local('event_ts_utc') }} as event_ts_local
    from matches
)

select
    store_id,
    max(store_name) as store_name,
    max(store_status) as store_status,
    date_trunc('hour', event_ts_local) as traffic_hour_local,
    count(distinct device_id) as unique_visitors,
    count(*) as ping_count,
    avg(accuracy_m) as avg_accuracy_m,
    avg(distance_to_store_m) as avg_distance_to_store_m,
    min(event_ts_utc) as first_ping_at_utc,
    max(event_ts_utc) as last_ping_at_utc,
    min(event_ts_local) as first_ping_at_local,
    max(event_ts_local) as last_ping_at_local
from localized
group by store_id, date_trunc('hour', event_ts_local)
