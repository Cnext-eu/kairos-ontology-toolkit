# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""dbt Projector — generate a dbt Core project from ontology + source vocabulary + SKOS mappings.

Generates a complete dbt project with:

1. **Sources** — minimal ``_sources.yml`` per source system (under ``models/silver/``)
2. **Silver models** — ``{entity}.sql`` per domain class (reads directly from bronze
   via ``{{ source() }}``, applies mapping transforms inline)
3. **Schema YAML** — ``_models.yml`` with column descriptions + SHACL-derived tests
4. **Project config** — ``dbt_project.yml`` + ``packages.yml``
5. **Gold models** — ``dim_{entity}.sql`` / ``fact_{entity}.sql`` (optional)

There is **no staging layer** — silver is the first dbt layer and reads directly
from bronze tables managed by the data platform.  The vocabulary TTL in
``integration/sources/`` is the authoritative contract for bronze table structure.

Bronze source systems are described using the ``kairos-bronze:`` vocabulary.
Column mappings use SKOS (``skos:exactMatch``, ``skos:closeMatch``, etc.)
with ``kairos-map:`` technical annotations for SQL transforms.

Namespace:  kairos-bronze:  https://kairos.cnext.eu/bronze#
Namespace:  kairos-map:     https://kairos.cnext.eu/mapping#
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef, XSD, RDFS, SKOS
from rdflib.namespace import OWL, RDF
from jinja2 import Environment, FileSystemLoader

from .uri_utils import camel_to_snake, extract_local_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

# ---------------------------------------------------------------------------
# Source-type → target SQL type mappings (per platform)
# ---------------------------------------------------------------------------

# Microsoft Fabric Warehouse types (VARCHAR-only, no NVARCHAR)
_SOURCE_TO_FABRIC: dict[str, str] = {
    "int": "INT",
    "bigint": "BIGINT",
    "smallint": "SMALLINT",
    "tinyint": "SMALLINT",
    "bit": "BIT",
    "decimal": "DECIMAL(18,4)",
    "numeric": "DECIMAL(18,4)",
    "float": "FLOAT",
    "real": "REAL",
    "money": "DECIMAL(18,4)",
    "datetime": "DATETIME2",
    "datetime2": "DATETIME2",
    "date": "DATE",
    "time": "TIME",
    "char": "VARCHAR(255)",
    "varchar": "VARCHAR(8000)",
    "nchar": "VARCHAR(255)",
    "nvarchar": "VARCHAR(8000)",
    "text": "VARCHAR(8000)",
    "ntext": "VARCHAR(8000)",
    "uniqueidentifier": "VARCHAR(36)",
    "binary": "VARBINARY(8000)",
    "varbinary": "VARBINARY(8000)",
    "image": "VARBINARY(8000)",
    "xml": "VARCHAR(8000)",
}

# Databricks (Spark SQL) types — for dbt-databricks / dbt-spark adapters
_SOURCE_TO_DATABRICKS: dict[str, str] = {
    "int": "INT",
    "bigint": "BIGINT",
    "smallint": "SMALLINT",
    "tinyint": "SMALLINT",
    "bit": "BOOLEAN",
    "decimal": "DECIMAL(18,4)",
    "numeric": "DECIMAL(18,4)",
    "float": "DOUBLE",
    "real": "DOUBLE",
    "money": "DECIMAL(18,4)",
    "datetime": "TIMESTAMP",
    "datetime2": "TIMESTAMP",
    "date": "DATE",
    "time": "STRING",
    "char": "STRING",
    "varchar": "STRING",
    "nchar": "STRING",
    "nvarchar": "STRING",
    "text": "STRING",
    "ntext": "STRING",
    "uniqueidentifier": "STRING",
    "binary": "BINARY",
    "varbinary": "BINARY",
    "image": "BINARY",
    "xml": "STRING",
}

# XSD → Fabric Warehouse type mapping (for silver columns from ontology)
_XSD_TO_FABRIC: dict[str, str] = {
    str(XSD.string): "VARCHAR(255)",
    str(XSD.normalizedString): "VARCHAR(255)",
    str(XSD.token): "VARCHAR(255)",
    str(XSD.integer): "BIGINT",
    str(XSD.int): "INT",
    str(XSD.long): "BIGINT",
    str(XSD.short): "SMALLINT",
    str(XSD.decimal): "DECIMAL(18,4)",
    str(XSD.float): "FLOAT",
    str(XSD.double): "FLOAT",
    str(XSD.boolean): "BIT",
    str(XSD.date): "DATE",
    str(XSD.dateTime): "DATETIME2",
    str(XSD.time): "TIME",
    str(XSD.gYear): "INT",
    str(XSD.anyURI): "VARCHAR(2048)",
}

# XSD → Databricks (Spark SQL) types
_XSD_TO_DATABRICKS: dict[str, str] = {
    str(XSD.string): "STRING",
    str(XSD.normalizedString): "STRING",
    str(XSD.token): "STRING",
    str(XSD.integer): "BIGINT",
    str(XSD.int): "INT",
    str(XSD.long): "BIGINT",
    str(XSD.short): "SMALLINT",
    str(XSD.decimal): "DECIMAL(18,4)",
    str(XSD.float): "DOUBLE",
    str(XSD.double): "DOUBLE",
    str(XSD.boolean): "BOOLEAN",
    str(XSD.date): "DATE",
    str(XSD.dateTime): "TIMESTAMP",
    str(XSD.time): "STRING",
    str(XSD.gYear): "INT",
    str(XSD.anyURI): "STRING",
}

# Platform selection: maps platform name to (source_type_map, xsd_type_map)
_PLATFORM_TYPE_MAPS: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "fabric": (_SOURCE_TO_FABRIC, _XSD_TO_FABRIC),
    "databricks": (_SOURCE_TO_DATABRICKS, _XSD_TO_DATABRICKS),
    "spark": (_SOURCE_TO_DATABRICKS, _XSD_TO_DATABRICKS),  # alias for backcompat
}

# Default platform — valid values: "fabric", "databricks"
DEFAULT_PLATFORM = "fabric"

# SHACL namespace
SH = Namespace("http://www.w3.org/ns/shacl#")


def _camel_to_snake(name: str) -> str:
    """Convert PascalCase / camelCase to snake_case."""
    return camel_to_snake(name)


def _source_type_to_databricks(src_type: str) -> str:
    """Map a source system data type string to Databricks (Spark SQL) type."""
    base = re.sub(r"\(.*\)", "", src_type.strip().lower())
    return _SOURCE_TO_DATABRICKS.get(base, "STRING")


def _source_type_to_target(src_type: str, platform: str = DEFAULT_PLATFORM) -> str:
    """Map a source system data type string to the target platform SQL type."""
    base = re.sub(r"\(.*\)", "", src_type.strip().lower())
    source_map, _ = _PLATFORM_TYPE_MAPS.get(platform, _PLATFORM_TYPE_MAPS[DEFAULT_PLATFORM])
    return source_map.get(base, "VARCHAR(255)")


def _xsd_to_target(range_uri, platform: str = DEFAULT_PLATFORM) -> str:
    """Map an XSD range URI to the target platform SQL type."""
    _, xsd_map = _PLATFORM_TYPE_MAPS.get(platform, _PLATFORM_TYPE_MAPS[DEFAULT_PLATFORM])
    return xsd_map.get(str(range_uri), "VARCHAR(255)") if range_uri else "VARCHAR(255)"


# ---------------------------------------------------------------------------
# dbt_utils macro-based type references (for portable silver/gold models)
# ---------------------------------------------------------------------------

_XSD_TO_DBT_MACRO: dict[str, str] = {
    str(XSD.string): "{{ dbt_utils.type_string() }}",
    str(XSD.normalizedString): "{{ dbt_utils.type_string() }}",
    str(XSD.token): "{{ dbt_utils.type_string() }}",
    str(XSD.integer): "{{ dbt_utils.type_int() }}",
    str(XSD.int): "{{ dbt_utils.type_int() }}",
    str(XSD.long): "{{ dbt_utils.type_int() }}",
    str(XSD.short): "{{ dbt_utils.type_int() }}",
    str(XSD.decimal): "DECIMAL(18,4)",  # no dbt_utils macro for decimal
    str(XSD.float): "{{ dbt_utils.type_float() }}",
    str(XSD.double): "{{ dbt_utils.type_float() }}",
    str(XSD.boolean): "{{ dbt_utils.type_boolean() }}",
    str(XSD.date): "DATE",  # DATE is universal
    str(XSD.dateTime): "{{ dbt_utils.type_timestamp() }}",
    str(XSD.time): "{{ dbt_utils.type_string() }}",
    str(XSD.gYear): "{{ dbt_utils.type_int() }}",
    str(XSD.anyURI): "{{ dbt_utils.type_string() }}",
}


def _xsd_to_dbt_macro(range_uri) -> str:
    """Map an XSD range URI to a dbt_utils macro expression (platform-portable)."""
    if not range_uri:
        return "{{ dbt_utils.type_string() }}"
    return _XSD_TO_DBT_MACRO.get(str(range_uri), "{{ dbt_utils.type_string() }}")


# ---------------------------------------------------------------------------
# Bronze TTL parser
# ---------------------------------------------------------------------------

def _parse_bronze(sources_dir: Path) -> list[dict]:
    """Parse source vocabulary TTL files from *sources_dir* and return source system metadata.

    Scans ``integration/sources/<system>/*.ttl`` (including ``*.vocabulary.ttl``)
    recursively, looking for ``kairos-bronze:SourceSystem`` instances.

    Returns a list of dicts, one per source system::

        {
            "system_uri": str,
            "system_label": str,
            "database": str,
            "schema": str,
            "connection_type": str,
            "tables": [
                {
                    "uri": str,
                    "name": str,        # physical table name
                    "label": str,
                    "pk_columns": [str],
                    "incremental_column": str | None,
                    "columns": [
                        {"uri": str, "name": str, "data_type": str,
                         "nullable": bool, "is_pk": bool}
                    ]
                }
            ]
        }
    """
    if not sources_dir or not sources_dir.is_dir():
        return []

    g = Graph()
    for ttl in sorted(sources_dir.rglob("*.ttl")):
        try:
            g.parse(ttl, format="turtle")
        except Exception as exc:
            logger.warning("Could not parse vocabulary file %s: %s", ttl.name, exc)

    systems: list[dict] = []
    for sys_uri in g.subjects(RDF.type, KAIROS_BRONZE.SourceSystem):
        label = str(g.value(sys_uri, RDFS.label) or extract_local_name(str(sys_uri)))
        db = str(g.value(sys_uri, KAIROS_BRONZE.database) or "")
        schema = str(g.value(sys_uri, KAIROS_BRONZE.schema) or "dbo")
        conn = str(g.value(sys_uri, KAIROS_BRONZE.connectionType) or "jdbc")

        tables: list[dict] = []
        for tbl_uri in g.subjects(KAIROS_BRONZE.sourceSystem, sys_uri):
            if (tbl_uri, RDF.type, KAIROS_BRONZE.SourceTable) not in g:
                continue
            tbl_name = str(g.value(tbl_uri, KAIROS_BRONZE.tableName) or
                           extract_local_name(str(tbl_uri)))
            tbl_label = str(g.value(tbl_uri, RDFS.label) or tbl_name)
            pk_raw = str(g.value(tbl_uri, KAIROS_BRONZE.primaryKeyColumns) or "")
            pk_cols = pk_raw.split() if pk_raw else []
            inc_col = g.value(tbl_uri, KAIROS_BRONZE.incrementalColumn)

            columns: list[dict] = []
            for col_uri in g.subjects(KAIROS_BRONZE.sourceTable, tbl_uri):
                if (col_uri, RDF.type, KAIROS_BRONZE.SourceColumn) not in g:
                    continue
                col_name = str(g.value(col_uri, KAIROS_BRONZE.columnName) or
                               extract_local_name(str(col_uri)))
                col_type = str(g.value(col_uri, KAIROS_BRONZE.dataType) or "string")
                nullable_val = g.value(col_uri, KAIROS_BRONZE.nullable)
                nullable = True if nullable_val is None else str(nullable_val).lower() == "true"
                is_pk_val = g.value(col_uri, KAIROS_BRONZE.isPrimaryKey)
                is_pk = str(is_pk_val).lower() == "true" if is_pk_val else col_name in pk_cols

                # JSON content type support
                content_type = g.value(col_uri, KAIROS_BRONZE.contentType)
                json_info = None
                if content_type and str(content_type) in ("json-array", "json-object"):
                    json_path = str(g.value(col_uri, KAIROS_BRONZE.jsonPath) or "$")
                    schema_uri = g.value(col_uri, KAIROS_BRONZE.jsonSchema)
                    json_fields = []
                    if schema_uri:
                        for field_node in g.objects(schema_uri, KAIROS_BRONZE.jsonField):
                            fname = str(g.value(field_node, KAIROS_BRONZE.fieldName) or "")
                            ftype = str(g.value(field_node, KAIROS_BRONZE.fieldType) or "VARCHAR(255)")
                            fpath = str(g.value(field_node, KAIROS_BRONZE.fieldPath) or f"$.{fname}")
                            fmax = g.value(field_node, KAIROS_BRONZE.fieldMaxLength)
                            json_fields.append({
                                "name": fname,
                                "type": ftype,
                                "path": fpath,
                                "max_length": int(str(fmax)) if fmax else 255,
                            })
                    json_info = {
                        "content_type": str(content_type),
                        "json_path": json_path,
                        "fields": json_fields,
                    }

                # Enum support
                enum_uri = g.value(col_uri, KAIROS_BRONZE.enumeration)
                enum_values = []
                if enum_uri:
                    for ev_node in g.objects(enum_uri, KAIROS_BRONZE.enumValue):
                        ev_code = str(g.value(ev_node, KAIROS_BRONZE.enumCode) or "")
                        ev_label = str(g.value(ev_node, KAIROS_BRONZE.enumLabel) or "")
                        if ev_code:
                            enum_values.append({"code": ev_code, "label": ev_label})

                columns.append({
                    "uri": str(col_uri),
                    "name": col_name,
                    "data_type": col_type,
                    "nullable": nullable,
                    "is_pk": is_pk,
                    "json_info": json_info,
                    "enum_values": enum_values if enum_values else None,
                })

            # Discriminator column support
            disc_col_uri = g.value(tbl_uri, KAIROS_BRONZE.discriminatorColumn)
            disc_col_name = None
            disc_values = []
            if disc_col_uri:
                disc_col_name = str(
                    g.value(disc_col_uri, KAIROS_BRONZE.columnName)
                    or extract_local_name(str(disc_col_uri))
                )
                for dv_node in g.objects(tbl_uri, KAIROS_BRONZE.discriminatorValue):
                    dv_code = str(g.value(dv_node, KAIROS_BRONZE.discriminatorCode) or "")
                    dv_label = str(g.value(dv_node, KAIROS_BRONZE.discriminatorLabel) or "")
                    if dv_code:
                        disc_values.append({"code": dv_code, "label": dv_label})

            tables.append({
                "uri": str(tbl_uri),
                "name": tbl_name,
                "label": tbl_label,
                "pk_columns": pk_cols,
                "incremental_column": str(inc_col) if inc_col else None,
                "columns": columns,
                "discriminator_column": disc_col_name,
                "discriminator_values": disc_values if disc_values else None,
            })

        systems.append({
            "system_uri": str(sys_uri),
            "system_label": label,
            "database": db,
            "schema": schema,
            "connection_type": conn,
            "tables": tables,
        })

    return systems


# ---------------------------------------------------------------------------
# SKOS mapping parser
# ---------------------------------------------------------------------------

def _parse_skos_mappings(mappings_dir: Path) -> dict:
    """Parse SKOS + kairos-map: mappings and return structured mapping data.

    Returns::

        {
            "table_maps": {bronze_table_uri: {
                "target_uri": silver_class_uri,
                "mapping_type": "direct" | "split" | "merge",
                "filter_condition": str | None,
                "dedup_key": str | None,
                "dedup_order": str | None,
            }},
            "column_maps": {bronze_col_uri: {
                "target_uri": silver_property_uri,
                "match_type": "exactMatch" | "closeMatch" | "narrowMatch" | ...,
                "transform": str | None,
                "source_columns": [str] | None,
                "default_value": str | None,
            }}
        }
    """
    result: dict = {"table_maps": {}, "column_maps": {}}
    if not mappings_dir or not mappings_dir.is_dir():
        return result

    g = Graph()
    for ttl in sorted(mappings_dir.glob("*.ttl")):
        try:
            g.parse(ttl, format="turtle")
        except Exception as exc:
            logger.warning("Could not parse mapping file %s: %s", ttl.name, exc)

    # SKOS match properties to check (ordered by preference)
    match_props = [
        (SKOS.exactMatch, "exactMatch"),
        (SKOS.closeMatch, "closeMatch"),
        (SKOS.narrowMatch, "narrowMatch"),
        (SKOS.broadMatch, "broadMatch"),
        (SKOS.relatedMatch, "relatedMatch"),
    ]

    for subj in set(g.subjects()):
        for skos_prop, match_name in match_props:
            for obj in g.objects(subj, skos_prop):
                subj_str = str(subj)
                obj_str = str(obj)

                # Check if this is a table-level or column-level mapping
                mapping_type = g.value(subj, KAIROS_MAP.mappingType)
                transform = g.value(subj, KAIROS_MAP.transform)

                if mapping_type is not None:
                    # Table-level mapping
                    filt = g.value(subj, KAIROS_MAP.filterCondition)
                    dedup_key = g.value(subj, KAIROS_MAP.deduplicationKey)
                    dedup_order = g.value(subj, KAIROS_MAP.deduplicationOrder)
                    result["table_maps"][subj_str] = {
                        "target_uri": obj_str,
                        "mapping_type": str(mapping_type),
                        "filter_condition": str(filt) if filt else None,
                        "dedup_key": str(dedup_key) if dedup_key else None,
                        "dedup_order": str(dedup_order) if dedup_order else None,
                    }
                else:
                    # Column-level mapping
                    src_cols = g.value(subj, KAIROS_MAP.sourceColumns)
                    default = g.value(subj, KAIROS_MAP.defaultValue)
                    result["column_maps"][subj_str] = {
                        "target_uri": obj_str,
                        "match_type": match_name,
                        "transform": str(transform) if transform else None,
                        "source_columns": str(src_cols).split() if src_cols else None,
                        "default_value": str(default) if default else None,
                    }

    return result


# ---------------------------------------------------------------------------
# SHACL → dbt test extraction
# ---------------------------------------------------------------------------

def _extract_shacl_tests(shapes_dir: Path, class_uri: str) -> dict[str, list]:
    """Extract dbt tests from SHACL shapes for a given class.

    Returns ``{column_name: [test_strings]}``.
    """
    if not shapes_dir or not shapes_dir.exists():
        return {}

    class_name = extract_local_name(class_uri)
    shape_file = shapes_dir / f"{class_name.lower()}.shacl.ttl"
    if not shape_file.exists():
        return {}

    try:
        sg = Graph()
        sg.parse(shape_file, format="turtle")
    except Exception:
        return {}

    tests_by_col: dict[str, list] = {}

    for ps in sg.objects(predicate=SH.property):
        path = sg.value(ps, SH.path)
        if not path:
            continue
        col_name = _camel_to_snake(extract_local_name(str(path)))
        tests: list = []

        min_count = sg.value(ps, SH.minCount)
        if min_count and int(min_count) > 0:
            tests.append("not_null")

        max_count = sg.value(ps, SH.maxCount)
        if max_count and int(max_count) == 1 and min_count and int(min_count) == 1:
            tests.append("unique")

        pattern = sg.value(ps, SH.pattern)
        if pattern:
            p = str(pattern).replace("'", "\\'")
            tests.append(
                f"dbt_expectations.expect_column_values_to_match_regex:\n"
                f"            regex: '{p}'"
            )

        in_list = sg.value(ps, SH["in"])
        if in_list:
            values = [f"'{str(v)}'" for v in sg.items(in_list)]
            if values:
                tests.append(
                    f"accepted_values:\n"
                    f"            values: [{', '.join(values)}]"
                )

        min_len = sg.value(ps, SH.minLength)
        max_len = sg.value(ps, SH.maxLength)
        if min_len or max_len:
            parts = []
            if min_len:
                parts.append(f"min_value: {int(min_len)}")
            if max_len:
                parts.append(f"max_value: {int(max_len)}")
            tests.append(
                f"dbt_expectations.expect_column_value_lengths_to_be_between:\n"
                f"            {'\n            '.join(parts)}"
            )

        min_inc = sg.value(ps, SH.minInclusive)
        max_inc = sg.value(ps, SH.maxInclusive)
        if min_inc or max_inc:
            parts = []
            if min_inc:
                parts.append(f"min_value: {min_inc}")
            if max_inc:
                parts.append(f"max_value: {max_inc}")
            tests.append(
                f"dbt_expectations.expect_column_values_to_be_between:\n"
                f"            {'\n            '.join(parts)}"
            )

        if tests:
            tests_by_col[col_name] = tests

    return tests_by_col


# ---------------------------------------------------------------------------
# Artifact generators
# ---------------------------------------------------------------------------

def _gen_sources(systems: list[dict], env: Environment) -> dict[str, str]:
    """Generate a single minimal ``_sources.yml`` under ``models/silver/``.

    The sources YAML is intentionally minimal — it declares only database,
    schema, and table names so dbt can generate ``{{ source() }}`` references.
    Column-level documentation lives in the vocabulary TTL (the authoritative
    source of bronze table structure), not in the dbt sources YAML.
    """
    artifacts: dict[str, str] = {}
    template = env.get_template("sources.yml.jinja2")

    for sys in systems:
        source_name = _camel_to_snake(sys["system_label"]).replace(" ", "_")
        tables_data = []
        for tbl in sys["tables"]:
            tables_data.append({
                "name": tbl["name"],
                "label": tbl["label"],
            })

        content = template.render(
            source_name=source_name,
            system_label=sys["system_label"],
            database=sys["database"],
            schema=sys["schema"],
            tables=tables_data,
        )
        path = f"models/silver/_{source_name}__sources.yml"
        artifacts[path] = content

    return artifacts


def _build_spark_schema(fields: list[dict]) -> str:
    """Build Spark schema string for from_json(). E.g. 'array<struct<name:string,age:int>>'."""
    field_parts = []
    for f in fields:
        # Map field length to Spark type (all extracted as string for safety)
        field_parts.append(f"{f['name']}:string")
    return f"array<struct<{','.join(field_parts)}>>"


def _gen_staging_models(
    systems: list[dict],
    mappings: dict,
    env: Environment,
    meta: dict,
    platform: str = DEFAULT_PLATFORM,
) -> dict[str, str]:
    """Generate ``stg_{source}__{table}.sql`` staging models."""
    artifacts: dict[str, str] = {}
    # Select template based on platform
    if platform in ("databricks", "spark"):
        template = env.get_template("staging_model_databricks.sql.jinja2")
    else:
        template = env.get_template("staging_model.sql.jinja2")

    for sys in systems:
        source_name = _camel_to_snake(sys["system_label"]).replace(" ", "_")

        for tbl in sys["tables"]:
            tbl_uri = tbl["uri"]
            tbl_map = mappings["table_maps"].get(tbl_uri, {})

            columns_data = []
            json_extractions = []
            for col in tbl["columns"]:
                col_uri = col["uri"] if "uri" in col else ""
                col_map = mappings["column_maps"].get(col_uri, {})

                # Check if this is a JSON column requiring extraction
                json_info = col.get("json_info")
                if json_info and json_info.get("fields"):
                    # JSON column: don't include as a regular column,
                    # instead add to json_extractions
                    alias = f"j_{_camel_to_snake(col['name'])}"
                    fields = [
                        {
                            "name": _camel_to_snake(f["name"]),
                            "length": f.get("max_length", 255),
                            "path": f["path"],
                        }
                        for f in json_info["fields"]
                    ]
                    extraction = {
                        "source_column": col["name"],
                        "alias": alias,
                        "content_type": json_info["content_type"],
                        "json_path": json_info["json_path"],
                        "fields": fields,
                    }
                    # For Databricks, add Spark schema string
                    if platform in ("databricks", "spark"):
                        extraction["spark_schema"] = _build_spark_schema(fields)
                    json_extractions.append(extraction)
                    continue

                # Use explicit transform if available, else default cast
                if col_map.get("transform"):
                    expr = col_map["transform"].replace("source.", "")
                else:
                    target_type = _source_type_to_target(col["data_type"], platform)
                    if target_type.startswith("VARCHAR") or target_type == "STRING":
                        expr = col["name"]
                    else:
                        expr = f"TRY_CAST({col['name']} AS {target_type})"

                # Target column name: from SKOS mapping or snake_case of source
                if col_map.get("target_uri"):
                    target_name = _camel_to_snake(
                        extract_local_name(col_map["target_uri"])
                    )
                else:
                    target_name = _camel_to_snake(col["name"])

                columns_data.append({
                    "expression": expr,
                    "target_name": target_name,
                })

            snake_table = _camel_to_snake(tbl["name"])
            # Determine materialization (incremental if configured)
            incremental_col = tbl.get("incremental_column")
            content = template.render(
                source_name=source_name,
                table_name=snake_table,
                system_label=sys["system_label"],
                raw_table_name=tbl["name"],
                columns=columns_data,
                json_extractions=json_extractions,
                filter_condition=tbl_map.get("filter_condition"),
                dedup_key=tbl_map.get("dedup_key"),
                dedup_order=tbl_map.get("dedup_order"),
                ontology_metadata=meta,
                incremental_column=incremental_col,
            )
            path = f"models/staging/{source_name}/stg_{source_name}__{snake_table}.sql"
            artifacts[path] = content

    return artifacts


def _gen_silver_models(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    systems: list[dict],
    mappings: dict,
    env: Environment,
    meta: dict,
    ontology_name: str,
    platform: str = DEFAULT_PLATFORM,
) -> dict[str, str]:
    """Generate silver entity models that read directly from bronze sources.

    Enforces layer contracts:
    - Silver models consume bronze tables via source() — no staging layer
    - Every source() must point to a declared bronze source table
    - Unmapped classes are skipped with a warning (no broken placeholders)
    - Silver absorbs rename, cast, and transform logic (previously in staging)
    """
    artifacts: dict[str, str] = {}
    template = env.get_template("silver_model.sql.jinja2")

    schema_name = f"silver_{ontology_name}"

    # Build reverse map: silver class URI → [(source_name, raw_table_name, table_uri)]
    class_to_sources: dict[str, list[tuple[str, str, str]]] = {}
    for sys in systems:
        source_name = _camel_to_snake(sys["system_label"]).replace(" ", "_")
        for tbl in sys["tables"]:
            tbl_map = mappings["table_maps"].get(tbl["uri"], {})
            target = tbl_map.get("target_uri")
            if target:
                class_to_sources.setdefault(target, []).append(
                    (source_name, tbl["name"], tbl["uri"])
                )

    for cls in classes:
        cls_uri = cls["uri"]
        local = cls["name"]
        model_name = _camel_to_snake(local)

        source_refs = class_to_sources.get(cls_uri, [])
        if not source_refs:
            logger.warning(
                "No bronze mapping for class %s — skipping silver model generation. "
                "Add a mapping in the mappings TTL to enable this model.",
                local,
            )
            continue

        # Extract properties for column list with platform-aware types
        columns = _extract_silver_columns(
            graph, cls_uri, namespace, mappings, platform=platform,
            source_refs=source_refs, systems=systems,
        )

        # Build source CTEs that reference bronze tables directly
        source_ctes = []
        filter_conditions = []
        for i, (src, raw_tbl, tbl_uri) in enumerate(source_refs):
            alias = _camel_to_snake(raw_tbl) if len(source_refs) == 1 else f"src_{i + 1}"
            source_ctes.append({
                "source_name": src,
                "table_name": raw_tbl,
                "alias": alias,
            })
            tbl_map = mappings["table_maps"].get(tbl_uri, {})
            if tbl_map.get("filter_condition"):
                filter_conditions.append(tbl_map["filter_condition"])

        # Determine WHERE clause from filter conditions
        where_clause = ""
        if filter_conditions and len(source_refs) == 1:
            where_clause = filter_conditions[0].replace("source.", "")

        content = template.render(
            model_name=model_name,
            domain_name=ontology_name,
            schema_name=schema_name,
            materialization="table",
            source_ctes=source_ctes,
            columns=columns,
            joins=[],
            where_clause=where_clause,
            ontology_metadata=meta,
        )
        path = f"models/silver/{ontology_name}/{model_name}.sql"
        artifacts[path] = content

    return artifacts


def _extract_silver_columns(
    graph: Graph,
    class_uri: str,
    namespace: str,
    mappings: dict,
    platform: str = DEFAULT_PLATFORM,
    source_refs: list[tuple[str, str, str]] | None = None,
    systems: list[dict] | None = None,
) -> list[dict]:
    """Extract silver-layer columns for a class from the ontology graph.

    Since silver reads directly from bronze (no staging layer), column
    expressions reference original bronze column names and apply casts/transforms
    inline.  Transform expressions from SKOS mappings are used as-is; direct
    mappings reference the original bronze column name with appropriate casting.

    Features:
    - SK uses dbt_utils.generate_surrogate_key() based on natural key columns
    - IRI constructs a proper ontology IRI from namespace + natural key
    - Mapped properties use their transform expressions (referencing bronze cols)
    - Direct mappings use original bronze column name with TRY_CAST
    - Unmapped optional properties use CAST(NULL AS {{ dbt_utils.type_*() }})
    - Types use dbt_utils macros for portability across platforms
    - Enum columns generate CASE statements for human-readable labels
    """
    columns: list[dict] = []
    model_name = _camel_to_snake(extract_local_name(class_uri))

    # Build lookups from bronze column URI → original column name / data type / enums
    bronze_col_lookup: dict[str, dict] = {}
    enum_lookup: dict[str, list[dict]] = {}
    if systems:
        for sys in systems:
            for tbl in sys["tables"]:
                for col in tbl["columns"]:
                    bronze_col_lookup[col["uri"]] = {
                        "name": col["name"],
                        "data_type": col["data_type"],
                    }
                    if col.get("enum_values"):
                        enum_lookup[col["uri"]] = col["enum_values"]

    # Determine natural key columns from kairos-ext:naturalKey annotation or PK columns
    natural_key_cols = _get_natural_key(graph, class_uri)

    # SK column: use surrogate key generation if natural key is known
    if natural_key_cols:
        sk_cols_str = "', '".join(natural_key_cols)
        sk_expr = f"{{{{ dbt_utils.generate_surrogate_key(['{sk_cols_str}']) }}}}"
    else:
        # Fallback: hash all non-null columns — will be overridden when natural key is set
        sk_expr = "CAST(NULL AS {{ dbt_utils.type_string() }})"

    columns.append({"expression": sk_expr, "target_name": f"{model_name}_sk"})

    # IRI column: construct from namespace + natural key
    if natural_key_cols:
        if len(natural_key_cols) == 1:
            iri_expr = (
                f"CONCAT('{namespace}', '{extract_local_name(class_uri)}/', "
                f"{natural_key_cols[0]})"
            )
        else:
            parts = ", '/', ".join(natural_key_cols)
            iri_expr = f"CONCAT('{namespace}', '{extract_local_name(class_uri)}/', {parts})"
    else:
        iri_expr = "CAST(NULL AS {{ dbt_utils.type_string() }})"

    columns.append({"expression": iri_expr, "target_name": f"{model_name}_iri"})

    # Datatype properties
    for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain and str(domain) == class_uri:
            prop_name = extract_local_name(str(prop))
            col_name = _camel_to_snake(prop_name)
            range_uri = graph.value(prop, RDFS.range)
            # Use dbt_utils macros for portable silver types
            macro_type = _xsd_to_dbt_macro(range_uri)

            # Check population requirement from kairos-ext annotation
            pop_req = graph.value(URIRef(str(prop)), KAIROS_EXT.populationRequirement)
            population = str(pop_req) if pop_req else "optional"

            # Check if there's a SKOS mapping transform for this property
            expr = None
            mapped_col_uri = None
            for col_uri, col_map in mappings.get("column_maps", {}).items():
                if col_map.get("target_uri") == str(prop):
                    mapped_col_uri = col_uri
                    if col_map.get("transform"):
                        expr = col_map["transform"].replace("source.", "")
                    else:
                        # Direct mapping — use the original bronze column name
                        # with a TRY_CAST to the target type
                        bronze_col = bronze_col_lookup.get(col_uri)
                        if bronze_col:
                            src_type = bronze_col["data_type"]
                            target_type = _source_type_to_target(src_type, platform)
                            bronze_name = bronze_col["name"]
                            if target_type.startswith("VARCHAR") or target_type == "STRING":
                                expr = bronze_name
                            else:
                                expr = f"TRY_CAST({bronze_name} AS {target_type})"
                        else:
                            # Fallback: use URI local name
                            source_col_name = extract_local_name(col_uri)
                            expr = source_col_name
                    break

            if expr is None:
                if population == "derived":
                    # Check for derivation formula
                    formula = graph.value(
                        URIRef(str(prop)), KAIROS_EXT.derivationFormula
                    )
                    if formula:
                        expr = str(formula)
                    else:
                        expr = f"CAST(NULL AS {macro_type})"
                else:
                    # Unmapped: NULL placeholder with portable dbt_utils type
                    expr = f"CAST(NULL AS {macro_type})"

            columns.append({"expression": expr, "target_name": col_name})

            # Generate _label column for enum-typed source columns
            if mapped_col_uri and mapped_col_uri in enum_lookup:
                enum_vals = enum_lookup[mapped_col_uri]
                case_expr = _build_enum_case(expr, enum_vals)
                columns.append({
                    "expression": case_expr,
                    "target_name": f"{col_name}_label",
                })

    return columns


def _build_enum_case(source_expr: str, enum_values: list[dict]) -> str:
    """Build a CASE statement to resolve enum codes to human-readable labels."""
    parts = [f"CASE CAST({source_expr} AS VARCHAR(50))"]
    for ev in enum_values:
        code = ev["code"].replace("'", "''")
        label = ev["label"].replace("'", "''")
        parts.append(f"        WHEN '{code}' THEN '{label}'")
    parts.append(
        f"        ELSE CONCAT('Unknown (', CAST({source_expr} AS VARCHAR(50)), ')')"
    )
    parts.append("    END")
    return "\n".join(parts)


def _get_natural_key(graph: Graph, class_uri: str) -> list[str]:
    """Get natural key column names for a class from kairos-ext:naturalKey annotation.

    Falls back to checking for properties annotated as primary key in mappings.
    """
    # Check kairos-ext:naturalKey on the class
    nk = graph.value(URIRef(class_uri), KAIROS_EXT.term("naturalKey"))
    if nk:
        return [_camel_to_snake(c) for c in str(nk).split()]

    return []


def _gen_schema_yaml(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    shapes_dir: Optional[Path],
    env: Environment,
    ontology_name: str,
    meta: dict,
    systems: list[dict] | None = None,
    mappings: dict | None = None,
) -> dict[str, str]:
    """Generate ``_models.yml`` with column descriptions, tests, and lineage."""
    artifacts: dict[str, str] = {}
    template = env.get_template("schema_models.yml.jinja2")

    # Build enum lookup from source systems for accepted_values tests
    enum_lookup: dict[str, list[dict]] = {}
    if systems:
        for sys in systems:
            for tbl in sys["tables"]:
                for col in tbl["columns"]:
                    if col.get("enum_values"):
                        enum_lookup[col["uri"]] = col["enum_values"]

    # Build mapping reverse-lookup: property URI → source column URI
    prop_to_source: dict[str, str] = {}
    if mappings:
        for col_uri, col_map in mappings.get("column_maps", {}).items():
            if col_map.get("target_uri"):
                prop_to_source[col_map["target_uri"]] = col_uri

    models_data = []
    for cls in classes:
        model_name = _camel_to_snake(cls["name"])
        shacl_tests = _extract_shacl_tests(shapes_dir, cls["uri"]) if shapes_dir else {}

        cols = []
        # SK + IRI columns
        cols.append({
            "name": f"{model_name}_sk",
            "description": "Surrogate key (PK)",
            "meta": {"is_pk": "true"},
            "tests": ["not_null", "unique"],
        })
        cols.append({
            "name": f"{model_name}_iri",
            "description": "OWL IRI lineage",
            "meta": {},
            "tests": ["not_null", "unique"],
        })

        # Datatype properties
        for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
            domain = graph.value(prop, RDFS.domain)
            if domain and str(domain) == cls["uri"]:
                prop_name = extract_local_name(str(prop))
                col_name = _camel_to_snake(prop_name)
                label = graph.value(prop, RDFS.label)
                comment = graph.value(prop, RDFS.comment)
                desc = str(comment) if comment else (str(label) if label else prop_name)
                range_uri = graph.value(prop, RDFS.range)
                data_type = _xsd_to_target(range_uri) if range_uri else "VARCHAR(255)"

                # Start with SHACL-derived tests
                tests = list(shacl_tests.get(col_name, []))

                # Add not_null for required properties (from kairos-ext annotation)
                pop_req = graph.value(URIRef(str(prop)), KAIROS_EXT.populationRequirement)
                if pop_req and str(pop_req) == "required" and "not_null" not in tests:
                    tests.append("not_null")

                # Add accepted_values for enum-typed source columns
                source_col_uri = prop_to_source.get(str(prop))
                if source_col_uri and source_col_uri in enum_lookup:
                    enum_vals = enum_lookup[source_col_uri]
                    values_list = [ev["code"] for ev in enum_vals]
                    tests.append({
                        "accepted_values": {
                            "values": values_list,
                        }
                    })

                # Lineage metadata
                col_meta = {"data_type": data_type}
                if source_col_uri:
                    col_meta["source_iri"] = source_col_uri

                cols.append({
                    "name": col_name,
                    "description": desc,
                    "meta": col_meta,
                    "tests": tests,
                })

        models_data.append({
            "name": model_name,
            "description": cls["comment"],
            "meta": {
                "ontology_class": cls["name"],
                "ontology_iri": meta.get("iri", ""),
            },
            "columns": cols,
        })

    if models_data:
        content = template.render(models=models_data)
        path = f"models/silver/{ontology_name}/_{ontology_name}__models.yml"
        artifacts[path] = content

    return artifacts


def _gen_project_config(
    systems: list[dict],
    ontology_names: list[str],
    env: Environment,
    project_name: str,
    gold_domains: list[dict] = None,
    platform: str = DEFAULT_PLATFORM,
) -> dict[str, str]:
    """Generate ``dbt_project.yml``, ``packages.yml``, and ``README.md``."""
    artifacts: dict[str, str] = {}

    domains = [{"name": n} for n in ontology_names]

    proj_template = env.get_template("dbt_project.yml.jinja2")
    artifacts["dbt_project.yml"] = proj_template.render(
        project_name=project_name,
        domains=domains,
        gold_domains=gold_domains or [],
    )

    pkg_template = env.get_template("packages.yml.jinja2")
    artifacts["packages.yml"] = pkg_template.render()

    # Platform-specific README
    adapter = "dbt-fabric" if platform == "fabric" else "dbt-databricks"
    adapter_install = f"pip install {adapter}"
    platform_label = "Microsoft Fabric Warehouse" if platform == "fabric" else "Azure Databricks"

    artifacts["README.md"] = f"""# dbt Project — {project_name}

Generated by **Kairos Ontology Toolkit** (dbt projector).

## Target Platform

| Setting | Value |
|---------|-------|
| Platform | {platform_label} |
| dbt adapter | `{adapter}` |
| SQL dialect | {'T-SQL' if platform == 'fabric' else 'Spark SQL'} |

## Getting Started

```bash
# Install dbt and the adapter
pip install dbt-core
{adapter_install}

# Install dbt packages (dbt_utils, dbt_expectations)
dbt deps

# Configure your connection in profiles.yml
# Then run:
dbt run
```

## Project Structure

```
models/
├── silver/           # Domain-aligned: maps bronze → canonical entities
│   └── <domain>/    # One folder per ontology domain
└── gold/             # Star schema: facts, dimensions, measures
    └── <domain>/

macros/               # Platform-abstraction macros (kairos_safe_cast, etc.)
```

## Layer Contracts

| Layer | Materialization | Purpose |
|-------|----------------|---------|
| Bronze | (platform-managed) | Raw source tables — outside dbt |
| Silver | Table | Domain entities mapped from bronze via `{{{{ source() }}}}` |
| Gold | Table | Star schema for BI (Power BI DirectLake / Databricks SQL) |

## Platform Macros

The `macros/` folder contains platform-abstraction macros:
- `kairos_safe_cast(column, type)` — safe casting (TRY_CAST)
- `kairos_json_value(column, path)` — extract single JSON value
- `kairos_surrogate_key(columns)` — surrogate key generation
- `kairos_concat(...)` — string concatenation
"""

    return artifacts


# ---------------------------------------------------------------------------
# Gold model generation (thick gold — pre-materialized star schema)
# ---------------------------------------------------------------------------

def _silver_model_name_for_class(cls_uri: str, classes: list[dict]) -> str:
    """Derive the silver dbt model name for a given ontology class URI."""
    for cls in classes:
        if cls["uri"] == cls_uri:
            return _camel_to_snake(cls["name"])
    local = extract_local_name(cls_uri)
    return _camel_to_snake(local)


def _gen_gold_models(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    shapes_dir: Optional[Path],
    ontology_name: str,
    gold_ext_path: Optional[Path],
    env: Environment,
    meta: dict,
) -> dict[str, str]:
    """Generate gold dbt models from gold table definitions.

    Uses the shared ``build_gold_tables()`` from the gold projector to get
    ``GoldTableDef`` objects, then renders each as a dbt SQL model that
    reads from the corresponding silver model via ``ref()``.
    """
    from .medallion_gold_projector import build_gold_tables, GoldTableDef

    gold_tables = build_gold_tables(
        classes, graph, namespace, shapes_dir, ontology_name, gold_ext_path,
    )
    if not gold_tables:
        return {}

    artifacts: dict[str, str] = {}
    template = env.get_template("gold_model.sql.jinja2")
    schema_name = gold_tables[0].schema if gold_tables else f"gold_{ontology_name}"

    for tbl in gold_tables:
        # dim_date is auto-generated — no silver ref needed
        if tbl.name == "dim_date":
            columns = []
            for col in tbl.columns:
                columns.append({
                    "expression": f"CAST(NULL AS {col.sql_type})",
                    "target_name": col.name,
                })
            content = template.render(
                model_name=tbl.name,
                domain_name=ontology_name,
                schema_name=schema_name,
                table_type="dimension",
                scd_type=tbl.scd_type,
                is_gdpr=False,
                source_ctes=[{"model": f"seed_dim_date", "alias": "date_seed"}],
                columns=columns,
                joins=[],
                where_clause="",
                ontology_metadata=meta,
                incremental_column="",
                unique_key="",
            )
            path = f"models/gold/{ontology_name}/{tbl.name}.sql"
            artifacts[path] = content
            continue

        # Build silver ref(s)
        source_ctes = []
        if tbl.is_subtype_cpt and tbl.parent_class_uri:
            # Class-per-table subtype: silver uses discriminator, so source
            # from parent's silver table (subtype is folded into parent in silver)
            silver_name = _silver_model_name_for_class(
                tbl.parent_class_uri, classes)
            source_ctes.append({"model": silver_name, "alias": silver_name})
        elif tbl.source_class_uri:
            silver_name = _silver_model_name_for_class(tbl.source_class_uri, classes)
            source_ctes.append({"model": silver_name, "alias": silver_name})

        # For fact tables with FK constraints, also ref the dimension silver models
        if tbl.table_type == "fact":
            seen_models = {c["model"] for c in source_ctes}
            for fk_col, ref_full, ref_col, label in tbl.fk_constraints:
                ref_tbl_name = ref_full.split(".")[-1]
                # Find the silver model for the referenced gold table
                ref_gold = next(
                    (t for t in gold_tables if t.name == ref_tbl_name), None)
                if ref_gold and ref_gold.source_class_uri:
                    ref_silver = _silver_model_name_for_class(
                        ref_gold.source_class_uri, classes)
                    if ref_silver not in seen_models:
                        source_ctes.append({
                            "model": ref_silver,
                            "alias": ref_silver,
                        })
                        seen_models.add(ref_silver)

        # GDPR satellite: ref parent dimension's silver model
        if tbl.is_gdpr and tbl.gdpr_parent_table:
            parent_gold = next(
                (t for t in gold_tables if t.name == tbl.gdpr_parent_table), None)
            if parent_gold and parent_gold.source_class_uri:
                parent_silver = _silver_model_name_for_class(
                    parent_gold.source_class_uri, classes)
                if not any(c["model"] == parent_silver for c in source_ctes):
                    source_ctes.append({
                        "model": parent_silver, "alias": parent_silver,
                    })

        if not source_ctes:
            logger.info("No silver ref for gold table %s — skipping", tbl.name)
            continue

        # Build column expressions
        columns = []
        for col in tbl.columns:
            if col.is_measure:
                continue
            columns.append({
                "expression": col.name,
                "target_name": col.name,
            })

        # SCD2 framing: filter to current records only
        where_clause = ""
        if (tbl.table_type == "dimension" and tbl.scd_type == "2"
                and not tbl.is_gdpr):
            where_clause = "is_current = 1"

        content = template.render(
            model_name=tbl.name,
            domain_name=ontology_name,
            schema_name=schema_name,
            table_type=tbl.table_type,
            scd_type=tbl.scd_type,
            is_gdpr=tbl.is_gdpr,
            source_ctes=source_ctes,
            columns=columns,
            joins=[],
            where_clause=where_clause,
            ontology_metadata=meta,
            incremental_column=tbl.incremental_column or "",
            unique_key=tbl.pk_column or "",
        )
        path = f"models/gold/{ontology_name}/{tbl.name}.sql"
        artifacts[path] = content

    return artifacts


def _gen_gold_schema_yaml(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    shapes_dir: Optional[Path],
    ontology_name: str,
    gold_ext_path: Optional[Path],
    env: Environment,
    meta: dict,
) -> dict[str, str]:
    """Generate ``_gold_models.yml`` with column descriptions and tests."""
    from .medallion_gold_projector import build_gold_tables

    gold_tables = build_gold_tables(
        classes, graph, namespace, shapes_dir, ontology_name, gold_ext_path,
    )
    if not gold_tables:
        return {}

    artifacts: dict[str, str] = {}
    template = env.get_template("gold_schema.yml.jinja2")

    models_data = []
    for tbl in gold_tables:
        # Skip tables that have no corresponding SQL model
        # (junction bridges have no source_class_uri)
        if tbl.name != "dim_date" and not tbl.source_class_uri:
            continue

        cols = []
        for col in tbl.columns:
            if col.is_measure:
                continue
            tests: list = []
            if not col.nullable:
                tests.append("not_null")
            if col.name == tbl.pk_column:
                tests.append("unique")
            col_meta: dict[str, str] = {"sql_type": col.sql_type}
            if col.comment:
                col_meta["comment"] = col.comment
            cols.append({
                "name": col.name,
                "description": col.comment or col.name,
                "meta": col_meta,
                "tests": tests,
            })

        models_data.append({
            "name": tbl.name,
            "description": tbl.source_class_label or tbl.name,
            "table_type": tbl.table_type,
            "ontology_class": tbl.source_class_label or "",
            "ontology_iri": meta.get("iri", ""),
            "columns": cols,
        })

    if models_data:
        content = template.render(models=models_data)
        path = f"models/gold/{ontology_name}/_{ontology_name}__gold_models.yml"
        artifacts[path] = content

    return artifacts


# ---------------------------------------------------------------------------
# Public entry point (called by projector orchestrator)
# ---------------------------------------------------------------------------

def generate_dbt_artifacts(
    classes: list,
    graph: Graph,
    template_dir,
    namespace: str,
    shapes_dir: Path = None,
    ontology_name: str = None,
    ontology_metadata: dict = None,
    bronze_dir: Path = None,
    sources_dir: Path = None,
    mappings_dir: Path = None,
    gold_ext_path: Path = None,
    target_platform: str = DEFAULT_PLATFORM,
) -> dict:
    """Generate dbt project artifacts from ontology + source vocabulary + SKOS mappings.

    This is the entry point called by the main projector orchestrator.

    Args:
        classes: List of class dicts with ``uri``, ``name``, ``label``, ``comment``.
        graph: RDFLib graph with the domain ontology.
        template_dir: Path to dbt Jinja2 templates directory.
        namespace: Base namespace for class filtering.
        shapes_dir: Optional SHACL shapes directory.
        ontology_name: Domain name (e.g. ``party``, ``client``).
        ontology_metadata: Provenance metadata dict.
        bronze_dir: Deprecated — use *sources_dir* instead.
        sources_dir: Path to ``integration/sources/`` directory.  Vocabulary TTLs
            are discovered recursively under each source system sub-folder.
        mappings_dir: Path to ``mappings/`` directory with SKOS mapping TTLs.
        gold_ext_path: Optional path to ``*-gold-ext.ttl`` for gold model generation.
        target_platform: Target SQL platform for type mapping.
            Options: ``"fabric"`` (default), ``"databricks"``, ``"spark"`` (alias for databricks).

    Returns:
        Dictionary of ``{file_path: content}`` for all generated artifacts.
    """
    artifacts: dict[str, str] = {}
    meta = ontology_metadata or {}
    onto_name = ontology_name or "domain"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    # Parse source vocabulary — prefer sources_dir, fall back to bronze_dir
    systems = _parse_bronze(sources_dir or bronze_dir)

    # Parse SKOS mappings
    mappings = _parse_skos_mappings(mappings_dir)

    if not systems:
        logger.info("No source systems found — generating silver models only")

    # 1. Sources YAML (minimal — under models/silver/)
    if systems:
        artifacts.update(_gen_sources(systems, env))
        print(f"    ✓ Generated {len(systems)} source definition(s)")

    # 2. Silver entity models (read directly from bronze via source())
    silver = _gen_silver_models(
        classes, graph, namespace, systems, mappings, env, meta, onto_name,
        platform=target_platform,
    )
    artifacts.update(silver)
    print(f"    ✓ Generated {len(silver)} silver model(s)")

    # 3. Schema YAML with SHACL tests
    schema = _gen_schema_yaml(
        classes, graph, namespace, shapes_dir, env, onto_name, meta,
        systems=systems, mappings=mappings,
    )
    artifacts.update(schema)

    # 4. Project config (only once per domain — orchestrator handles multi-domain)
    has_gold = False
    if systems:
        # 5. Gold entity models (thick gold — pre-materialized star schema)
        gold = _gen_gold_models(
            classes, graph, namespace, shapes_dir, onto_name, gold_ext_path, env, meta,
        )
        artifacts.update(gold)
        has_gold = len(gold) > 0
        if gold:
            print(f"    ✓ Generated {len(gold)} gold model(s)")

        # 6. Gold schema YAML with tests
        gold_schema = _gen_gold_schema_yaml(
            classes, graph, namespace, shapes_dir, onto_name, gold_ext_path, env, meta,
        )
        artifacts.update(gold_schema)

        gold_domains = [{"name": onto_name}] if has_gold else []
        project = _gen_project_config(
            systems, [onto_name], env, f"{onto_name}_project",
            gold_domains=gold_domains,
            platform=target_platform,
        )
        artifacts.update(project)

    # 7. Coverage report
    if systems:
        coverage = _gen_coverage_report(
            classes, graph, namespace, systems, mappings, onto_name,
        )
        if coverage:
            artifacts.update(coverage)
            print("    ✓ Generated coverage report")

    # 8. Platform macros
    macros = _gen_macros(template_dir)
    artifacts.update(macros)
    if macros:
        print(f"    ✓ Generated {len(macros)} platform macro(s)")

    return artifacts


# ---------------------------------------------------------------------------
# Generated macros (platform-abstraction layer for dbt projects)
# ---------------------------------------------------------------------------

def _gen_macros(template_dir) -> dict[str, str]:
    """Copy platform-abstraction macros into the generated dbt project.

    Reads macro files from the ``macros/`` subfolder of the templates directory
    and includes them in the generated artifacts under ``macros/``.
    """
    artifacts: dict[str, str] = {}
    macros_dir = Path(template_dir) / "macros"
    if not macros_dir.exists():
        return artifacts

    for macro_file in macros_dir.glob("*.sql"):
        content = macro_file.read_text(encoding="utf-8")
        artifacts[f"macros/{macro_file.name}"] = content

    return artifacts


# ---------------------------------------------------------------------------
# Coverage report generation
# ---------------------------------------------------------------------------

def _gen_coverage_report(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    systems: list[dict],
    mappings: dict,
    ontology_name: str,
) -> dict[str, str]:
    """Generate a JSON coverage report showing mapping completeness.

    Reports for each ontology entity:
    - Total properties vs mapped vs unmapped
    - Required properties that are missing mappings
    - Source column utilization (consumed vs unused)
    """
    import json

    report: dict = {}

    # Build column_maps reverse: target_uri → source column URI
    target_to_source: dict[str, str] = {}
    for col_uri, col_map in mappings.get("column_maps", {}).items():
        if col_map.get("target_uri"):
            target_to_source[col_map["target_uri"]] = col_uri

    # Build set of all consumed source column URIs
    consumed_source_cols = set(mappings.get("column_maps", {}).keys())

    for cls in classes:
        cls_uri = cls["uri"]
        local = cls["name"]
        model_name = _camel_to_snake(local)

        total = 0
        required_count = 0
        optional_count = 0
        derived_count = 0
        populated = 0
        always_null = 0
        null_columns = []
        missing_required = []

        for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
            domain = graph.value(prop, RDFS.domain)
            if domain and str(domain) == cls_uri:
                total += 1
                prop_str = str(prop)
                prop_name = extract_local_name(prop_str)
                col_name = _camel_to_snake(prop_name)

                pop_req = graph.value(URIRef(prop_str), KAIROS_EXT.populationRequirement)
                population = str(pop_req) if pop_req else "optional"

                if population == "required":
                    required_count += 1
                elif population == "derived":
                    derived_count += 1
                else:
                    optional_count += 1

                has_mapping = prop_str in target_to_source
                if has_mapping:
                    populated += 1
                elif population == "derived":
                    formula = graph.value(URIRef(prop_str), KAIROS_EXT.derivationFormula)
                    if formula:
                        populated += 1
                    else:
                        always_null += 1
                        null_columns.append(col_name)
                else:
                    always_null += 1
                    null_columns.append(col_name)
                    if population == "required":
                        missing_required.append(col_name)

        # Source coverage per table mapped to this class
        source_coverage = {}
        for sys in systems:
            source_name = _camel_to_snake(sys["system_label"]).replace(" ", "_")
            for tbl in sys["tables"]:
                tbl_map = mappings.get("table_maps", {}).get(tbl["uri"], {})
                if tbl_map.get("target_uri") == cls_uri:
                    tbl_cols = {c["uri"] for c in tbl["columns"]}
                    used = tbl_cols & consumed_source_cols
                    unused = [
                        c["name"] for c in tbl["columns"]
                        if c["uri"] not in consumed_source_cols
                    ]
                    key = f"{source_name}__{_camel_to_snake(tbl['name'])}"
                    source_coverage[key] = {
                        "available_columns": len(tbl["columns"]),
                        "consumed_columns": len(used),
                        "unused_columns": unused,
                    }

        report[model_name] = {
            "ontology_properties_total": total,
            "ontology_properties_required": required_count,
            "ontology_properties_optional": optional_count,
            "ontology_properties_derived": derived_count,
            "populated_from_source": populated,
            "always_null": always_null,
            "null_columns": null_columns,
            "missing_required_mappings": missing_required,
            "source_coverage": source_coverage,
        }

    content = json.dumps(
        {ontology_name: report}, indent=2, ensure_ascii=False,
    )
    return {"coverage-report.json": content}
