{# print_query.sql — execute arbitrary SQL and print results to stdout #}
{# Use for ad-hoc schema discovery (e.g., listing schemas or tables).  #}
{#                                                                      #}
{# Usage:                                                               #}
{#   dbt run-operation print_query \                                    #}
{#     --args '{sql: "SELECT table_schema FROM INFORMATION_SCHEMA.TABLES"}' #}
{#     --profiles-dir .dbt                                              #}

{% macro print_query(sql) %}
    {% set results = run_query(sql) %}
    {% if results %}
        {% for row in results.rows %}
            {{ print(row.values() | join(' | ')) }}
        {% endfor %}
    {% else %}
        {{ print('(no results)') }}
    {% endif %}
{% endmacro %}
