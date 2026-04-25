# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""dbt Projector — generate a dbt Core project from ontology + source vocabulary + SKOS mappings.

Generates a complete dbt project with:

1. **Sources** — ``_sources.yml`` per source system (from source vocabulary TTL)
2. **Staging models** — ``stg_{source}__{table}.sql`` (rename + cast, materialized as views)
3. **Silver models** — ``{entity}.sql`` per domain class (staging → silver, matches silver DDL)
4. **Schema YAML** — ``_models.yml`` with column descriptions + SHACL-derived tests
5. **Project config** — ``dbt_project.yml`` + ``packages.yml``

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

from .uri_utils import extract_local_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

# ---------------------------------------------------------------------------
# Source-type → Spark SQL type mapping (for staging CAST)
# ---------------------------------------------------------------------------
_SOURCE_TO_SPARK: dict[str, str] = {
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

# XSD → Spark SQL type mapping (for silver columns from ontology)
_XSD_TO_SPARK: dict[str, str] = {
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

# SHACL namespace
SH = Namespace("http://www.w3.org/ns/shacl#")


def _camel_to_snake(name: str) -> str:
    """Convert PascalCase / camelCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _source_type_to_spark(src_type: str) -> str:
    """Map a source system data type string to Spark SQL type."""
    base = re.sub(r"\(.*\)", "", src_type.strip().lower())
    return _SOURCE_TO_SPARK.get(base, "STRING")


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

                columns.append({
                    "uri": str(col_uri),
                    "name": col_name,
                    "data_type": col_type,
                    "nullable": nullable,
                    "is_pk": is_pk,
                })

            tables.append({
                "uri": str(tbl_uri),
                "name": tbl_name,
                "label": tbl_label,
                "pk_columns": pk_cols,
                "incremental_column": str(inc_col) if inc_col else None,
                "columns": columns,
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
    """Generate ``_sources.yml`` per source system."""
    artifacts: dict[str, str] = {}
    template = env.get_template("sources.yml.jinja2")

    for sys in systems:
        source_name = _camel_to_snake(sys["system_label"]).replace(" ", "_")
        tables_data = []
        for tbl in sys["tables"]:
            cols_data = []
            for col in tbl["columns"]:
                col_tests = []
                if not col["nullable"]:
                    col_tests.append("not_null")
                if col["is_pk"]:
                    col_tests.append("unique")
                cols_data.append({
                    "name": col["name"],
                    "description": f"{col['data_type']}"
                                   + (" NOT NULL" if not col["nullable"] else "")
                                   + (" (PK)" if col["is_pk"] else ""),
                    "tests": col_tests,
                })
            tables_data.append({
                "name": tbl["name"],
                "label": tbl["label"],
                "columns": cols_data,
            })

        content = template.render(
            source_name=source_name,
            system_label=sys["system_label"],
            database=sys["database"],
            schema=sys["schema"],
            tables=tables_data,
        )
        path = f"models/staging/{source_name}/_{source_name}__sources.yml"
        artifacts[path] = content

    return artifacts


def _gen_staging_models(
    systems: list[dict],
    mappings: dict,
    env: Environment,
    meta: dict,
) -> dict[str, str]:
    """Generate ``stg_{source}__{table}.sql`` staging models."""
    artifacts: dict[str, str] = {}
    template = env.get_template("staging_model.sql.jinja2")

    for sys in systems:
        source_name = _camel_to_snake(sys["system_label"]).replace(" ", "_")

        for tbl in sys["tables"]:
            tbl_uri = tbl["uri"]
            tbl_map = mappings["table_maps"].get(tbl_uri, {})

            columns_data = []
            for col in tbl["columns"]:
                col_uri = col["uri"] if "uri" in col else ""
                col_map = mappings["column_maps"].get(col_uri, {})

                # Use explicit transform if available, else default cast
                if col_map.get("transform"):
                    expr = col_map["transform"].replace("source.", "")
                else:
                    spark_type = _source_type_to_spark(col["data_type"])
                    if spark_type == "STRING":
                        expr = col["name"]
                    else:
                        expr = f"CAST({col['name']} AS {spark_type})"

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
            content = template.render(
                source_name=source_name,
                table_name=snake_table,
                system_label=sys["system_label"],
                raw_table_name=tbl["name"],
                columns=columns_data,
                filter_condition=tbl_map.get("filter_condition"),
                dedup_key=tbl_map.get("dedup_key"),
                dedup_order=tbl_map.get("dedup_order"),
                ontology_metadata=meta,
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
) -> dict[str, str]:
    """Generate silver entity models that read from staging."""
    artifacts: dict[str, str] = {}
    template = env.get_template("silver_model.sql.jinja2")

    schema_name = f"silver_{ontology_name}"

    # Build reverse map: silver class URI → [(source_name, stg_model_name)]
    class_to_staging: dict[str, list[tuple[str, str]]] = {}
    for sys in systems:
        source_name = _camel_to_snake(sys["system_label"]).replace(" ", "_")
        for tbl in sys["tables"]:
            tbl_map = mappings["table_maps"].get(tbl["uri"], {})
            target = tbl_map.get("target_uri")
            if target:
                snake_table = _camel_to_snake(tbl["name"])
                stg_name = f"stg_{source_name}__{snake_table}"
                class_to_staging.setdefault(target, []).append((source_name, stg_name))

    for cls in classes:
        cls_uri = cls["uri"]
        local = cls["name"]
        model_name = _camel_to_snake(local)

        staging_refs = class_to_staging.get(cls_uri, [])
        if not staging_refs:
            logger.info("No bronze mapping for %s — generating passthrough model", local)
            # Still generate a placeholder model
            staging_refs = [(ontology_name, f"stg_{ontology_name}__{model_name}")]

        # Extract properties for column list
        columns = _extract_silver_columns(graph, cls_uri, namespace, mappings)

        source_ctes = []
        for i, (src, stg) in enumerate(staging_refs):
            alias = stg if len(staging_refs) == 1 else f"src_{i + 1}"
            source_ctes.append({"model": stg, "alias": alias})

        content = template.render(
            model_name=model_name,
            domain_name=ontology_name,
            schema_name=schema_name,
            materialization="table",
            source_ctes=source_ctes,
            columns=columns,
            joins=[],
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
) -> list[dict]:
    """Extract silver-layer columns for a class from the ontology graph."""
    columns: list[dict] = []

    # SK column
    model_name = _camel_to_snake(extract_local_name(class_uri))
    columns.append({"expression": f"CAST(NULL AS STRING)", "target_name": f"{model_name}_sk"})
    columns.append({"expression": f"CAST(NULL AS STRING)", "target_name": f"{model_name}_iri"})

    # Datatype properties
    for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain and str(domain) == class_uri:
            prop_name = extract_local_name(str(prop))
            col_name = _camel_to_snake(prop_name)
            range_uri = graph.value(prop, RDFS.range)
            spark_type = _XSD_TO_SPARK.get(str(range_uri), "STRING") if range_uri else "STRING"

            # Check if there's a SKOS mapping transform for this property
            expr = col_name
            for col_uri, col_map in mappings.get("column_maps", {}).items():
                if col_map.get("target_uri") == str(prop):
                    if col_map.get("transform"):
                        expr = col_map["transform"].replace("source.", "")
                    break

            columns.append({"expression": expr, "target_name": col_name})

    return columns


def _gen_schema_yaml(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    shapes_dir: Optional[Path],
    env: Environment,
    ontology_name: str,
    meta: dict,
) -> dict[str, str]:
    """Generate ``_models.yml`` with column descriptions and SHACL tests."""
    artifacts: dict[str, str] = {}
    template = env.get_template("schema_models.yml.jinja2")

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
                data_type = _XSD_TO_SPARK.get(str(range_uri), "STRING") if range_uri else "STRING"

                tests = shacl_tests.get(col_name, [])
                cols.append({
                    "name": col_name,
                    "description": desc,
                    "meta": {"data_type": data_type},
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
) -> dict[str, str]:
    """Generate ``dbt_project.yml`` and ``packages.yml``."""
    artifacts: dict[str, str] = {}

    sources = [
        {"name": _camel_to_snake(s["system_label"]).replace(" ", "_")}
        for s in systems
    ]
    domains = [{"name": n} for n in ontology_names]

    proj_template = env.get_template("dbt_project.yml.jinja2")
    artifacts["dbt_project.yml"] = proj_template.render(
        project_name=project_name,
        sources=sources,
        domains=domains,
        gold_domains=gold_domains or [],
    )

    pkg_template = env.get_template("packages.yml.jinja2")
    artifacts["packages.yml"] = pkg_template.render()

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

    # 1. Sources YAML
    if systems:
        artifacts.update(_gen_sources(systems, env))
        print(f"    ✓ Generated {len(systems)} source definition(s)")

    # 2. Staging models
    if systems:
        staging = _gen_staging_models(systems, mappings, env, meta)
        artifacts.update(staging)
        print(f"    ✓ Generated {len(staging)} staging model(s)")

    # 3. Silver entity models
    silver = _gen_silver_models(
        classes, graph, namespace, systems, mappings, env, meta, onto_name,
    )
    artifacts.update(silver)
    print(f"    ✓ Generated {len(silver)} silver model(s)")

    # 4. Schema YAML with SHACL tests
    schema = _gen_schema_yaml(
        classes, graph, namespace, shapes_dir, env, onto_name, meta,
    )
    artifacts.update(schema)

    # 5. Project config (only once per domain — orchestrator handles multi-domain)
    has_gold = False
    if systems:
        # 6. Gold entity models (thick gold — pre-materialized star schema)
        gold = _gen_gold_models(
            classes, graph, namespace, shapes_dir, onto_name, gold_ext_path, env, meta,
        )
        artifacts.update(gold)
        has_gold = len(gold) > 0
        if gold:
            print(f"    ✓ Generated {len(gold)} gold model(s)")

        # 7. Gold schema YAML with tests
        gold_schema = _gen_gold_schema_yaml(
            classes, graph, namespace, shapes_dir, onto_name, gold_ext_path, env, meta,
        )
        artifacts.update(gold_schema)

        gold_domains = [{"name": onto_name}] if has_gold else []
        project = _gen_project_config(
            systems, [onto_name], env, f"{onto_name}_project",
            gold_domains=gold_domains,
        )
        artifacts.update(project)

    return artifacts
