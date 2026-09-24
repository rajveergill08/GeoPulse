{% if target.name == 'ci' %}

with expected as (
    select
        'store_a' as existing_store_id,
        'store_b' as candidate_store_id,
        cast('2026-09-22' as date) as traffic_date_utc,
        'morning_commute' as daypart,
        10 as existing_store_unique_visitors,
        4 as candidate_store_unique_visitors,
        3 as shared_visitors,
        1 as incremental_candidate_visitors,
        cast(0.3 as double) as cannibalization_rate,
        cast(0.75 as double) as candidate_overlap_rate,
        cast(0.25 as double) as candidate_incremental_reach_rate
),

actual as (
    select
        existing_store_id,
        candidate_store_id,
        traffic_date_utc,
        daypart,
        existing_store_unique_visitors,
        candidate_store_unique_visitors,
        shared_visitors,
        incremental_candidate_visitors,
        cannibalization_rate,
        candidate_overlap_rate,
        candidate_incremental_reach_rate
    from {{ ref('fct_store_cannibalization') }}
)

select
    coalesce(expected.existing_store_id, actual.existing_store_id) as existing_store_id,
    coalesce(expected.candidate_store_id, actual.candidate_store_id) as candidate_store_id,
    coalesce(expected.traffic_date_utc, actual.traffic_date_utc) as traffic_date_utc,
    coalesce(expected.daypart, actual.daypart) as daypart
from expected
full outer join actual
    on expected.existing_store_id = actual.existing_store_id
   and expected.candidate_store_id = actual.candidate_store_id
   and expected.traffic_date_utc = actual.traffic_date_utc
   and expected.daypart = actual.daypart
where expected.existing_store_id is null
   or actual.existing_store_id is null
   or expected.existing_store_unique_visitors <> actual.existing_store_unique_visitors
   or expected.candidate_store_unique_visitors <> actual.candidate_store_unique_visitors
   or expected.shared_visitors <> actual.shared_visitors
   or expected.incremental_candidate_visitors <> actual.incremental_candidate_visitors
   or expected.cannibalization_rate <> actual.cannibalization_rate
   or expected.candidate_overlap_rate <> actual.candidate_overlap_rate
   or expected.candidate_incremental_reach_rate <> actual.candidate_incremental_reach_rate

{% else %}

select *
from {{ ref('fct_store_cannibalization') }}
where 1 = 0

{% endif %}
