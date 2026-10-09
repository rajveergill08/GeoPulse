{% if target.type == 'duckdb' %}
with expected as (
    select '8861892e9bfffff' as hex_id, cast('2026-09-22' as date) as traffic_date_local,
           8 as event_hour_local, 3 as unique_visitors, 4 as ping_count
    union all
    select '88618925a7fffff', cast('2026-09-22' as date), 8, 8, 8
    union all
    select '8861892ec3fffff', cast('2026-09-22' as date), 8, 4, 4
    union all
    select '8861892e9bfffff', cast('2026-09-22' as date), 18, 2, 2
    union all
    select '88618925a7fffff', cast('2026-09-22' as date), 18, 1, 1
    union all
    select '8861892e9dfffff', cast('2026-09-22' as date), 23, 1, 1
    union all
    select '8861892e9dfffff', cast('2026-09-23' as date), 0, 1, 1
),
actual as (
    select hex_id, traffic_date_local, event_hour_local, unique_visitors, ping_count
    from {{ ref('fct_h3_hourly_footfall') }}
)

(select * from actual except select * from expected)
union all
(select * from expected except select * from actual)
{% else %}
select * from {{ ref('fct_h3_hourly_footfall') }} where 1 = 0
{% endif %}
