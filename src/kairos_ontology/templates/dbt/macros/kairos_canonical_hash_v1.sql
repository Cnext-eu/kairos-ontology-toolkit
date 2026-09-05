-- Kairos canonical hash contract v1 (DD-109)
-- SHA-256 over ordered typed length-delimited fields with an explicit null marker.
-- Text/JSON hash inputs must be contract-validated NFC; SQL does not guess normalization.

{% macro _kairos_canonical_lexical_v1(expression, data_type) -%}
  {%- set kind = data_type.split('(')[0] -%}
  {%- if kind == 'float64' or kind == 'json' -%}
    {{ exceptions.raise_compiler_error(
      "DD-109 canonical hash v1 rejects SQL type " ~ data_type ~
      "; use an exact supported type or canonicalize JSON before Silver"
    ) }}
  {%- elif target.type == 'fabric' -%}
    {%- if kind == 'string' -%}
      CAST({{ expression }} AS VARCHAR(MAX))
    {%- elif kind == 'boolean' -%}
      CASE WHEN {{ expression }} = 1 THEN 'true' ELSE 'false' END
    {%- elif kind in ['int16', 'int32', 'int64'] -%}
      CAST({{ expression }} AS VARCHAR(40))
    {%- elif kind == 'decimal' -%}
      CAST(CAST({{ expression }} AS {{ data_type | upper }}) AS VARCHAR(80))
    {%- elif kind == 'date' -%}
      CONVERT(CHAR(10), CAST({{ expression }} AS DATE), 23)
    {%- elif kind == 'time' -%}
      CONVERT(VARCHAR(16), CAST({{ expression }} AS TIME(6)), 126)
    {%- elif kind == 'timestamp' -%}
      CONCAT(
        CONVERT(VARCHAR(26), CAST({{ expression }} AS DATETIME2(6)), 126),
        'Z'
      )
    {%- elif kind == 'binary' -%}
      LOWER(CONVERT(VARCHAR(MAX), CAST({{ expression }} AS VARBINARY(MAX)), 2))
    {%- else -%}
      {{ exceptions.raise_compiler_error(
        "DD-109 canonical hash v1 does not support type " ~ data_type
      ) }}
    {%- endif -%}
  {%- elif target.type == 'databricks' -%}
    {%- if kind == 'string' -%}
      CAST({{ expression }} AS STRING)
    {%- elif kind == 'boolean' -%}
      CASE WHEN {{ expression }} THEN 'true' ELSE 'false' END
    {%- elif kind in ['int16', 'int32', 'int64'] -%}
      CAST({{ expression }} AS STRING)
    {%- elif kind == 'decimal' -%}
      CAST(CAST({{ expression }} AS {{ data_type | upper }}) AS STRING)
    {%- elif kind == 'date' -%}
      DATE_FORMAT(CAST({{ expression }} AS DATE), 'yyyy-MM-dd')
    {%- elif kind == 'time' -%}
      CAST({{ expression }} AS STRING)
    {%- elif kind == 'timestamp' -%}
      DATE_FORMAT(
        CAST({{ expression }} AS TIMESTAMP),
        'yyyy-MM-dd''T''HH:mm:ss.SSSSSS''Z'''
      )
    {%- elif kind == 'binary' -%}
      LOWER(HEX(CAST({{ expression }} AS BINARY)))
    {%- else -%}
      {{ exceptions.raise_compiler_error(
        "DD-109 canonical hash v1 does not support type " ~ data_type
      ) }}
    {%- endif -%}
  {%- else -%}
    {{ exceptions.raise_compiler_error(
      "DD-109 canonical hash v1 supports only fabric and databricks"
    ) }}
  {%- endif -%}
{%- endmacro %}

{% macro _kairos_canonical_utf8_v1(expression) -%}
  {%- if target.type == 'fabric' -%}
    CONVERT(
      VARBINARY(MAX),
      CAST({{ expression }} AS VARCHAR(MAX))
        COLLATE Latin1_General_100_BIN2_UTF8
    )
  {%- elif target.type == 'databricks' -%}
    ENCODE(CAST({{ expression }} AS STRING), 'UTF-8')
  {%- else -%}
    {{ exceptions.raise_compiler_error(
      "DD-109 canonical hash v1 supports only fabric and databricks"
    ) }}
  {%- endif -%}
{%- endmacro %}

{% macro _kairos_canonical_field_v1(expression, data_type) -%}
  {%- set lexical = _kairos_canonical_lexical_v1(expression, data_type) -%}
  {%- set bytes = _kairos_canonical_utf8_v1(lexical) -%}
  CASE
    WHEN {{ expression }} IS NULL THEN '{{ data_type }}:N:0:;'
    ELSE CONCAT(
      '{{ data_type }}:V:',
      {%- if target.type == 'fabric' %}
      CAST(DATALENGTH({{ bytes }}) AS VARCHAR(20)),
      ':',
      LOWER(CONVERT(VARCHAR(MAX), {{ bytes }}, 2)),
      {%- elif target.type == 'databricks' %}
      CAST(LENGTH({{ bytes }}) AS STRING),
      ':',
      LOWER(HEX({{ bytes }})),
      {%- endif %}
      ';'
    )
  END
{%- endmacro %}

{% macro kairos_canonical_hash_v1(expressions, data_types) -%}
  {%- if expressions | length == 0 or expressions | length != data_types | length -%}
    {{ exceptions.raise_compiler_error(
      "DD-109 canonical hash v1 requires equally sized, non-empty value/type lists"
    ) }}
  {%- endif -%}
  {%- if target.type == 'fabric' -%}
    LOWER(CONVERT(
      VARCHAR(64),
      HASHBYTES(
        'SHA2_256',
        CONVERT(
          VARBINARY(MAX),
          CONCAT(
            'KAIROS-CANONICAL-HASH|v1|'
{%- for expression in expressions %},
            {{ _kairos_canonical_field_v1(
              expression,
              data_types[loop.index0]
            ) }}
{%- endfor %}
          )
        )
      ),
      2
    ))
  {%- elif target.type == 'databricks' -%}
    SHA2(
      ENCODE(
        CONCAT(
          'KAIROS-CANONICAL-HASH|v1|'
{%- for expression in expressions %},
          {{ _kairos_canonical_field_v1(
            expression,
            data_types[loop.index0]
          ) }}
{%- endfor %}
        ),
        'UTF-8'
      ),
      256
    )
  {%- else -%}
    {{ exceptions.raise_compiler_error(
      "DD-109 canonical hash v1 supports only fabric and databricks"
    ) }}
  {%- endif -%}
{%- endmacro %}
