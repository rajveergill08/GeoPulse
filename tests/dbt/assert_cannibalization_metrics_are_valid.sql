select *
from {{ ref('fct_store_cannibalization') }}
where existing_store_unique_visitors <= 0
   or candidate_store_unique_visitors <= 0
   or shared_visitors < 0
   or shared_visitors > existing_store_unique_visitors
   or shared_visitors > candidate_store_unique_visitors
   or ordered_candidate_to_existing_visitors < 0
   or ordered_candidate_to_existing_visitors > shared_visitors
   or incremental_candidate_visitors < 0
   or cannibalization_rate < 0
   or cannibalization_rate > 1
   or candidate_overlap_rate < 0
   or candidate_overlap_rate > 1
   or candidate_incremental_reach_rate < 0
   or candidate_incremental_reach_rate > 1
   or abs(candidate_overlap_rate + candidate_incremental_reach_rate - 1) > 0.000001
