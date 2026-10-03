{% set mart = ref('fct_store_cannibalization') %}
{% set forbidden_names = ['device_id', 'event_ts_utc', 'ping_latitude', 'ping_longitude'] %}
{% set exposed = [] %}

{% if execute %}
    {% for column in adapter.get_columns_in_relation(mart) %}
        {% if column.name | lower in forbidden_names %}
            {% do exposed.append(column.name) %}
        {% endif %}
    {% endfor %}
{% endif %}

select 1 as leaked_device_level_column
where {{ exposed | length }} > 0
