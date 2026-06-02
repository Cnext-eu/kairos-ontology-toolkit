{# extract_source_schema.sql — dbt macro for bronze schema introspection #}
{# This macro uses dbt's adapter layer to introspect declared source tables #}
{# and outputs a YAML-formatted schema file for the kairos-ontology toolkit. #}
{#                                                                            #}
{# NOTE: For full metadata (samples, JSON detection, row counts), use the     #}
{# kairos-ontology extract-schema CLI command instead. This macro is a        #}
{# lightweight fallback that only captures column names and data types.       #}
{#                                                                            #}
{# Usage:                                                                     #}
{#   dbt run-operation extract_source_schema --args '{source_name: "myapp"}'  #}
{#                                                                            #}
{# The output is printed to stdout. Redirect to a file:                       #}
{#   dbt run-operation extract_source_schema \                                #}
{#     --args '{source_name: "myapp"}' 2>/dev/null > schema.yaml              #}

{% macro extract_source_schema(source_name) %}
    {# Retrieve all sources matching the given name #}
    {% set source_nodes = [] %}
    {% for node in graph.sources.values() %}
        {% if node.source_name == source_name %}
            {% do source_nodes.append(node) %}
        {% endif %}
    {% endfor %}

    {% if source_nodes | length == 0 %}
        {{ exceptions.raise_compiler_error(
            "No source found with name '" ~ source_name ~ "'. "
            "Ensure it is defined in a _sources.yml file."
        ) }}
    {% endif %}

    {# Determine metadata from first node #}
    {% set first_node = source_nodes[0] %}
    {% set db_name = first_node.database or target.database %}
    {% set schema_name = first_node.schema or target.schema %}

    {# Detect platform from adapter type #}
    {% set adapter_type = adapter.type() %}
    {% set platform_map = {
        'fabric': 'fabric-warehouse',
        'spark': 'fabric-lakehouse',
        'databricks': 'databricks',
        'snowflake': 'snowflake',
        'postgres': 'postgres'
    } %}
    {% set platform = platform_map.get(adapter_type, 'unknown') %}

    {# Print YAML header #}
    {{ print('version: "1.0"') }}
    {{ print('system: "' ~ source_name ~ '"') }}
    {{ print('platform: "' ~ platform ~ '"') }}
    {{ print('environment: "' ~ target.name ~ '"') }}
    {{ print('extracted_at: "' ~ modules.datetime.datetime.now(modules.datetime.timezone.utc).isoformat() ~ '"') }}
    {{ print('connection:') }}
    {{ print('  database: "' ~ db_name ~ '"') }}
    {{ print('  schema: "' ~ schema_name ~ '"') }}
    {{ print('') }}
    {{ print('tables:') }}

    {# Iterate over each source table and introspect columns #}
    {% for node in source_nodes %}
        {% set relation = source(source_name, node.name) %}
        {% set columns = adapter.get_columns_in_relation(relation) %}

        {{ print('  - name: "' ~ node.name ~ '"') }}
        {{ print('    columns:') }}

        {% for col in columns %}
            {{ print('      - name: "' ~ col.name ~ '"') }}
            {{ print('        data_type: "' ~ col.data_type ~ '"') }}
            {# nullable and is_primary_key may not be available on all adapters #}
            {# Users should annotate these manually if needed #}
        {% endfor %}
    {% endfor %}

{% endmacro %}
