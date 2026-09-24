{% macro traffic_daypart(timestamp_expression) -%}
case
    when extract(hour from {{ timestamp_expression }}) between 5 and 9 then 'morning_commute'
    when extract(hour from {{ timestamp_expression }}) between 10 and 15 then 'midday'
    when extract(hour from {{ timestamp_expression }}) between 16 and 19 then 'evening_commute'
    else 'off_peak'
end
{%- endmacro %}
