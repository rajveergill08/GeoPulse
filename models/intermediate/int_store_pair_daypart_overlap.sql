with device_visits as (
    select *
    from {{ ref('int_store_device_daypart_visits') }}
),

store_daypart_totals as (
    select
        store_id,
        max(store_name) as store_name,
        max(store_status) as store_status,
        traffic_date_utc,
        daypart,
        count(*) as unique_visitors
    from device_visits
    group by store_id, traffic_date_utc, daypart
),

eligible_store_pairs as (
    select
        existing.store_id as existing_store_id,
        existing.store_name as existing_store_name,
        candidate.store_id as candidate_store_id,
        candidate.store_name as candidate_store_name,
        candidate.store_status as candidate_store_status,
        existing.traffic_date_utc,
        existing.daypart,
        existing.unique_visitors as existing_store_unique_visitors,
        candidate.unique_visitors as candidate_store_unique_visitors
    from store_daypart_totals as existing
    inner join store_daypart_totals as candidate
        on existing.traffic_date_utc = candidate.traffic_date_utc
       and existing.daypart = candidate.daypart
    where existing.store_status = 'existing'
      and candidate.store_status in ('proposed', 'candidate')
      and existing.store_id <> candidate.store_id
),

shared_visitors as (
    select
        existing.store_id as existing_store_id,
        candidate.store_id as candidate_store_id,
        existing.traffic_date_utc,
        existing.daypart,
        count(distinct existing.device_id) as shared_visitors
    from device_visits as existing
    inner join device_visits as candidate
        on existing.device_id = candidate.device_id
       and existing.traffic_date_utc = candidate.traffic_date_utc
       and existing.daypart = candidate.daypart
    where existing.store_status = 'existing'
      and candidate.store_status in ('proposed', 'candidate')
      and existing.store_id <> candidate.store_id
    group by
        existing.store_id,
        candidate.store_id,
        existing.traffic_date_utc,
        existing.daypart
)

select
    pairs.existing_store_id,
    pairs.existing_store_name,
    pairs.candidate_store_id,
    pairs.candidate_store_name,
    pairs.candidate_store_status,
    pairs.traffic_date_utc,
    pairs.daypart,
    pairs.existing_store_unique_visitors,
    pairs.candidate_store_unique_visitors,
    coalesce(overlap.shared_visitors, 0) as shared_visitors
from eligible_store_pairs as pairs
left join shared_visitors as overlap
    on pairs.existing_store_id = overlap.existing_store_id
   and pairs.candidate_store_id = overlap.candidate_store_id
   and pairs.traffic_date_utc = overlap.traffic_date_utc
   and pairs.daypart = overlap.daypart
