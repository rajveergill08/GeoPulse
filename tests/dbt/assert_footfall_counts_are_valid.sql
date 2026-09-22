select *
from {{ ref('fct_store_hourly_footfall') }}
where unique_visitors < 0
   or ping_count < 0
   or unique_visitors > ping_count
