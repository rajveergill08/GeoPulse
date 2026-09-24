select
    device_id,
    store_id,
    traffic_date_utc,
    daypart,
    count(*) as row_count
from {{ ref('int_store_device_daypart_visits') }}
group by device_id, store_id, traffic_date_utc, daypart
having count(*) > 1
