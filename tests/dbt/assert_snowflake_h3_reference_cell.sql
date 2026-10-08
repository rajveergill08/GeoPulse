{% if target.type == 'snowflake' %}
-- Snowflake's documented Brandenburg Gate example; checks native H3 execution,
-- whereas DuckDB CI only tests aggregation over already indexed synthetic pings.
with reference_cell as (
    select h3_point_to_cell_string(st_point(13.377704, 52.516262), 8) as observed_hex_id
)
select * from reference_cell
where lower(observed_hex_id) != '881f1d4887fffff'
{% else %}
select 1 as not_applicable where 1 = 0
{% endif %}
