select
    existing_store_id,
    candidate_store_id,
    traffic_date_local,
    daypart
from {{ ref('int_store_pair_ordered_evidence') }}
group by
    existing_store_id,
    candidate_store_id,
    traffic_date_local,
    daypart
having count(*) <> 1
