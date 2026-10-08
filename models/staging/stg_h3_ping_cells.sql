with source_pings as (
    select *
    from {{ source('raw', 'mobile_pings') }}
)

select
    trim(cast(device_id as varchar)) as device_id,
    {% if target.type == 'snowflake' %}
        -- The raw column is TIMESTAMP_TZ. Normalize its instant to UTC before
        -- passing a timezone-free timestamp to the shared retail-clock macro.
        cast(convert_timezone('UTC', event_ts) as timestamp_ntz) as event_ts_utc,
        lower(h3_point_to_cell_string(location, 8)) as hex_id
    {% elif target.type == 'duckdb' %}
        cast(event_ts as timestamp) as event_ts_utc,
        lower(trim(cast(hex_id as varchar))) as hex_id
    {% else %}
        {{ exceptions.raise_compiler_error('H3 staging does not support adapter type ' ~ target.type) }}
    {% endif %}
from source_pings
where device_id is not null
  and nullif(trim(cast(device_id as varchar)), '') is not null
  and event_ts is not null
  {% if target.type == 'snowflake' %}
      and location is not null
  {% else %}
      and hex_id is not null
  {% endif %}
