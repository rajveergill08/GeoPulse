select
    store_id,
    traffic_hour_local,
    count(*) as row_count
from {{ ref('fct_store_hourly_footfall') }}
group by store_id, traffic_hour_local
having count(*) > 1
