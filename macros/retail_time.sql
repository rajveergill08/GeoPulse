{% macro utc_to_retail_local(timestamp_expression) -%}
    {% set retail_timezone = var('geopulse_retail_timezone', 'Asia/Kolkata') %}
    {% if target.type == 'snowflake' -%}
        convert_timezone(
            'UTC',
            '{{ retail_timezone }}',
            cast({{ timestamp_expression }} as timestamp_ntz)
        )
    {%- elif target.type == 'duckdb' -%}
        timezone(
            '{{ retail_timezone }}',
            timezone('UTC', cast({{ timestamp_expression }} as timestamp))
        )
    {%- else -%}
        {{ exceptions.raise_compiler_error(
            "utc_to_retail_local does not support adapter type " ~ target.type
        ) }}
    {%- endif %}
{%- endmacro %}
