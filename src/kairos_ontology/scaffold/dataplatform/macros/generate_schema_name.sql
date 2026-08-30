{#
    Custom schema-name override for medallion (bronze/silver/gold) layouts.

    dbt's default generate_schema_name macro concatenates the target's base schema
    with any model-level `+schema:` config (e.g. `dbo_silver` instead of `silver`).
    This override returns the custom schema verbatim so `+schema: silver` /
    `+schema: gold` land in bare `silver` / `gold` schemas as intended.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%}

        {{ default_schema }}

    {%- else -%}

        {{ custom_schema_name | trim }}

    {%- endif -%}

{%- endmacro %}
