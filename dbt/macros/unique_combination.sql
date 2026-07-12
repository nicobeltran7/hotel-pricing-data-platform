{% test dbt_utils_unique_combination_stub(model, combination_of) %}
{#- Composite-key uniqueness test. Named after the dbt_utils equivalent;
    implemented locally to keep the project dependency-free. -#}

select {{ combination_of | join(', ') }}, count(*) as n
from {{ model }}
group by {{ combination_of | join(', ') }}
having count(*) > 1

{% endtest %}
