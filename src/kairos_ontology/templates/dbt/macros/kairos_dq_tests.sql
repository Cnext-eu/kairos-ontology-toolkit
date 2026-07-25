-- DD-115 toolkit-owned DQ evaluators. Execution and monitoring remain downstream.

{% macro kairos_dq_text_type() %}
  {%- if target.type in ('fabric', 'sqlserver') -%}
    VARCHAR(8000)
  {%- elif target.type in ('databricks', 'spark') -%}
    STRING
  {%- else -%}
    {{ exceptions.raise_compiler_error(
      "DD-115 DQ tests support only Fabric and Databricks"
    ) }}
  {%- endif -%}
{% endmacro %}

{% macro kairos_dq_float_type() %}
  {%- if target.type in ('fabric', 'sqlserver') -%}FLOAT
  {%- else -%}DOUBLE
  {%- endif -%}
{% endmacro %}

{% macro kairos_dq_contract_shape(model, tolerance, required_columns) %}
with metrics as (
    select
        count(*) as total_count,
        sum(case when
{%- for column in required_columns %}
            {{ adapter.quote(column) }} is null{% if not loop.last %} or{% endif %}
{%- endfor %}
            then 1 else 0 end) as affected_count
    from {{ model }}
)
select
    case when affected_count > {{ tolerance }} then 'fail' else 'pass' end as status,
    cast(affected_count as {{ kairos_dq_text_type() }}) as observed_value,
    affected_count,
    cast(null as {{ kairos_dq_text_type() }}) as reconciliation_values
from metrics
{% endmacro %}

{% macro kairos_dq_freshness(model, tolerance, column, unit) %}
{%- set divisor = {
    'seconds': 1,
    'minutes': 60,
    'hours': 3600,
    'days': 86400
  }[unit] %}
with observed as (
    select max({{ adapter.quote(column) }}) as newest_value
    from {{ model }}
),
metrics as (
    select
        newest_value,
{%- if target.type in ('fabric', 'sqlserver') %}
        cast(datediff(second, newest_value, {{ kairos_current_timestamp() }})
          as {{ kairos_dq_float_type() }}) / {{ divisor }} as observed_age
{%- elif target.type in ('databricks', 'spark') %}
        cast(timestampdiff(
          SECOND, newest_value, {{ kairos_current_timestamp() }}
        ) as {{ kairos_dq_float_type() }}) / {{ divisor }} as observed_age
{%- else %}
        {{ exceptions.raise_compiler_error(
          "DD-115 freshness supports only Fabric and Databricks"
        ) }}
{%- endif %}
    from observed
)
select
    case
        when newest_value is null then 'not-evaluated'
        when observed_age > {{ tolerance }} then 'fail'
        else 'pass'
    end as status,
    cast(observed_age as {{ kairos_dq_text_type() }}) as observed_value,
    cast(null as bigint) as affected_count,
    cast(null as {{ kairos_dq_text_type() }}) as reconciliation_values
from metrics
{% endmacro %}

{% macro kairos_dq_volume(model, tolerance) %}
with metrics as (
    select count(*) as observed_count
    from {{ model }}
)
select
    case when observed_count < {{ tolerance }} then 'fail' else 'pass' end as status,
    cast(observed_count as {{ kairos_dq_text_type() }}) as observed_value,
    case when observed_count < {{ tolerance }} then observed_count else 0 end
      as affected_count,
    cast(null as {{ kairos_dq_text_type() }}) as reconciliation_values
from metrics
{% endmacro %}

{% macro kairos_dq_duplicate_rate(model, tolerance, columns) %}
with grouped as (
    select
{%- for column in columns %}
        {{ adapter.quote(column) }}{% if not loop.last %},{% endif %}
{%- endfor %},
        count(*) as group_count
    from {{ model }}
    group by
{%- for column in columns %}
        {{ adapter.quote(column) }}{% if not loop.last %},{% endif %}
{%- endfor %}
),
metrics as (
    select
        (select count(*) from {{ model }}) as total_count,
        coalesce(sum(case when group_count > 1 then group_count else 0 end), 0)
          as affected_count
    from grouped
),
observed as (
    select
        total_count,
        affected_count,
        case when total_count = 0 then null
             else cast(affected_count as {{ kairos_dq_float_type() }})
                  / total_count end as observed_rate
    from metrics
)
select
    case
        when total_count = 0 then 'not-evaluated'
        when observed_rate > {{ tolerance }} then 'fail'
        else 'pass'
    end as status,
    cast(observed_rate as {{ kairos_dq_text_type() }}) as observed_value,
    affected_count,
    cast(null as {{ kairos_dq_text_type() }}) as reconciliation_values
from observed
{% endmacro %}

{% macro kairos_dq_range(model, tolerance, column, minimum=none, maximum=none) %}
with metrics as (
    select
        count(*) as total_count,
        sum(case when
{%- if minimum is not none %}
            {{ adapter.quote(column) }} < {{ minimum }}
{%- endif %}
{%- if minimum is not none and maximum is not none %} or{% endif %}
{%- if maximum is not none %}
            {{ adapter.quote(column) }} > {{ maximum }}
{%- endif %}
            then 1 else 0 end) as affected_count
    from {{ model }}
),
observed as (
    select
        total_count,
        affected_count,
        case when total_count = 0 then null
             else cast(affected_count as {{ kairos_dq_float_type() }})
                  / total_count end as observed_rate
    from metrics
)
select
    case
        when total_count = 0 then 'not-evaluated'
        when observed_rate > {{ tolerance }} then 'fail'
        else 'pass'
    end as status,
    cast(observed_rate as {{ kairos_dq_text_type() }}) as observed_value,
    affected_count,
    cast(null as {{ kairos_dq_text_type() }}) as reconciliation_values
from observed
{% endmacro %}

{% macro kairos_dq_distribution(model, tolerance, column, allowed_values) %}
with metrics as (
    select
        count(*) as total_count,
        sum(case when {{ adapter.quote(column) }} is null
{%- if allowed_values %}
              or {{ adapter.quote(column) }} not in (
{%- for value in allowed_values %}
                  '{{ value | replace("'", "''") }}'{% if not loop.last %},{% endif %}
{%- endfor %}
              )
{%- endif %}
            then 1 else 0 end) as affected_count
    from {{ model }}
),
observed as (
    select
        total_count,
        affected_count,
        case when total_count = 0 then null
             else cast(affected_count as {{ kairos_dq_float_type() }})
                  / total_count end as observed_rate
    from metrics
)
select
    case
        when total_count = 0 then 'not-evaluated'
        when observed_rate > {{ tolerance }} then 'fail'
        else 'pass'
    end as status,
    cast(observed_rate as {{ kairos_dq_text_type() }}) as observed_value,
    affected_count,
    cast(null as {{ kairos_dq_text_type() }}) as reconciliation_values
from observed
{% endmacro %}

{% macro kairos_dq_reconciliation(
    model,
    tolerance,
    compare_model,
    metric,
    column=none,
    compare_column=none
) %}
with source_metric as (
    select
{%- if metric == 'count' %}
        count(*) as metric_value
{%- else %}
        coalesce(sum({{ adapter.quote(column) }}), 0) as metric_value
{%- endif %}
    from {{ model }}
),
comparison_metric as (
    select
{%- if metric == 'count' %}
        count(*) as metric_value
{%- else %}
        coalesce(sum({{ adapter.quote(compare_column) }}), 0) as metric_value
{%- endif %}
    from {{ compare_model }}
),
observed as (
    select
        source.metric_value as source_value,
        comparison.metric_value as comparison_value,
        abs(source.metric_value - comparison.metric_value) as observed_difference
    from source_metric source
    cross join comparison_metric comparison
)
select
    case when observed_difference > {{ tolerance }} then 'fail' else 'pass' end
      as status,
    cast(observed_difference as {{ kairos_dq_text_type() }}) as observed_value,
    cast(null as bigint) as affected_count,
    concat(
      'source=', cast(source_value as {{ kairos_dq_text_type() }}),
      '|comparison=', cast(comparison_value as {{ kairos_dq_text_type() }})
    ) as reconciliation_values
from observed
{% endmacro %}

{% macro kairos_dq_referential_coverage(
    model,
    tolerance,
    column,
    parent_model,
    parent_column
) %}
with metrics as (
    select
        count(*) as total_count,
        sum(case when child.{{ adapter.quote(column) }} is null
                  or parent.{{ adapter.quote(parent_column) }} is null
                 then 1 else 0 end) as affected_count
    from {{ model }} child
    left join {{ parent_model }} parent
      on parent.{{ adapter.quote(parent_column) }}
       = child.{{ adapter.quote(column) }}
),
observed as (
    select
        total_count,
        affected_count,
        case when total_count = 0 then null
             else cast(affected_count as {{ kairos_dq_float_type() }})
                  / total_count end as observed_rate
    from metrics
)
select
    case
        when total_count = 0 then 'not-evaluated'
        when observed_rate > {{ tolerance }} then 'fail'
        else 'pass'
    end as status,
    cast(observed_rate as {{ kairos_dq_text_type() }}) as observed_value,
    affected_count,
    cast(null as {{ kairos_dq_text_type() }}) as reconciliation_values
from observed
{% endmacro %}

{% macro kairos_dq_cross_field(model, tolerance, left, operator, right) %}
with metrics as (
    select
        count(*) as total_count,
        sum(case when
{%- if operator == 'eq' %}
            not (
              {{ adapter.quote(left) }} = {{ adapter.quote(right) }}
              or (
                {{ adapter.quote(left) }} is null
                and {{ adapter.quote(right) }} is null
              )
            )
{%- elif operator == 'ne' %}
            (
              {{ adapter.quote(left) }} = {{ adapter.quote(right) }}
              or (
                {{ adapter.quote(left) }} is null
                and {{ adapter.quote(right) }} is null
              )
            )
{%- else %}
            {{ adapter.quote(left) }} is null
            or {{ adapter.quote(right) }} is null
            or not (
              {{ adapter.quote(left) }}
              {% if operator == 'lt' %}<{% elif operator == 'lte' %}<={% elif operator == 'gt' %}>{% else %}>={% endif %}
              {{ adapter.quote(right) }}
            )
{%- endif %}
            then 1 else 0 end) as affected_count
    from {{ model }}
),
observed as (
    select
        total_count,
        affected_count,
        case when total_count = 0 then null
             else cast(affected_count as {{ kairos_dq_float_type() }})
                  / total_count end as observed_rate
    from metrics
)
select
    case
        when total_count = 0 then 'not-evaluated'
        when observed_rate > {{ tolerance }} then 'fail'
        else 'pass'
    end as status,
    cast(observed_rate as {{ kairos_dq_text_type() }}) as observed_value,
    affected_count,
    cast(null as {{ kairos_dq_text_type() }}) as reconciliation_values
from observed
{% endmacro %}
