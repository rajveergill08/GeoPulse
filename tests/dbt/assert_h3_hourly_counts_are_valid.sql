select *
from {{ ref('fct_h3_hourly_footfall') }}
where unique_visitors < 0
   or ping_count < 0
   or unique_visitors > ping_count
   or event_hour_local < 0
   or event_hour_local > 23
   or traffic_date_local != cast(traffic_hour_local as date)
   or h3_resolution != 8
