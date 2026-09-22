{% if target.name == 'ci' %}

with expected as (
    select 'store_a' as store_id, cast('2026-09-22 08:00:00' as timestamp) as traffic_hour_utc, 2 as unique_visitors, 3 as ping_count
    union all
    select 'store_a', cast('2026-09-22 18:00:00' as timestamp), 3, 3
    union all
    select 'store_b', cast('2026-09-22 08:00:00' as timestamp), 2, 2
),

actual as (
    select store_id, traffic_hour_utc, unique_visitors, ping_count
    from {{ ref('fct_store_hourly_footfall') }}
)

select
    coalesce(expected.store_id, actual.store_id) as store_id,
    coalesce(expected.traffic_hour_utc, actual.traffic_hour_utc) as traffic_hour_utc,
    expected.unique_visitors as expected_unique_visitors,
    actual.unique_visitors as actual_unique_visitors,
    expected.ping_count as expected_ping_count,
    actual.ping_count as actual_ping_count
from expected
full outer join actual
    on expected.store_id = actual.store_id
   and expected.traffic_hour_utc = actual.traffic_hour_utc
where expected.store_id is null
   or actual.store_id is null
   or expected.unique_visitors <> actual.unique_visitors
   or expected.ping_count <> actual.ping_count

{% else %}

select *
from {{ ref('fct_store_hourly_footfall') }}
where 1 = 0

{% endif %}
