select
    store_id,
    traffic_hour_local,
    event_hour_local,
    traffic_date_local,
    retail_timezone
from {{ ref('fct_store_hourly_footfall') }}
where traffic_hour_local is null
   or traffic_date_local is null
   or retail_timezone is null
   or event_hour_local is null
   or event_hour_local < 0
   or event_hour_local > 23
   or event_hour_local <> extract(hour from traffic_hour_local)
   or traffic_date_local <> cast(traffic_hour_local as date)
   or retail_timezone <> '{{ var("geopulse_retail_timezone", "Asia/Kolkata") }}'
