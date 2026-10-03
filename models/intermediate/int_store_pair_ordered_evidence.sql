with device_visits as (
    select *
    from {{ ref('int_store_device_daypart_visits') }}
),

shared_devices as (
    select
        existing.device_id,
        existing.store_id as existing_store_id,
        candidate.store_id as candidate_store_id,
        existing.traffic_date_local,
        existing.daypart
    from device_visits as existing
    inner join device_visits as candidate
        on existing.device_id = candidate.device_id
       and existing.traffic_date_local = candidate.traffic_date_local
       and existing.daypart = candidate.daypart
    where existing.store_status = 'existing'
      and candidate.store_status in ('proposed', 'candidate')
      and existing.store_id <> candidate.store_id
),

localized_matches as (
    select
        device_id,
        store_id,
        event_ts_utc,
        {{ utc_to_retail_local('event_ts_utc') }} as event_ts_local
    from {{ ref('stg_ping_store_matches') }}
),

classified_matches as (
    select
        device_id,
        store_id,
        event_ts_utc,
        cast(event_ts_local as date) as traffic_date_local,
        {{ traffic_daypart('event_ts_local') }} as daypart
    from localized_matches
),

pair_ping_flags as (
    select
        shared.device_id,
        shared.existing_store_id,
        shared.candidate_store_id,
        shared.traffic_date_local,
        shared.daypart,
        matches.event_ts_utc,
        max(case when matches.store_id = shared.existing_store_id then 1 else 0 end)
            as at_existing,
        max(case when matches.store_id = shared.candidate_store_id then 1 else 0 end)
            as at_candidate
    from shared_devices as shared
    inner join classified_matches as matches
        on shared.device_id = matches.device_id
       and shared.traffic_date_local = matches.traffic_date_local
       and shared.daypart = matches.daypart
       and matches.store_id in (shared.existing_store_id, shared.candidate_store_id)
    group by
        shared.device_id,
        shared.existing_store_id,
        shared.candidate_store_id,
        shared.traffic_date_local,
        shared.daypart,
        matches.event_ts_utc
),

device_sequence as (
    select
        shared.device_id,
        shared.existing_store_id,
        shared.candidate_store_id,
        shared.traffic_date_local,
        shared.daypart,
        min(
            case when flags.at_candidate = 1 and flags.at_existing = 0
                then flags.event_ts_utc end
        ) as first_candidate_only_ts_utc,
        max(
            case when flags.at_existing = 1 and flags.at_candidate = 0
                then flags.event_ts_utc end
        ) as last_existing_only_ts_utc
    from shared_devices as shared
    left join pair_ping_flags as flags
        on shared.device_id = flags.device_id
       and shared.existing_store_id = flags.existing_store_id
       and shared.candidate_store_id = flags.candidate_store_id
       and shared.traffic_date_local = flags.traffic_date_local
       and shared.daypart = flags.daypart
    group by
        shared.device_id,
        shared.existing_store_id,
        shared.candidate_store_id,
        shared.traffic_date_local,
        shared.daypart
)

select
    existing_store_id,
    candidate_store_id,
    traffic_date_local,
    daypart,
    sum(
        case when first_candidate_only_ts_utc < last_existing_only_ts_utc
            then 1 else 0 end
    ) as ordered_candidate_to_existing_visitors
from device_sequence
group by
    existing_store_id,
    candidate_store_id,
    traffic_date_local,
    daypart
