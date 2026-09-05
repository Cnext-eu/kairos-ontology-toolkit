-- Adapter-safe DD-109 runtime expressions.

{% macro kairos_runtime_lookback_floor(timestamp_column, amount, unit) -%}
  {%- if unit not in ['hours', 'days'] -%}
    {{ exceptions.raise_compiler_error(
      "DD-109 lookback unit must be hours or days"
    ) }}
  {%- elif target.type == 'fabric' -%}
    DATEADD(
      {{ 'HOUR' if unit == 'hours' else 'DAY' }},
      -{{ amount }},
      {{ timestamp_column }}
    )
  {%- elif target.type == 'databricks' -%}
    {{ timestamp_column }} - INTERVAL {{ amount }} {{ unit | upper }}
  {%- else -%}
    {{ exceptions.raise_compiler_error(
      "DD-109 runtime supports only fabric and databricks"
    ) }}
  {%- endif -%}
{%- endmacro %}

{% macro kairos_values_distinct(left_value, right_value) -%}
  {%- if target.type == 'fabric' -%}
    (
      {{ left_value }} <> {{ right_value }}
      OR ({{ left_value }} IS NULL AND {{ right_value }} IS NOT NULL)
      OR ({{ left_value }} IS NOT NULL AND {{ right_value }} IS NULL)
    )
  {%- elif target.type == 'databricks' -%}
    NOT ({{ left_value }} <=> {{ right_value }})
  {%- else -%}
    {{ exceptions.raise_compiler_error(
      "DD-109 runtime supports only fabric and databricks"
    ) }}
  {%- endif -%}
{%- endmacro %}
