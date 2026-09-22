select
    store_id,
    traffic_hour_utc,
    count(*) as row_count
from {{ ref('fct_store_hourly_footfall') }}
group by store_id, traffic_hour_utc
having count(*) > 1
