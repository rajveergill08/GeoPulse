with pair_overlap as (
    select *
    from {{ ref('int_store_pair_daypart_overlap') }}
)

select
    concat(
        existing_store_id,
        '|',
        candidate_store_id,
        '|',
        cast(traffic_date_utc as varchar),
        '|',
        daypart
    ) as store_pair_daypart_key,
    existing_store_id,
    existing_store_name,
    candidate_store_id,
    candidate_store_name,
    candidate_store_status,
    traffic_date_utc,
    daypart,
    existing_store_unique_visitors,
    candidate_store_unique_visitors,
    shared_visitors,
    candidate_store_unique_visitors - shared_visitors as incremental_candidate_visitors,
    round(
        cast(shared_visitors as double)
        / nullif(existing_store_unique_visitors, 0),
        6
    ) as cannibalization_rate,
    round(
        cast(shared_visitors as double)
        / nullif(candidate_store_unique_visitors, 0),
        6
    ) as candidate_overlap_rate,
    round(
        cast(candidate_store_unique_visitors - shared_visitors as double)
        / nullif(candidate_store_unique_visitors, 0),
        6
    ) as candidate_incremental_reach_rate
from pair_overlap
