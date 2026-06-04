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
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef, XSD, RDFS, SKOS
from rdflib.namespace import OWL, RDF
from jinja2 import Environment, FileSystemLoader

from .uri_utils import camel_to_snake, extract_local_name
from .shared import KAIROS_EXT, merge_ext_graph, str_val, bool_val

logger = logging.getLogger(__name__)


def _prefixed_iri(uri: str) -> str:
    """Derive a compact prefixed IRI from a full URI.

    Given ``https://acme.example/ontology/party#website``, returns ``party:website``.
    """
    local = extract_local_name(uri)
    if "#" in uri:
        ns = uri.rsplit("#", 1)[0]
    elif "/" in uri:
        ns = uri.rsplit("/", 1)[0]
    else:
        return local
    prefix = ns.rsplit("/", 1)[-1] if "/" in ns else ns
    return f"{prefix}:{local}"


def _resolve_qname(uri: str, ns_bindings: dict[str, str] | None = None) -> str:
    """Resolve a URI to a prefixed form using declared namespace bindings.

    Tries declared prefixes first (e.g., ``bronze-ap:col_name``), falls back to
    ``_prefixed_iri()`` if no matching binding found.
    """
    if not ns_bindings:
        return _prefixed_iri(uri)
    for prefix, ns_uri in ns_bindings.items():
        if uri.startswith(ns_uri):
            local = uri[len(ns_uri):]
            return f"{prefix}:{local}"
    return _prefixed_iri(uri)

# Module-level cache for entity metadata (populated by generate_dbt_artifacts,
# read by projector.py via get_last_entity_metadata)
_last_entity_metadata: dict[str, list[dict]] = {}


def get_last_entity_metadata() -> dict[str, list[dict]]:
    """Return cached entity metadata from the last generate_dbt_artifacts call.

    Returns:
        Dict of {domain_name: [entity_meta_dicts]}.
    """
    return dict(_last_entity_metadata)

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")

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

# T-SQL reserved keywords that must be bracket-quoted when used as identifiers.
# This list covers the most commonly encountered keywords in bronze source columns.
_TSQL_RESERVED_KEYWORDS: set[str] = {
    "function", "key", "value", "index", "table", "column", "user", "role",
    "order", "group", "type", "status", "date", "time", "level", "check",
    "default", "select", "insert", "update", "delete", "create", "drop",
    "alter", "grant", "revoke", "execute", "view", "procedure", "trigger",
    "constraint", "primary", "foreign", "references", "identity", "schema",
    "database", "transaction", "commit", "rollback", "cursor", "open",
    "close", "fetch", "option", "plan", "rule", "system", "backup",
}


def _quote_identifier_if_reserved(name: str) -> str:
    """Wrap an identifier in a kairos_quote_identifier macro call if it's a reserved keyword."""
    if name.lower() in _TSQL_RESERVED_KEYWORDS:
        return "{{ kairos_quote_identifier('" + name + "') }}"
    return name


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
        except (SyntaxError, Exception) as exc:
            logger.warning("Could not parse vocabulary file %s: %s", ttl.name, exc)
            continue

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

def _parse_split_annotations(mappings_dir: Path) -> dict[tuple[str, str], dict]:
    """Pre-parse mapping TTL files by statement block to resolve split ambiguity.

    Standard RDF parsing merges all triples for the same subject, making it
    impossible to correlate which ``kairos-map:filterCondition`` belongs to which
    ``skos:exactMatch`` target when multiple split entries share a subject.

    This function parses the raw Turtle text by statement block (terminated by
    ``'.'``) so each block's annotations stay isolated.

    Returns a dict keyed by ``(subject_uri, target_uri)`` with per-entry
    annotations::

        {("bronze:tblX", "ex:ClassA"): {"filter_condition": "...", ...}, ...}
    """
    result: dict[tuple[str, str], dict] = {}
    if not mappings_dir or not mappings_dir.is_dir():
        return result

    skos_match_uris = {
        str(SKOS.exactMatch), str(SKOS.closeMatch), str(SKOS.narrowMatch),
        str(SKOS.broadMatch), str(SKOS.relatedMatch),
    }

    for ttl_path in sorted(mappings_dir.rglob("*.ttl")):
        try:
            content = ttl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Could not read mapping file %s: %s", ttl_path.name, exc)
            continue

        # Extract prefix lines (needed to parse each block independently)
        lines = content.split("\n")
        prefix_lines: list[str] = []
        body_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("@prefix") or stripped.startswith("@base"):
                prefix_lines.append(line)
            else:
                body_lines.append(line)

        prefix_block = "\n".join(prefix_lines) + "\n"
        body = "\n".join(body_lines)

        # Split body into statement blocks (each terminated by '.').
        # LIMITATION: This regex can incorrectly split on periods inside string
        # literals that happen to precede a newline. In practice, Kairos mapping
        # files use short IRIs and identifiers (not prose sentences), so this
        # rarely triggers. A proper fix would require a Turtle tokenizer.
        statements = re.split(r"\.\s*(?=\n|$)", body)

        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue

            # Parse this single statement block
            try:
                block_g = Graph()
                block_g.parse(data=prefix_block + stmt + " .", format="turtle")
            except Exception as exc:
                logger.debug("Skipping unparseable mapping block in %s: %s",
                             ttl_path.name, exc)
                continue

            # Look for table-level mappings in this block
            for subj, pred, obj in block_g:
                pred_str = str(pred)
                if pred_str not in skos_match_uris:
                    continue
                # Found a SKOS match — check if it has mapping annotations
                mapping_type = block_g.value(subj, KAIROS_MAP.mappingType)
                if mapping_type is None:
                    continue
                filt = block_g.value(subj, KAIROS_MAP.filterCondition)
                dedup_key = block_g.value(subj, KAIROS_MAP.deduplicationKey)
                dedup_order = block_g.value(subj, KAIROS_MAP.deduplicationOrder)
                result[(str(subj), str(obj))] = {
                    "filter_condition": str(filt) if filt else None,
                    "dedup_key": str(dedup_key) if dedup_key else None,
                    "dedup_order": str(dedup_order) if dedup_order else None,
                }

    return result


def _parse_skos_mappings(mappings_dir: Path) -> tuple[dict, dict[str, str]]:
    """Parse SKOS + kairos-map: mappings and return structured mapping data.

    Returns a tuple of (mappings_dict, ns_bindings):

    mappings_dict::

        {
            "table_maps": {bronze_table_uri: [{
                "target_uri": silver_class_uri,
                "mapping_type": "direct" | "split" | "merge",
                "filter_condition": str | None,
                "dedup_key": str | None,
                "dedup_order": str | None,
            }, ...]},
            "column_maps": {bronze_col_uri: [{
                "target_uri": silver_property_uri,
                "match_type": "exactMatch" | "closeMatch" | "narrowMatch" | ...,
                "transform": str | None,
                "source_columns": [str] | None,
                "default_value": str | None,
            }, ...]}
        }

    ns_bindings: dict mapping prefix → namespace URI from the mapping files.

    Note: Both ``table_maps`` and ``column_maps`` values are **lists** to support
    one-to-many patterns (split: one table → multiple classes; multi-target: one
    column → multiple properties).
    """
    result: dict = {"table_maps": {}, "column_maps": {}}
    ns_bindings: dict[str, str] = {}
    if not mappings_dir or not mappings_dir.is_dir():
        return result, ns_bindings

    # Pre-parse to resolve per-target annotations for split patterns
    split_annotations = _parse_split_annotations(mappings_dir)

    g = Graph()
    for ttl in sorted(mappings_dir.rglob("*.ttl")):
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
                    # Table-level mapping (list to support 1:N split pattern)
                    # Use per-block annotations if available (handles split correctly)
                    annotations = split_annotations.get((subj_str, obj_str), {})
                    filt = annotations.get("filter_condition")
                    dedup_key = annotations.get("dedup_key")
                    dedup_order = annotations.get("dedup_order")

                    # Fall back to g.value() for single-target (non-split) cases
                    if filt is None:
                        v = g.value(subj, KAIROS_MAP.filterCondition)
                        filt = str(v) if v else None
                    if dedup_key is None:
                        v = g.value(subj, KAIROS_MAP.deduplicationKey)
                        dedup_key = str(v) if v else None
                    if dedup_order is None:
                        v = g.value(subj, KAIROS_MAP.deduplicationOrder)
                        dedup_order = str(v) if v else None

                    result["table_maps"].setdefault(subj_str, []).append({
                        "target_uri": obj_str,
                        "mapping_type": str(mapping_type),
                        "filter_condition": filt,
                        "dedup_key": dedup_key,
                        "dedup_order": dedup_order,
                    })
                else:
                    # Column-level mapping (list to support 1:N multi-target)
                    src_cols = g.value(subj, KAIROS_MAP.sourceColumns)
                    default = g.value(subj, KAIROS_MAP.defaultValue)
                    result["column_maps"].setdefault(subj_str, []).append({
                        "target_uri": obj_str,
                        "match_type": match_name,
                        "transform": str(transform) if transform else None,
                        "source_columns": str(src_cols).split() if src_cols else None,
                        "default_value": str(default) if default else None,
                    })

    # Extract declared namespace bindings from mapping files
    for prefix, ns_uri in g.namespaces():
        if prefix:  # skip default namespace
            ns_bindings[prefix] = str(ns_uri)

    return result, ns_bindings


# ---------------------------------------------------------------------------
# SHACL → dbt test extraction
# ---------------------------------------------------------------------------

def _load_shacl_graph(shapes_dir: Path) -> Graph | None:
    """Load all SHACL files from shapes_dir into a single graph (cached per call).

    Returns None if no shapes were loaded.
    """
    if not shapes_dir or not shapes_dir.exists():
        return None

    sg = Graph()
    loaded = False
    for sf in sorted(shapes_dir.glob("*.ttl")):
        try:
            sg.parse(sf, format="turtle")
            loaded = True
        except Exception as exc:
            logger.debug("Could not parse SHACL file %s: %s", sf.name, exc)
    return sg if loaded else None


def _extract_shacl_tests(shapes_dir: Path, class_uri: str,
                          shacl_graph: Graph | None = None) -> dict[str, list]:
    """Extract dbt tests from SHACL shapes for a given class.

    Args:
        shapes_dir: Path to shapes directory (used only if shacl_graph is None).
        class_uri: URI of the class to extract tests for.
        shacl_graph: Pre-parsed SHACL graph. If provided, avoids re-parsing.

    Returns ``{column_name: [test_strings]}``.
    """
    if not shapes_dir or not shapes_dir.exists():
        return {}

    target_class = URIRef(class_uri)

    # Use provided graph or load (backward-compatible)
    if shacl_graph is not None:
        sg = shacl_graph
    else:
        class_name = extract_local_name(class_uri)
        candidates = [
            shapes_dir / f"{class_name.lower()}.shacl.ttl",
            shapes_dir / f"{class_name.lower()}-shapes.ttl",
        ]
        all_shapes = list(shapes_dir.glob("*.ttl"))
        sg = Graph()
        loaded = False
        for candidate in candidates:
            if candidate.exists():
                try:
                    sg.parse(candidate, format="turtle")
                    loaded = True
                except Exception as exc:
                    logger.warning("Could not parse SHACL file %s: %s", candidate.name, exc)
                break
        if not loaded:
            for sf in all_shapes:
                try:
                    sg.parse(sf, format="turtle")
                    loaded = True
                except Exception as exc:
                    logger.debug("Could not parse SHACL file %s: %s", sf.name, exc)
                    continue
        if not loaded:
            return {}

    tests_by_col: dict[str, list] = {}

    # Find property shapes that target this class (directly or via NodeShape)
    for node_shape in sg.subjects(RDF.type, SH.NodeShape):
        shape_target = sg.value(node_shape, SH.targetClass)
        if shape_target and str(shape_target) != str(target_class):
            continue
        for ps in sg.objects(node_shape, SH.property):
            _extract_property_shape_tests(sg, ps, tests_by_col)

    # Also handle property shapes attached via sh:property without NodeShape typing
    for ps in sg.objects(predicate=SH.property):
        path = sg.value(ps, SH.path)
        if not path:
            continue
        col_name = _camel_to_snake(extract_local_name(str(path)))
        if col_name in tests_by_col:
            continue  # already extracted via NodeShape path
        # Check if this property shape belongs to a shape targeting our class
        for subj in sg.subjects(SH.property, ps):
            shape_target = sg.value(subj, SH.targetClass)
            if shape_target and str(shape_target) == str(target_class):
                _extract_property_shape_tests(sg, ps, tests_by_col)
                break

    return tests_by_col


def _extract_property_shape_tests(
    sg: Graph, ps, tests_by_col: dict[str, list]
) -> None:
    """Extract dbt tests from a single SHACL property shape node."""
    path = sg.value(ps, SH.path)
    if not path:
        return
    col_name = _camel_to_snake(extract_local_name(str(path)))
    if col_name in tests_by_col:
        return  # already processed

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


# ---------------------------------------------------------------------------
# Artifact generators
# ---------------------------------------------------------------------------

def _gen_sources(
    systems: list[dict], env: Environment, mappings: dict,
    logical_sources_only: bool = False,
) -> dict[str, str]:
    """Generate a single minimal ``_sources.yml`` under ``models/silver/``.

    The sources YAML is intentionally minimal — it declares only database,
    schema, and table names so dbt can generate ``{{ source() }}`` references.
    Column-level documentation lives in the vocabulary TTL (the authoritative
    source of bronze table structure), not in the dbt sources YAML.

    Only tables that have at least one mapping to a domain class are included.

    When *logical_sources_only* is True, the generated sources omit ``database``
    and ``schema`` fields — physical binding is expected to be defined in the
    downstream dataplatform repo's own ``_sources.yml``.
    """
    artifacts: dict[str, str] = {}
    template = env.get_template("sources.yml.jinja2")
    mapped_table_uris = set(mappings.get("table_maps", {}).keys())

    for sys in systems:
        source_name = _camel_to_snake(sys["system_label"]).replace(" ", "_")
        tables_data = []
        for tbl in sys["tables"]:
            if mapped_table_uris and tbl["uri"] not in mapped_table_uris:
                continue
            tables_data.append({
                "name": tbl["name"],
                "label": tbl["label"],
            })

        if not tables_data:
            continue

        content = template.render(
            source_name=source_name,
            system_label=sys["system_label"],
            database=sys["database"],
            schema=sys["schema"],
            tables=tables_data,
            logical_sources_only=logical_sources_only,
        )
        path = f"models/silver/_{source_name}__sources.yml"
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
    mapping_ns: dict[str, str] | None = None,
) -> tuple[dict[str, str], list[str], list[dict]]:
    """Generate silver entity models that read directly from bronze sources.

    Enforces layer contracts:
    - Silver models consume bronze tables via source() — no staging layer
    - Every source() must point to a declared bronze source table
    - Unmapped classes are skipped with a warning (no broken placeholders)
    - Silver absorbs rename, cast, and transform logic (previously in staging)

    Returns:
        Tuple of (artifacts dict, warnings list, entity_metadata list).
        Each entity_metadata entry: {class_name, model_file, scd_type,
        source_count, column_count, fk_join_count, skipped, skip_reason}.
    """
    artifacts: dict[str, str] = {}
    warnings: list[str] = []
    entity_metadata: list[dict] = []
    template = env.get_template("silver_model.sql.jinja2")

    schema_name = f"silver_{ontology_name}"

    # Build reverse map: silver class URI → [(source_name, raw_table_name, table_uri)]
    SUPPORTED_MAPPING_TYPES = {"direct", "split", "merge"}
    class_to_sources: dict[str, list[tuple[str, str, str]]] = {}
    for sys in systems:
        source_name = _camel_to_snake(sys["system_label"]).replace(" ", "_")
        for tbl in sys["tables"]:
            for tbl_map in mappings["table_maps"].get(tbl["uri"], []):
                target = tbl_map.get("target_uri")
                if not target:
                    continue
                mtype = tbl_map.get("mapping_type", "direct")
                if mtype not in SUPPORTED_MAPPING_TYPES:
                    tbl_local = extract_local_name(tbl["uri"])
                    target_local = extract_local_name(target)
                    msg = (
                        f"Unsupported mappingType '{mtype}' on "
                        f"'{tbl_local}' → '{target_local}' — skipping. "
                        f"Supported types: {', '.join(sorted(SUPPORTED_MAPPING_TYPES))}."
                    )
                    logger.warning(msg)
                    warnings.append(msg)
                    continue
                class_to_sources.setdefault(target, []).append(
                    (source_name, tbl["name"], tbl["uri"])
                )

    for cls in classes:
        cls_uri = cls["uri"]
        local = cls["name"]
        model_name = _camel_to_snake(local)

        source_refs = class_to_sources.get(cls_uri, [])
        if not source_refs:
            # Check if this class is a discriminator subclass (S3-flattened into parent)
            is_discriminator_subclass = False
            parent_name = None
            for parent in graph.objects(URIRef(cls_uri), RDFS.subClassOf):
                if not isinstance(parent, URIRef):
                    continue
                if str(parent).startswith("http://www.w3.org/"):
                    continue
                strategy = graph.value(parent, KAIROS_EXT.inheritanceStrategy)
                if strategy and str(strategy) == "discriminator":
                    is_discriminator_subclass = True
                    parent_name = extract_local_name(str(parent))
                    break

            if is_discriminator_subclass:
                logger.info(
                    f"Class '{local}' flattened into parent '{parent_name}' via "
                    f"S3 discriminator strategy — no separate silver model needed."
                )
                entity_metadata.append({
                    "class_name": local,
                    "class_uri": cls_uri,
                    "model_file": None,
                    "scd_type": None,
                    "source_count": 0,
                    "column_count": 0,
                    "column_names": [],
                    "fk_join_count": 0,
                    "skipped": True,
                    "skip_reason": f"S3 discriminator subclass of {parent_name}",
                })
                continue

            msg = (
                f"No bronze mapping for class '{local}' — skipping silver model. "
                f"Resolve via: kairos-design-mapping"
            )
            logger.warning(msg)
            warnings.append(msg)
            entity_metadata.append({
                "class_name": local,
                "class_uri": cls_uri,
                "model_file": None,
                "scd_type": None,
                "source_count": 0,
                "column_count": 0,
                "column_names": [],
                "fk_join_count": 0,
                "skipped": True,
                "skip_reason": "No bronze mapping found",
            })
            continue

        # Check for missing naturalKey — critical for SK and IRI generation
        natural_key_cols = _get_natural_key(graph, cls_uri)
        if not natural_key_cols:
            fk_parents = _fk_child_parents(graph, cls_uri)
            if fk_parents:
                msg = (
                    f"Class '{local}' has no kairos-ext:naturalKey and is an "
                    f"FK-child of {', '.join(fk_parents)} (via "
                    f"kairos-ext:silverForeignKeyOn) — its surrogate key and IRI "
                    f"will be NULL. If this is a weak entity, add a "
                    f"kairos-ext:naturalKey for its composite business key (e.g. "
                    f"a type/discriminator column distinguishing rows under the "
                    f"same parent); if it has its own source identity, add that "
                    f"key; if it is purely embedded, consider denormalising it "
                    f"onto the parent table. Resolve via: kairos-design-silver"
                )
            else:
                msg = (
                    f"Class '{local}' has no kairos-ext:naturalKey — "
                    f"SK and IRI columns will be NULL. "
                    f"Resolve via: kairos-design-silver"
                )
            logger.warning(msg)
            warnings.append(msg)

        # DD-039: Check for silverSourceRef (bronze_expanded staging model override)
        silver_source_ref = str_val(
            graph, URIRef(cls_uri), KAIROS_EXT.silverSourceRef
        )

        # ----- Multi-source: generate per-source views + union model -----
        if len(source_refs) > 1:
            source_model_names: list[str] = []
            source_template = env.get_template("silver_source_model.sql.jinja2")
            union_template = env.get_template("silver_union_model.sql.jinja2")

            # Detect same-source collisions requiring table-name disambiguation
            source_system_counts = Counter(src for src, _, _ in source_refs)
            needs_table_suffix = {
                src for src, count in source_system_counts.items() if count > 1
            }

            for i, (src, raw_tbl, tbl_uri) in enumerate(source_refs):
                src_suffix = _camel_to_snake(src)
                if src in needs_table_suffix:
                    tbl_suffix = _camel_to_snake(raw_tbl.split(".")[-1])
                    src_model_name = f"{model_name}__from_{src_suffix}__{tbl_suffix}"
                else:
                    src_model_name = f"{model_name}__from_{src_suffix}"
                source_model_names.append(src_model_name)

                # Get the set of column URIs for this specific source table
                tbl_col_uris = _get_table_column_uris(systems, tbl_uri)

                # Extract columns scoped to this source (no SK/IRI)
                src_columns = _extract_silver_columns(
                    graph, cls_uri, namespace, mappings, platform=platform,
                    source_refs=source_refs, systems=systems,
                    table_column_uris=tbl_col_uris, include_sk_iri=False,
                    mapping_ns=mapping_ns,
                )

                # Resolve filter condition
                cte_filter = ""
                tbl_maps_list = mappings["table_maps"].get(tbl_uri, [])
                for tbl_map in tbl_maps_list:
                    if (tbl_map.get("target_uri") == cls_uri
                            and tbl_map.get("filter_condition")):
                        cte_filter = tbl_map["filter_condition"].replace("source.", "")
                        break

                content = source_template.render(
                    model_name=src_model_name,
                    domain_name=ontology_name,
                    schema_name=schema_name,
                    source_name=src,
                    raw_table_name=raw_tbl,
                    columns=src_columns,
                    filter_condition=cte_filter,
                    parent_model=model_name,
                    ref_model=silver_source_ref or None,
                    ontology_metadata=meta,
                )
                path = f"models/silver/{ontology_name}/{src_model_name}.sql"
                artifacts[path] = content

            # Build SK/IRI expressions for the union model (uses normalised cols)
            sk_expr = _build_sk_expression(graph, cls_uri)
            iri_expr = _build_iri_expression(graph, cls_uri, namespace)

            # Collect the normalised target column names (without SK/IRI)
            # Use the first source's columns as the canonical list of target names
            first_tbl_col_uris = _get_table_column_uris(
                systems, source_refs[0][2]
            )
            canonical_columns = _extract_silver_columns(
                graph, cls_uri, namespace, mappings, platform=platform,
                source_refs=source_refs, systems=systems,
                table_column_uris=first_tbl_col_uris, include_sk_iri=False,
                mapping_ns=mapping_ns,
            )

            # FK joins in union model (applied on normalised column names)
            fk_columns, fk_joins, fk_warnings = _extract_fk_columns_and_joins(
                graph, cls_uri, mappings, source_refs, systems=systems,
            )
            warnings.extend(fk_warnings)

            content = union_template.render(
                model_name=model_name,
                domain_name=ontology_name,
                schema_name=schema_name,
                materialization="table",
                source_models=source_model_names,
                columns=canonical_columns,
                sk_expression=sk_expr,
                iri_expression=iri_expr,
                joins=fk_columns,
                ontology_metadata=meta,
            )
            path = f"models/silver/{ontology_name}/{model_name}.sql"
            artifacts[path] = content
            entity_metadata.append({
                "class_name": local,
                "class_uri": cls_uri,
                "model_file": f"{model_name}.sql",
                "scd_type": "2",
                "source_count": len(source_refs),
                "column_count": len(canonical_columns),
                "column_names": [c["target_name"] for c in canonical_columns],
                "fk_join_count": len(fk_joins) if fk_joins else 0,
                "skipped": False,
                "skip_reason": None,
            })
            continue

        # ----- Single source: existing inline model -----
        # Read SCD type annotation (default: "2" for regular entities, "1" for reference)
        is_ref = bool_val(graph, URIRef(cls_uri), KAIROS_EXT.isReferenceData, False)
        scd_type = str_val(
            graph, URIRef(cls_uri), KAIROS_EXT.scdType, "1" if is_ref else "2"
        )

        # Extract properties for column list with platform-aware types.
        # Scope to primary table columns so inherited properties from other
        # source tables are excluded (they would require a JOIN to resolve).
        primary_col_uris = _get_table_column_uris(systems, source_refs[0][2])
        columns = _extract_silver_columns(
            graph, cls_uri, namespace, mappings, platform=platform,
            source_refs=source_refs, systems=systems,
            table_column_uris=primary_col_uris or None,
            mapping_ns=mapping_ns,
        )

        # Cross-table column detection: warn if mapped columns reference source
        # tables other than the primary source (would require a JOIN to resolve).
        # Only warn for properties that belong to THIS class's domain (avoids
        # noise from mappings targeting other entities in the same source system).
        if systems and source_refs and len(source_refs) == 1:
            primary_tbl_uri = source_refs[0][2]
            primary_col_uris = _get_table_column_uris(systems, primary_tbl_uri)
            # Collect property URIs whose domain matches this class
            domain_classes = _get_class_and_parents(graph, cls_uri)
            domain_prop_uris: set[str] = set()
            for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
                prop_domain = graph.value(prop, RDFS.domain)
                if prop_domain and str(prop_domain) in domain_classes:
                    domain_prop_uris.add(str(prop))
            # Also include object properties (for FK references)
            for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
                prop_domain = graph.value(prop, RDFS.domain)
                if prop_domain and str(prop_domain) in domain_classes:
                    domain_prop_uris.add(str(prop))

            if primary_col_uris:
                for col_uri, col_maps_list in mappings.get("column_maps", {}).items():
                    for col_map in col_maps_list:
                        target_uri = col_map.get("target_uri")
                        if target_uri and target_uri in domain_prop_uris:
                            if col_uri not in primary_col_uris:
                                target_prop = extract_local_name(target_uri)
                                source_col = extract_local_name(col_uri)
                                warnings.append(
                                    f"Cross-table reference in '{local}': "
                                    f"column '{source_col}' mapped to "
                                    f"'{target_prop}' belongs to a different "
                                    f"source table — model may need a JOIN."
                                )

        # Extract FK columns from object properties (cross-domain joins)
        fk_columns, fk_joins, fk_warnings = _extract_fk_columns_and_joins(
            graph, cls_uri, mappings, source_refs, systems=systems,
        )
        warnings.extend(fk_warnings)

        # Build source CTEs that reference bronze tables directly
        # (or bronze_expanded via ref() when silverSourceRef is set — DD-039)
        source_ctes = []
        filter_conditions = []
        for i, (src, raw_tbl, tbl_uri) in enumerate(source_refs):
            alias = _camel_to_snake(raw_tbl) if len(source_refs) == 1 else f"src_{i + 1}"
            # Resolve per-CTE filter condition
            cte_filter = ""
            tbl_maps_list = mappings["table_maps"].get(tbl_uri, [])
            for tbl_map in tbl_maps_list:
                if tbl_map.get("target_uri") == cls_uri and tbl_map.get("filter_condition"):
                    cte_filter = tbl_map["filter_condition"].replace("source.", "")
                    filter_conditions.append(cte_filter)
                    break
            cte = {
                "source_name": src,
                "table_name": raw_tbl,
                "alias": alias,
                "filter": cte_filter,
                "ref_model": silver_source_ref or None,
            }
            source_ctes.append(cte)

        # When FK JOINs are present, qualify unqualified column expressions with
        # the primary source alias to prevent ambiguous references in T-SQL.
        if fk_joins and source_ctes:
            primary_alias = source_ctes[0]["alias"]
            for col in columns:
                expr = col["expression"]
                # Only qualify simple column references (no dots, parens, or spaces)
                # Skip SK/IRI/NULL expressions and already-qualified references
                if (
                    "." not in expr
                    and "(" not in expr
                    and " " not in expr
                    and "{{" not in expr
                    and expr != "CAST(NULL"
                    and not expr.startswith("CAST(")
                    and not expr.startswith("COALESCE(")
                ):
                    col["expression"] = f"{primary_alias}.{expr}"

        columns.extend(fk_columns)

        # Filter conditions are embedded in each CTE via cte.filter.
        # No top-level WHERE needed — all filtering happens at the CTE level.
        where_clause = ""

        # Compute hash columns for SCD2 change detection (_row_hash)
        # Exclude: SK, IRI, temporal columns, _row_hash itself, FK columns
        _scd_temporal = {"valid_from", "valid_to", "is_current", "_row_hash"}
        _fk_target_names = {j.get("fk_column", "") for j in fk_joins} if fk_joins else set()
        hash_columns = [
            col["target_name"] for col in columns
            if col["target_name"] not in _scd_temporal
            and not col["target_name"].endswith("_sk")
            and not col["target_name"].endswith("_iri")
            and col["target_name"] not in _fk_target_names
        ]

        # Determine materialization and unique_key based on SCD type
        if scd_type == "2":
            materialization = "incremental"
            unique_key = [f"{model_name}_sk", "valid_from"]
        elif scd_type == "1":
            materialization = "incremental"
            unique_key = f"{model_name}_sk"
        else:
            materialization = "table"
            unique_key = ""

        content = template.render(
            model_name=model_name,
            domain_name=ontology_name,
            schema_name=schema_name,
            materialization=materialization,
            unique_key=unique_key,
            scd_type=scd_type,
            hash_columns=hash_columns,
            source_ctes=source_ctes,
            columns=columns,
            joins=fk_joins,
            where_clause=where_clause,
            ontology_metadata=meta,
        )
        path = f"models/silver/{ontology_name}/{model_name}.sql"
        artifacts[path] = content
        entity_metadata.append({
            "class_name": local,
            "class_uri": cls_uri,
            "model_file": f"{model_name}.sql",
            "scd_type": scd_type,
            "source_count": len(source_refs),
            "column_count": len(columns),
            "column_names": [c["target_name"] for c in columns],
            "fk_join_count": len(fk_joins) if fk_joins else 0,
            "skipped": False,
            "skip_reason": None,
        })

    return artifacts, warnings, entity_metadata


def _get_class_and_parents(graph: Graph, class_uri: str) -> set[str]:
    """Return the set of class URIs including the given class and all ancestors.

    Walks the rdfs:subClassOf chain upward, collecting all parent class URIs.
    This enables inheritance: properties defined on a parent class are included
    when generating models for a subclass.
    """
    result = {class_uri}
    current = URIRef(class_uri)
    visited = set()
    while current not in visited:
        visited.add(current)
        parent = graph.value(current, RDFS.subClassOf)
        if parent is None or str(parent) in result:
            break
        # Skip owl:Thing and other top-level classes
        if str(parent).startswith("http://www.w3.org/"):
            break
        result.add(str(parent))
        current = parent
    return result


def _get_table_column_uris(systems: list[dict], table_uri: str) -> set[str]:
    """Return the set of column URIs belonging to a specific bronze table."""
    result: set[str] = set()
    for sys in systems:
        for tbl in sys["tables"]:
            if tbl["uri"] == table_uri:
                for col in tbl["columns"]:
                    result.add(col["uri"])
    return result


def _build_sk_expression(
    graph: Graph, class_uri: str
) -> str:
    """Build the SK expression for a class, using normalised target column names."""
    natural_key_cols = _get_natural_key(graph, class_uri)
    if natural_key_cols:
        sk_cols_str = "', '".join(natural_key_cols)
        return f"{{{{ dbt_utils.generate_surrogate_key(['{sk_cols_str}']) }}}}"
    return "CAST(NULL AS {{ dbt_utils.type_string() }})"


def _build_iri_expression(
    graph: Graph, class_uri: str, namespace: str
) -> str:
    """Build the IRI expression for a class, using normalised target column names."""
    natural_key_cols = _get_natural_key(graph, class_uri)
    if natural_key_cols:
        if len(natural_key_cols) == 1:
            return (
                f"CONCAT('{namespace}', '{extract_local_name(class_uri)}/', "
                f"{natural_key_cols[0]})"
            )
        parts = ", '/', ".join(natural_key_cols)
        return (
            f"CONCAT('{namespace}', '{extract_local_name(class_uri)}/', {parts})"
        )
    return "CAST(NULL AS {{ dbt_utils.type_string() }})"


def _build_sk_iri_columns(
    graph: Graph,
    class_uri: str,
    namespace: str,
    natural_key_cols: list[str],
) -> list[dict]:
    """Build the SK and IRI column dicts for a silver model."""
    columns: list[dict] = []
    model_name = _camel_to_snake(extract_local_name(class_uri))

    # SK column: use surrogate key generation if natural key is known
    if natural_key_cols:
        sk_cols_str = "', '".join(natural_key_cols)
        sk_expr = f"{{{{ dbt_utils.generate_surrogate_key(['{sk_cols_str}']) }}}}"
    else:
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
            iri_expr = (
                f"CONCAT('{namespace}', '{extract_local_name(class_uri)}/', {parts})"
            )
    else:
        iri_expr = "CAST(NULL AS {{ dbt_utils.type_string() }})"

    columns.append({"expression": iri_expr, "target_name": f"{model_name}_iri"})
    return columns


def _resolve_mapped_columns(
    graph: Graph,
    class_uri: str,
    mappings: dict,
    platform: str,
    bronze_col_lookup: dict[str, dict],
    enum_lookup: dict[str, list[dict]],
    table_column_uris: set[str] | None = None,
    mapping_ns: dict[str, str] | None = None,
) -> list[dict]:
    """Resolve data columns from source mappings for a silver model.

    Iterates over datatype properties of the class, finds matching SKOS column
    mappings, applies type casting and defaults, and generates enum label columns.
    """
    columns: list[dict] = []

    # Collect domain classes: self + parent classes (for inheritance in split patterns)
    domain_classes = _get_class_and_parents(graph, class_uri)

    # Datatype properties (including inherited from parent classes)
    seen_col_names: set[str] = set()
    for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain and str(domain) in domain_classes:
            prop_name = extract_local_name(str(prop))
            col_name = _camel_to_snake(prop_name)
            # Deduplicate: skip if column already added (child overrides parent)
            if col_name in seen_col_names:
                continue
            seen_col_names.add(col_name)
            _range_uri = graph.value(prop, RDFS.range)
            # Use dbt_utils macros for portable silver types

            # Check population requirement from kairos-ext annotation
            pop_req = graph.value(URIRef(str(prop)), KAIROS_EXT.populationRequirement)
            population = str(pop_req) if pop_req else "optional"

            # Check if there's a SKOS mapping transform for this property
            expr = None
            mapped_col_uri = None
            matched_col_map = None
            for col_uri, col_maps_list in mappings.get("column_maps", {}).items():
                for col_map in col_maps_list:
                    if col_map.get("target_uri") == str(prop):
                        # If scoped to a specific source, skip column maps from other sources
                        if table_column_uris is not None and col_uri not in table_column_uris:
                            continue
                        mapped_col_uri = col_uri
                        matched_col_map = col_map
                        if col_map.get("transform"):
                            expr = col_map["transform"].replace("source.", "")
                        else:
                            # Direct mapping — use the original bronze column name
                            # with a TRY_CAST to the target type
                            bronze_col = bronze_col_lookup.get(col_uri)
                            if bronze_col:
                                src_type = bronze_col["data_type"]
                                target_type = _source_type_to_target(src_type, platform)
                                bronze_name = _quote_identifier_if_reserved(
                                    bronze_col["name"]
                                )
                                if target_type.startswith("VARCHAR") or target_type == "STRING":
                                    expr = bronze_name
                                else:
                                    expr = f"TRY_CAST({bronze_name} AS {target_type})"
                            else:
                                # Fallback: use URI local name
                                source_col_name = extract_local_name(col_uri)
                                expr = _quote_identifier_if_reserved(source_col_name)
                        break
                if mapped_col_uri:
                    break

            # Wrap in COALESCE if a default value is declared in the mapping
            if expr and matched_col_map:
                if matched_col_map.get("default_value"):
                    expr = f"COALESCE({expr}, {matched_col_map['default_value']})"

            if expr is None:
                if population == "derived":
                    # Check for derivation formula
                    formula = graph.value(
                        URIRef(str(prop)), KAIROS_EXT.derivationFormula
                    )
                    if formula:
                        expr = str(formula)
                    else:
                        # Derived without formula — skip (no source data)
                        continue
                else:
                    # Unmapped property with no source data — skip entirely.
                    # Only include columns that have a real bronze mapping.
                    continue

            # Build lineage comment: source skos:{matchType} target (mirrors SKOS triple)
            if mapped_col_uri and matched_col_map:
                match_type = matched_col_map.get("match_type", "exactMatch")
                source_qname = _resolve_qname(mapped_col_uri, mapping_ns)
                target_qname = _resolve_qname(str(prop), mapping_ns)
                lineage_comment = f"{source_qname} skos:{match_type} {target_qname}"
            else:
                lineage_comment = _resolve_qname(str(prop), mapping_ns)

            columns.append({
                "expression": expr,
                "target_name": col_name,
                "comment": lineage_comment,
            })

            # Generate _label column for enum-typed source columns
            if mapped_col_uri and mapped_col_uri in enum_lookup:
                enum_vals = enum_lookup[mapped_col_uri]
                case_expr = _build_enum_case(expr, enum_vals)
                columns.append({
                    "expression": case_expr,
                    "target_name": f"{col_name}_label",
                })

    return columns


def _extract_silver_columns(
    graph: Graph,
    class_uri: str,
    namespace: str,
    mappings: dict,
    platform: str = DEFAULT_PLATFORM,
    source_refs: list[tuple[str, str, str]] | None = None,
    systems: list[dict] | None = None,
    table_column_uris: set[str] | None = None,
    include_sk_iri: bool = True,
    mapping_ns: dict[str, str] | None = None,
) -> list[dict]:
    """Extract silver-layer columns for a class from the ontology graph.

    Since silver reads directly from bronze (no staging layer), column
    expressions reference original bronze column names and apply casts/transforms
    inline.  Transform expressions from SKOS mappings are used as-is; direct
    mappings reference the original bronze column name with appropriate casting.

    Args:
        table_column_uris: When provided, only column_maps whose source column
            URI is in this set are considered.  Used for per-source column
            extraction in multi-source scenarios.
        include_sk_iri: When False, SK and IRI columns are omitted.  Used for
            per-source models where SK/IRI are computed in the parent union model.

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

    if include_sk_iri:
        columns.extend(
            _build_sk_iri_columns(graph, class_uri, namespace, natural_key_cols)
        )

    # Resolve mapped data columns
    columns.extend(
        _resolve_mapped_columns(
            graph, class_uri, mappings, platform,
            bronze_col_lookup, enum_lookup, table_column_uris,
            mapping_ns=mapping_ns,
        )
    )

    # Validate that naturalKey columns are present in the generated column list.
    # If missing, add them as pass-through from the source table so that SK/IRI
    # expressions in the staged CTE can reference them.
    if natural_key_cols and include_sk_iri:
        col_names = {c["target_name"] for c in columns}
        missing = [nk for nk in natural_key_cols if nk not in col_names]
        if missing:
            class_name = extract_local_name(class_uri)
            logger.warning(
                "SK validation: naturalKey column(s) %s not found in model "
                "columns for %s — adding as pass-through",
                missing, class_name,
            )
            for nk_col in missing:
                # Attempt to find the source column name via bronze lookup
                # (natural key is snake_case of the property local name)
                columns.append({
                    "expression": nk_col,
                    "target_name": nk_col,
                })

    return columns


def _resolve_discriminated_model(graph: Graph, class_uri) -> tuple[str, str]:
    """Resolve a class to its effective model name, accounting for discriminator folding.

    If the class is a subclass of a parent with ``inheritanceStrategy "discriminator"``,
    the subclass is folded into the parent table — return the parent's model name.
    Otherwise return the class's own model name.

    Returns (model_name, local_name) for the resolved target.
    """
    cls_local = extract_local_name(str(class_uri))
    cls_model = _camel_to_snake(cls_local)

    # Walk up the subClassOf chain looking for a discriminator parent
    for parent in graph.objects(URIRef(str(class_uri)), RDFS.subClassOf):
        strategy = graph.value(parent, KAIROS_EXT.inheritanceStrategy)
        if strategy and str(strategy) == "discriminator":
            parent_local = extract_local_name(str(parent))
            parent_model = _camel_to_snake(parent_local)
            return parent_model, parent_local

    return cls_model, cls_local


def _infer_fk_targets(
    graph: Graph,
    class_uri: str,
) -> list[dict]:
    """Identify qualifying FK object properties for a class.

    A property qualifies as a FK column when ANY of:
      - it has an explicit ``kairos-ext:silverColumnName`` annotation,
      - it is declared ``owl:FunctionalProperty``,
      - it has ``kairos-ext:silverForeignKey true`` (DD-022).

    Properties with ``kairos-ext:silverForeignKeyOn`` that redirect the FK to
    a different class are skipped (the FK belongs on the target class, not here).

    Returns a list of dicts with keys: prop, range_cls, range_local, range_model,
    fk_col_name.
    """
    domain_classes = _get_class_and_parents(graph, class_uri)
    targets: list[dict] = []

    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain is None or str(domain) not in domain_classes:
            continue

        # Skip junction-table properties (many-to-many)
        if graph.value(prop, KAIROS_EXT.junctionTableName):
            continue

        # Skip if silverForeignKeyOn redirects this FK to another table (DD-022)
        fk_on = graph.value(prop, KAIROS_EXT.silverForeignKeyOn)
        if fk_on is not None:
            continue

        # Qualify: must be functional, have silverColumnName, or silverForeignKey
        has_explicit_col = graph.value(prop, KAIROS_EXT.silverColumnName) is not None
        is_functional = (prop, RDF.type, OWL.FunctionalProperty) in graph
        has_fk_annotation = bool_val(
            graph, URIRef(str(prop)), KAIROS_EXT.silverForeignKey, False,
        )
        if not has_explicit_col and not is_functional and not has_fk_annotation:
            continue

        range_cls = graph.value(prop, RDFS.range)
        if range_cls is None:
            continue

        # Resolve through discriminator folding (e.g. LegalEntity → Party)
        range_model, range_local = _resolve_discriminated_model(graph, range_cls)

        # Determine FK column name
        col_override = graph.value(prop, KAIROS_EXT.silverColumnName)
        fk_col_name = str(col_override) if col_override else f"{range_model}_sk"

        targets.append({
            "prop": prop,
            "range_cls": range_cls,
            "range_local": range_local,
            "range_model": range_model,
            "fk_col_name": fk_col_name,
        })

    return targets


def _infer_fk_on_targets(
    graph: Graph,
    class_uri: str,
) -> list[dict]:
    """Identify FK properties redirected TO this class via ``silverForeignKeyOn``.

    When a property has ``kairos-ext:silverForeignKeyOn <class>``, the FK column
    should appear on that target class (not the domain class).  This function
    collects such properties where the target class matches *class_uri*.

    The join target is the property's **domain** (the parent entity), not its
    range (which equals this class).  E.g. hasAddress(domain=Party, range=Address)
    with silverForeignKeyOn=Address → FK on Address joining to Party.
    """
    targets: list[dict] = []

    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        fk_on = graph.value(prop, KAIROS_EXT.silverForeignKeyOn)
        if fk_on is None or str(fk_on) != class_uri:
            continue

        # The domain of the property is the parent we're joining to
        # (not range, which is the current class — would cause self-join)
        parent_cls = graph.value(prop, RDFS.domain)
        if parent_cls is None:
            continue

        # Skip if parent is same as current class (true self-referential)
        if str(parent_cls) == class_uri:
            continue

        # Resolve through discriminator folding
        parent_model, parent_local = _resolve_discriminated_model(graph, parent_cls)

        col_override = graph.value(prop, KAIROS_EXT.silverColumnName)
        fk_col_name = str(col_override) if col_override else f"{parent_model}_sk"

        targets.append({
            "prop": prop,
            "range_cls": parent_cls,
            "range_local": parent_local,
            "range_model": parent_model,
            "fk_col_name": fk_col_name,
        })

    return targets


def _resolve_fk_source_column(
    prop,
    mappings: dict,
    bronze_col_lookup: dict[str, dict],
    graph: Graph,
    range_cls,
    source_refs: list[tuple[str, str, str]],
    systems: list[dict] | None,
    fk_col_name: str,
    range_local: str,
) -> tuple[str | None, list[str] | None]:
    """Resolve the source column(s) for an FK property via mappings or auto-inference.

    Returns (source_col_name, source_columns) or (None, None) if unresolved.
    """
    source_col_name = None
    source_columns: list[str] | None = None

    # Try explicit SKOS mapping first
    for col_uri, col_maps_list in mappings.get("column_maps", {}).items():
        for col_map in col_maps_list:
            if col_map.get("target_uri") == str(prop):
                if col_map.get("source_columns"):
                    source_columns = col_map["source_columns"]
                if col_map.get("transform"):
                    source_col_name = col_map["transform"].replace("source.", "")
                else:
                    bronze_col = bronze_col_lookup.get(col_uri)
                    if bronze_col:
                        source_col_name = bronze_col["name"]
                    else:
                        source_col_name = extract_local_name(col_uri)
                break
        if source_col_name:
            break

    if source_col_name is not None:
        return source_col_name, source_columns

    # Auto-inference: find source column mapped to NK of range class
    current_table_col_uris: set[str] = set()
    if systems:
        for (_, _, tbl_uri_ref) in source_refs:
            current_table_col_uris.update(
                _get_table_column_uris(systems, tbl_uri_ref)
            )

    nk_prop_uris = _get_nk_property_uris(graph, str(range_cls))

    if not nk_prop_uris or not current_table_col_uris:
        return None, None

    # Collect all candidates per NK property — require exactly one
    # unambiguous candidate per NK component
    nk_candidates: list[tuple[str, str | None, list[str] | None]] = []
    all_resolved = True
    for nk_uri in nk_prop_uris:
        matches: list[tuple[str, str | None]] = []
        for col_uri, col_maps_list in mappings.get("column_maps", {}).items():
            if col_uri not in current_table_col_uris:
                continue
            for col_map in col_maps_list:
                if col_map.get("target_uri") == nk_uri:
                    if col_map.get("transform"):
                        resolved = col_map["transform"].replace("source.", "")
                    else:
                        bronze_col = bronze_col_lookup.get(col_uri)
                        if bronze_col:
                            resolved = bronze_col["name"]
                        else:
                            resolved = extract_local_name(col_uri)
                    sc = col_map.get("source_columns")
                    matches.append((resolved, sc))
        if len(matches) == 1:
            nk_candidates.append((matches[0][0], None, matches[0][1]))
        else:
            all_resolved = False
            break

    if all_resolved and len(nk_candidates) == len(nk_prop_uris):
        if len(nk_candidates) == 1:
            source_col_name = nk_candidates[0][0]
            source_columns = nk_candidates[0][2]
        else:
            # Composite NK: build ordered source column list
            source_col_name = nk_candidates[0][0]
            source_columns = [c[0] for c in nk_candidates]
        msg = (
            f"FK column '{fk_col_name}': auto-inferred join via "
            f"natural key of '{range_local}'."
        )
        logger.info(msg)

    return source_col_name, source_columns


def _build_fk_join_clause(
    source_alias: str,
    source_col_name: str,
    source_columns: list[str] | None,
    range_model: str,
    range_local: str,
    fk_col_name: str,
    target_nk: list[str],
    join_alias: str,
) -> tuple[dict, dict, str | None]:
    """Build the join dict and FK column dict for one FK relationship.

    Returns (fk_column_dict, join_dict, warning_or_None).
    """
    warning = None

    # Build join condition — single or composite NK
    if len(target_nk) == 1:
        join_condition = (
            f"{source_alias}.{source_col_name} = "
            f"{join_alias}.{target_nk[0]}"
        )
    elif source_columns and len(source_columns) == len(target_nk):
        # Composite NK: match source columns to target NK columns in order
        parts = [
            f"{source_alias}.{sc} = {join_alias}.{nk}"
            for sc, nk in zip(source_columns, target_nk)
        ]
        join_condition = " AND ".join(parts)
    else:
        # Composite NK but no matching sourceColumns — single col match + warning
        join_condition = (
            f"{source_alias}.{source_col_name} = "
            f"{join_alias}.{target_nk[0]}"
        )
        warning = (
            f"FK column '{fk_col_name}' targets class '{range_local}' with "
            f"composite natural key ({', '.join(target_nk)}) but mapping has "
            f"only 1 source column — join may be incomplete."
        )

    join_dict = {
        "type": "left",
        "ref": f"{{{{ ref('{range_model}') }}}}",
        "alias": join_alias,
        "condition": join_condition,
    }

    fk_col_dict = {
        "expression": f"{join_alias}.{range_model}_sk",
        "target_name": fk_col_name,
    }

    return fk_col_dict, join_dict, warning


def _extract_fk_columns_and_joins(
    graph: Graph,
    class_uri: str,
    mappings: dict,
    source_refs: list[tuple[str, str, str]],
    systems: list[dict] | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """Extract FK columns and joins from object properties.

    For each qualifying object property (functional, silverColumnName, or
    silverForeignKey) on the class, generates a surrogate-key lookup join to
    the referenced silver model.

    Returns:
        (fk_columns, joins, warnings) where:
        - fk_columns: column dicts with expression referencing the join alias
        - joins: join dicts for the Jinja template
        - warnings: messages about unsupported FK patterns
    """
    fk_columns: list[dict] = []
    joins: list[dict] = []
    warnings: list[str] = []
    existing_aliases: set[str] = set()

    # Only support single-source models for FK joins (multi-source is too complex)
    if len(source_refs) != 1:
        return fk_columns, joins, warnings

    source_alias = _camel_to_snake(source_refs[0][1])

    # Build bronze column lookup for resolving source column names
    bronze_col_lookup: dict[str, dict] = {}
    if systems:
        for sys in systems:
            for tbl in sys["tables"]:
                for col in tbl["columns"]:
                    bronze_col_lookup[col["uri"]] = {
                        "name": col["name"],
                        "data_type": col["data_type"],
                    }

    # Identify qualifying FK targets
    fk_targets = _infer_fk_targets(graph, class_uri)
    # Also include FK columns redirected to this class via silverForeignKeyOn
    fk_targets.extend(_infer_fk_on_targets(graph, class_uri))

    for target_info in fk_targets:
        prop = target_info["prop"]
        range_cls = target_info["range_cls"]
        range_local = target_info["range_local"]
        range_model = target_info["range_model"]
        fk_col_name = target_info["fk_col_name"]

        # Disambiguate duplicate FK column names
        if fk_col_name in existing_aliases:
            prop_suffix = _camel_to_snake(extract_local_name(str(prop)))
            fk_col_name = f"{prop_suffix}_sk"

        # Resolve source column via mapping or auto-inference
        source_col_name, source_columns = _resolve_fk_source_column(
            prop, mappings, bronze_col_lookup, graph, range_cls,
            source_refs, systems, fk_col_name, range_local,
        )

        if source_col_name is None:
            # No explicit mapping and auto-inference failed — emit NULL placeholder
            prop_local = extract_local_name(str(prop))
            fk_columns.append({
                "expression": "CAST(NULL AS {{ dbt_utils.type_string() }})",
                "target_name": fk_col_name,
            })
            remediation = (
                f"Add 'bronze:<col> skos:exactMatch <{prop}>' to your mapping "
                f"file, or map a source column to the natural key of "
                f"'{range_local}'."
            )
            msg = (
                f"FK column '{fk_col_name}' has no mapping for property "
                f"'{prop_local}' and auto-inference found no match — "
                f"emitting NULL placeholder. {remediation}"
            )
            warnings.append(msg)
            existing_aliases.add(fk_col_name)
            continue

        # Get target class natural key for the join condition
        target_nk = _get_natural_key(graph, str(range_cls))

        if len(target_nk) == 0:
            # No natural key — cannot generate join
            fk_columns.append({
                "expression": "CAST(NULL AS {{ dbt_utils.type_string() }})",
                "target_name": fk_col_name,
            })
            msg = (
                f"FK column '{fk_col_name}' targets class '{range_local}' which "
                f"has no kairos-ext:naturalKey — cannot generate join. "
                f"Resolve via: kairos-design-silver"
            )
            warnings.append(msg)
            existing_aliases.add(fk_col_name)
            continue

        # Generate join alias and ref
        join_alias = f"{range_model}_ref"
        base_alias = join_alias
        counter = 2
        while join_alias in existing_aliases:
            join_alias = f"{base_alias}_{counter}"
            counter += 1

        existing_aliases.add(fk_col_name)
        existing_aliases.add(join_alias)

        # Build join clause
        fk_col_dict, join_dict, join_warning = _build_fk_join_clause(
            source_alias, source_col_name, source_columns,
            range_model, range_local, fk_col_name, target_nk, join_alias,
        )
        fk_col_dict["comment"] = _prefixed_iri(str(prop))

        joins.append(join_dict)
        fk_columns.append(fk_col_dict)
        if join_warning:
            warnings.append(join_warning)

    return fk_columns, joins, warnings


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


def _fk_child_parents(graph: Graph, class_uri: str) -> list[str]:
    """Local names of parent classes for which ``class_uri`` is an FK-child.

    A class is an FK-child (weak entity) when an object property declares
    ``kairos-ext:silverForeignKeyOn`` pointing at it, so the FK column lands on
    this class's table pointing back to the property's other end (the parent).
    Such entities typically derive their identity from the parent (composite key)
    rather than from a standalone natural key. Used only to enrich warnings.
    """
    parents: list[str] = []
    target = URIRef(class_uri)
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        fk_on = graph.value(prop, KAIROS_EXT.silverForeignKeyOn)
        if fk_on is None or fk_on != target:
            continue
        domain = graph.value(prop, RDFS.domain)
        rng = graph.value(prop, RDFS.range)
        parent = domain if rng == target else rng
        if parent is not None:
            local = extract_local_name(str(parent))
            if local not in parents:
                parents.append(local)
    return parents


def _get_natural_key(
    graph: Graph, class_uri: str, _visited: set[str] | None = None
) -> list[str]:
    """Get natural key column names for a class from kairos-ext:naturalKey annotation.

    Walks up the rdfs:subClassOf hierarchy when the parent declares
    inheritanceStrategy "discriminator", inheriting the parent's naturalKey.
    This avoids requiring redundant annotations on every discriminator subtype.
    """
    if _visited is None:
        _visited = set()
    if class_uri in _visited:
        return []
    _visited.add(class_uri)

    # Direct annotation on this class — always wins
    nk = graph.value(URIRef(class_uri), KAIROS_EXT.naturalKey)
    if nk:
        return [_camel_to_snake(c) for c in str(nk).split()]

    # Walk up rdfs:subClassOf to inherit from discriminator parents
    for parent in graph.objects(URIRef(class_uri), RDFS.subClassOf):
        if not isinstance(parent, URIRef):
            continue
        parent_str = str(parent)
        if parent_str.startswith("http://www.w3.org/"):
            continue
        # Only inherit if parent uses discriminator strategy
        strategy = graph.value(parent, KAIROS_EXT.inheritanceStrategy)
        if strategy and str(strategy) == "discriminator":
            inherited = _get_natural_key(graph, parent_str, _visited)
            if inherited:
                return inherited

    return []


def _get_nk_property_uris(graph: Graph, class_uri: str) -> list[str]:
    """Get the full URIs of properties that form the natural key of a class.

    Resolves NK column names (from ``kairos-ext:naturalKey``) back to property URIs
    by matching the camelCase name against ``rdfs:domain`` on the class and its parents.
    Walks the discriminator hierarchy to find inherited naturalKey annotations.
    """
    # Find the naturalKey annotation (may be inherited from discriminator parent)
    nk = _get_raw_natural_key(graph, class_uri)
    if not nk:
        return []

    nk_names = str(nk).split()  # camelCase as declared in the annotation

    # Collect all domain classes (self + parents) for property lookup
    domain_classes = _get_class_and_parents(graph, class_uri)

    uris: list[str] = []
    for name in nk_names:
        found = False
        for domain_cls in domain_classes:
            for prop in graph.subjects(RDFS.domain, URIRef(domain_cls)):
                if extract_local_name(str(prop)) == name:
                    uris.append(str(prop))
                    found = True
                    break
            if found:
                break
    return uris


def _get_raw_natural_key(
    graph: Graph, class_uri: str, _visited: set[str] | None = None
) -> str | None:
    """Get the raw naturalKey annotation value (camelCase), walking discriminator hierarchy.

    Returns the literal string value of kairos-ext:naturalKey (unsplit, un-snake-cased),
    or None if no annotation is found.
    """
    if _visited is None:
        _visited = set()
    if class_uri in _visited:
        return None
    _visited.add(class_uri)

    nk = graph.value(URIRef(class_uri), KAIROS_EXT.naturalKey)
    if nk:
        return str(nk)

    # Walk up rdfs:subClassOf to inherit from discriminator parents
    for parent in graph.objects(URIRef(class_uri), RDFS.subClassOf):
        if not isinstance(parent, URIRef):
            continue
        parent_str = str(parent)
        if parent_str.startswith("http://www.w3.org/"):
            continue
        strategy = graph.value(parent, KAIROS_EXT.inheritanceStrategy)
        if strategy and str(strategy) == "discriminator":
            result = _get_raw_natural_key(graph, parent_str, _visited)
            if result:
                return result

    return None


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
    generated_class_names: set[str] | None = None,
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

    # Build mapping reverse-lookup: property URI → source column URI + match type
    prop_to_source: dict[str, str] = {}
    prop_to_match_type: dict[str, str] = {}
    if mappings:
        for col_uri, col_maps_list in mappings.get("column_maps", {}).items():
            for col_map in col_maps_list:
                if col_map.get("target_uri"):
                    prop_to_source[col_map["target_uri"]] = col_uri
                    if col_map.get("match_type"):
                        prop_to_match_type[col_map["target_uri"]] = col_map["match_type"]

    # Pre-load SHACL graph once for all classes (performance: avoids re-parsing per class)
    shacl_graph = _load_shacl_graph(shapes_dir) if shapes_dir else None

    models_data = []
    for cls in classes:
        # Skip classes that didn't generate a silver model (no bronze mapping)
        if generated_class_names is not None and cls["name"] not in generated_class_names:
            continue
        model_name = _camel_to_snake(cls["name"])
        shacl_tests = (
            _extract_shacl_tests(shapes_dir, cls["uri"], shacl_graph=shacl_graph)
            if shapes_dir else {}
        )

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

        # Datatype properties (including inherited from parent classes)
        domain_classes = _get_class_and_parents(graph, cls["uri"])
        seen_schema_cols: set[str] = set()
        for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
            domain = graph.value(prop, RDFS.domain)
            if domain and str(domain) in domain_classes:
                prop_name = extract_local_name(str(prop))
                col_name = _camel_to_snake(prop_name)
                if col_name in seen_schema_cols:
                    continue
                seen_schema_cols.add(col_name)
                label = graph.value(prop, RDFS.label)
                comment = graph.value(prop, RDFS.comment)
                desc = str(comment) if comment else (str(label) if label else prop_name)

                # Append SKOS match type for non-exactMatch columns
                match_type = prop_to_match_type.get(str(prop))
                if match_type and match_type != "exactMatch":
                    match_labels = {
                        "closeMatch": "computed/derived",
                        "narrowMatch": "subset mapping",
                        "broadMatch": "broad mapping",
                        "relatedMatch": "related mapping",
                    }
                    label_hint = match_labels.get(match_type, match_type)
                    desc = f"{desc} ({match_type} — {label_hint})"
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
                col_meta = {
                    "data_type": data_type,
                    "domain_iri": str(prop),
                }
                if source_col_uri:
                    col_meta["source_iri"] = source_col_uri

                cols.append({
                    "name": col_name,
                    "description": desc,
                    "meta": col_meta,
                    "tests": tests,
                })

        # Object property FK columns (including inherited from parent classes)
        for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
            domain = graph.value(prop, RDFS.domain)
            if domain and str(domain) in domain_classes:
                # Skip junction-table properties
                if graph.value(prop, KAIROS_EXT.junctionTableName):
                    continue
                # Only functional / explicit column
                has_explicit = graph.value(
                    prop, KAIROS_EXT.silverColumnName
                ) is not None
                is_functional = (prop, RDF.type, OWL.FunctionalProperty) in graph
                if not has_explicit and not is_functional:
                    continue
                range_cls = graph.value(prop, RDFS.range)
                if range_cls is None:
                    continue
                range_local = extract_local_name(str(range_cls))
                range_model = _camel_to_snake(range_local)
                col_override = graph.value(prop, KAIROS_EXT.silverColumnName)
                fk_col_name = str(col_override) if col_override else f"{range_model}_sk"
                prop_label = graph.value(prop, RDFS.label)
                prop_comment = graph.value(prop, RDFS.comment)
                fk_desc = (
                    str(prop_comment) if prop_comment
                    else (str(prop_label) if prop_label
                          else f"FK to {range_local}")
                )
                cols.append({
                    "name": fk_col_name,
                    "description": fk_desc,
                    "meta": {
                        "is_fk": "true",
                        "references": range_model,
                        "domain_iri": str(prop),
                    },
                    "tests": [],
                })

        models_data.append({
            "name": model_name,
            "description": cls["comment"],
            "meta": {
                "ontology_class": cls["name"],
                "ontology_iri": meta.get("iri", ""),
                "ontology_version": meta.get("version", ""),
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

    # Sanitize project name for dbt (must match ^[^\d\W]\w*$)
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", project_name)
    if safe_name and safe_name[0].isdigit():
        safe_name = f"p_{safe_name}"

    domains = [{"name": n} for n in ontology_names]

    proj_template = env.get_template("dbt_project.yml.jinja2")
    artifacts["dbt_project.yml"] = proj_template.render(
        project_name=safe_name,
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


def _build_silver_model_registry(
    silver_entity_meta: list[dict],
    classes: list[dict],
    graph: Graph,
) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Build registries mapping class URIs to silver model names and columns.

    Returns:
        Tuple of (name_registry, columns_registry) where:
        - name_registry: class URI → silver model name (snake_case)
        - columns_registry: silver model name → set of column names

    Also maps parent class URIs (via rdfs:subClassOf) to the child's silver
    model name, but ONLY when exactly one hub class extends that parent.
    This avoids ambiguity when multiple classes share a parent.
    """
    name_registry: dict[str, str] = {}
    columns_registry: dict[str, set[str]] = {}

    # Phase 1: Register direct mappings from entity metadata
    for meta in silver_entity_meta:
        if meta.get("skipped"):
            continue
        cls_uri = meta.get("class_uri")
        if not cls_uri:
            continue
        model_name = _camel_to_snake(meta["class_name"])
        name_registry[cls_uri] = model_name
        col_names = meta.get("column_names", [])
        columns_registry[model_name] = set(col_names)

    # Phase 2: Map parent URIs → child model name (single-child only)
    # Track how many children claim each parent
    parent_to_children: dict[str, list[str]] = {}
    for cls_uri, model_name in list(name_registry.items()):
        cls_ref = URIRef(cls_uri)
        for parent in graph.objects(cls_ref, RDFS.subClassOf):
            if not isinstance(parent, URIRef):
                continue
            parent_str = str(parent)
            if parent_str.startswith("http://www.w3.org/"):
                continue
            # Skip if parent already has its own silver model
            if parent_str in name_registry:
                continue
            parent_to_children.setdefault(parent_str, []).append(model_name)

    # Only register unambiguous parents (exactly one child)
    for parent_uri, children in parent_to_children.items():
        if len(children) == 1:
            name_registry[parent_uri] = children[0]
        else:
            logger.warning(
                "Parent class <%s> extended by multiple hub classes (%s) — "
                "cannot resolve to a single silver model. Gold models "
                "referencing this class may produce broken ref() calls.",
                parent_uri, ", ".join(children),
            )

    return name_registry, columns_registry


def _silver_model_name_for_class(
    cls_uri: str,
    classes: list[dict],
    registry: dict[str, str] | None = None,
) -> str | None:
    """Derive the silver dbt model name for a given ontology class URI.

    When *registry* is provided (built from actual silver generation metadata),
    it is treated as the **authoritative** source — only classes that appear in
    the registry are considered to have a silver model.  This prevents gold
    models from emitting ``ref()`` calls for imported reference-model classes
    that have no corresponding silver model.

    When *registry* is ``None`` (standalone gold run without silver), falls back
    to matching against the *classes* list.

    Returns ``None`` when no silver model can be resolved.
    """
    # 1. Registry is authoritative when present
    if registry is not None:
        name = registry.get(cls_uri)
        if name is None:
            logger.debug(
                "Class <%s> not found in silver registry — no silver model",
                cls_uri,
            )
        return name

    # 2. No registry — fall back to classes list
    for cls in classes:
        if cls["uri"] == cls_uri:
            return _camel_to_snake(cls["name"])

    logger.debug("Class <%s> not found in classes list — no silver model", cls_uri)
    return None


def _gen_gold_models(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    shapes_dir: Optional[Path],
    ontology_name: str,
    gold_ext_path: Optional[Path],
    env: Environment,
    meta: dict,
    silver_name_registry: dict[str, str] | None = None,
    silver_columns_registry: dict[str, set[str]] | None = None,
) -> dict[str, str]:
    """Generate gold dbt models from gold table definitions.

    Uses the shared ``build_gold_tables()`` from the gold projector to get
    ``GoldTableDef`` objects, then renders each as a dbt SQL model that
    reads from the corresponding silver model via ``ref()``.
    """
    from .medallion_gold_projector import build_gold_tables

    gold_tables = build_gold_tables(
        classes, graph, namespace, shapes_dir, ontology_name, gold_ext_path,
    )
    if not gold_tables:
        return {}

    artifacts: dict[str, str] = {}
    template = env.get_template("gold_model.sql.jinja2")
    schema_name = gold_tables[0].schema if gold_tables else f"gold_{ontology_name}"

    for tbl in gold_tables:
        # dim_date is auto-generated with platform-aware date-spine logic
        if tbl.name == "dim_date":
            # The date spine CTE uses dbt macros for cross-platform compatibility
            date_spine_cte = (
                "date_spine AS (\n"
                "    SELECT CAST(value AS DATE) AS date_key\n"
                "    FROM {{ kairos_date_spine(36525) }}\n"
                ")"
            )
            columns = []
            for col in tbl.columns:
                if col.name == "date_key":
                    columns.append({
                        "expression": "date_spine.date_key",
                        "target_name": col.name,
                    })
                elif col.name == "year":
                    columns.append({
                        "expression": "YEAR(date_spine.date_key)",
                        "target_name": col.name,
                    })
                elif col.name == "quarter":
                    columns.append({
                        "expression": "{{ kairos_quarter(date_spine.date_key) }}",
                        "target_name": col.name,
                    })
                elif col.name == "month":
                    columns.append({
                        "expression": "MONTH(date_spine.date_key)",
                        "target_name": col.name,
                    })
                elif col.name == "day_of_month":
                    columns.append({
                        "expression": "DAY(date_spine.date_key)",
                        "target_name": col.name,
                    })
                elif col.name == "day_of_week":
                    columns.append({
                        "expression": (
                            "{{ kairos_day_of_week(date_spine.date_key) }}"
                        ),
                        "target_name": col.name,
                    })
                elif col.name == "month_name":
                    columns.append({
                        "expression": (
                            "{{ kairos_month_name(date_spine.date_key) }}"
                        ),
                        "target_name": col.name,
                    })
                elif col.name == "is_weekend":
                    columns.append({
                        "expression": (
                            "CASE WHEN {{ kairos_day_of_week(date_spine.date_key) }}"
                            " IN (1, 7)"
                            " THEN {{ kairos_bool(true) }}"
                            " ELSE {{ kairos_bool(false) }} END"
                        ),
                        "target_name": col.name,
                    })
                else:
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
                source_ctes=[{"cte": date_spine_cte, "alias": "date_spine"}],
                columns=columns,
                joins=[],
                where_clause="",
                ontology_metadata=meta,
                incremental_column="",
                unique_key="",
            )
            path = f"models/gold/shared/{tbl.name}.sql"
            artifacts[path] = content
            continue

        # Build silver ref(s)
        source_ctes = []
        if tbl.is_subtype_cpt and tbl.parent_class_uri:
            # Class-per-table subtype: silver uses discriminator, so source
            # from parent's silver table (subtype is folded into parent in silver)
            silver_name = _silver_model_name_for_class(
                tbl.parent_class_uri, classes, registry=silver_name_registry)
            if silver_name:
                source_ctes.append({"model": silver_name, "alias": silver_name})
        elif tbl.source_class_uri:
            silver_name = _silver_model_name_for_class(
                tbl.source_class_uri, classes, registry=silver_name_registry)
            if silver_name:
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
                        ref_gold.source_class_uri, classes,
                        registry=silver_name_registry)
                    if ref_silver and ref_silver not in seen_models:
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
                    parent_gold.source_class_uri, classes,
                    registry=silver_name_registry)
                if parent_silver and not any(
                    c["model"] == parent_silver for c in source_ctes
                ):
                    source_ctes.append({
                        "model": parent_silver, "alias": parent_silver,
                    })

        if not source_ctes:
            logger.info("No silver ref for gold table %s — skipping", tbl.name)
            continue

        # Build joins for fact table FK lookups
        joins: list[dict] = []
        if tbl.table_type == "fact":
            seen_join_aliases: set[str] = set()
            source_alias = source_ctes[0]["alias"] if source_ctes else ""
            for fk_col, ref_full, ref_col, label in tbl.fk_constraints:
                ref_tbl_name = ref_full.split(".")[-1]
                ref_gold = next(
                    (t for t in gold_tables if t.name == ref_tbl_name), None)
                if ref_gold and ref_gold.source_class_uri:
                    ref_silver = _silver_model_name_for_class(
                        ref_gold.source_class_uri, classes,
                        registry=silver_name_registry)
                    if not ref_silver:
                        continue
                    alias = ref_silver
                    # Disambiguate aliases
                    base_alias = alias
                    counter = 2
                    while alias in seen_join_aliases:
                        alias = f"{base_alias}_{counter}"
                        counter += 1
                    seen_join_aliases.add(alias)

                    # FK column references the _sk of the referenced dimension
                    # ref_col is the PK column in the gold table
                    joins.append({
                        "type": "left",
                        "alias": alias,
                        "condition": (
                            f"{source_alias}.{fk_col} = {alias}.{ref_col}"
                        ),
                    })

        # Build column expressions — filter against silver columns when available
        # to ensure gold only SELECTs columns that actually exist in silver.
        silver_cols: set[str] | None = None
        if silver_columns_registry and source_ctes:
            primary_silver = source_ctes[0]["model"]
            silver_cols = silver_columns_registry.get(primary_silver)

        columns = []
        for col in tbl.columns:
            if col.is_measure:
                continue
            # Skip columns not present in silver (except structural columns
            # like SKs, valid_from/to, is_current which gold generates itself).
            # Note: _type discriminator columns ARE expected to be in silver;
            # if they're missing from silver_cols it means silver didn't generate
            # them and gold should not reference them.
            if silver_cols is not None:
                structural = (
                    col.name.endswith("_sk")
                    or col.name in ("valid_from", "valid_to", "is_current")
                )
                if not structural and col.name not in silver_cols:
                    logger.debug(
                        "Gold model '%s': skipping column '%s' — not in silver",
                        tbl.name, col.name,
                    )
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
            joins=joins,
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
    generated_gold_names: set[str] | None = None,
) -> dict[str, str]:
    """Generate ``_gold_models.yml`` with column descriptions and tests.

    When *generated_gold_names* is provided, only tables whose name appears in
    the set are included.  This keeps the schema YAML aligned with the actual
    ``.sql`` files emitted by ``_gen_gold_models``.
    """
    from .medallion_gold_projector import build_gold_tables

    gold_tables = build_gold_tables(
        classes, graph, namespace, shapes_dir, ontology_name, gold_ext_path,
    )
    if not gold_tables:
        return {}

    artifacts: dict[str, str] = {}
    template = env.get_template("gold_schema.yml.jinja2")

    models_data = []
    shared_models_data = []
    for tbl in gold_tables:
        # Skip tables that have no corresponding SQL model
        # (junction bridges have no source_class_uri)
        if tbl.name != "dim_date" and not tbl.source_class_uri:
            continue

        # Skip tables whose dbt model was not generated (no silver source)
        if generated_gold_names is not None and tbl.name not in generated_gold_names:
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

        model_entry = {
            "name": tbl.name,
            "description": tbl.source_class_label or tbl.name,
            "table_type": tbl.table_type,
            "ontology_class": tbl.source_class_label or "",
            "ontology_iri": meta.get("iri", ""),
            "ontology_version": meta.get("version", ""),
            "columns": cols,
        }

        # Conformed dimensions go to shared schema
        if tbl.name == "dim_date":
            shared_models_data.append(model_entry)
        else:
            models_data.append(model_entry)

    if models_data:
        content = template.render(models=models_data)
        path = f"models/gold/{ontology_name}/_{ontology_name}__gold_models.yml"
        artifacts[path] = content

    if shared_models_data:
        content = template.render(models=shared_models_data)
        artifacts["models/gold/shared/_shared__gold_models.yml"] = content

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
    silver_ext_path: Path = None,
    ref_model_defaults: list = None,
    peer_ext_paths: list = None,
    logical_sources_only: bool = False,
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
        silver_ext_path: Optional path to ``*-silver-ext.ttl`` for naturalKey and
            other silver annotations used by the dbt silver layer.
        peer_ext_paths: Optional list of paths to other domain ``*-silver-ext.ttl``
            files.  Used for cross-domain naturalKey resolution when FK targets
            are declared in a different domain's extension.

    Returns:
        Dictionary of ``{file_path: content}`` for all generated artifacts.
    """
    artifacts: dict[str, str] = {}
    meta = ontology_metadata or {}
    onto_name = ontology_name or "domain"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    # Merge silver-ext triples into a working copy of the graph so naturalKey
    # and other silver annotations are visible during dbt silver model generation.
    # DD-023: Include ref-model defaults as fallback layer.
    # Cross-domain NK: Include peer extension files for FK target resolution.
    graph = merge_ext_graph(
        graph, silver_ext_path,
        fallback_paths=ref_model_defaults,
        peer_ext_paths=peer_ext_paths,
    )

    # Parse source vocabulary — prefer sources_dir, fall back to bronze_dir
    systems = _parse_bronze(sources_dir or bronze_dir)

    # Parse SKOS mappings
    mappings, mapping_ns = _parse_skos_mappings(mappings_dir)

    if not systems:
        logger.info("No source systems found — generating silver models only")

    # 1. Sources YAML (minimal — under models/silver/)
    if systems:
        artifacts.update(_gen_sources(systems, env, mappings, logical_sources_only))
        logger.info("Generated %d source definition(s)", len(systems))

    # 2. Silver entity models (read directly from bronze via source())
    silver, silver_warnings, silver_entity_meta = _gen_silver_models(
        classes, graph, namespace, systems, mappings, env, meta, onto_name,
        platform=target_platform,
        mapping_ns=mapping_ns,
    )
    artifacts.update(silver)
    logger.info("Generated %d silver model(s)", len(silver))
    if silver_warnings:
        for w in silver_warnings:
            logger.warning("%s", w)
        logger.info(
            "%d class(es) skipped — see projection-report.json for details",
            len(silver_warnings),
        )

    # Cache entity metadata for session log (retrieved via get_last_entity_metadata)
    _last_entity_metadata[onto_name] = silver_entity_meta

    # Determine which classes actually generated silver models (for schema filtering).
    # Only filter when source systems are present — without sources, schema YAML is
    # generated for all classes (useful for ontology-only projections without bronze).
    generated_class_names: set[str] | None = None
    if systems:
        generated_class_names = {
            m["class_name"] for m in silver_entity_meta if not m.get("skipped")
        }

    # 3. Schema YAML with SHACL tests
    schema = _gen_schema_yaml(
        classes, graph, namespace, shapes_dir, env, onto_name, meta,
        systems=systems, mappings=mappings,
        generated_class_names=generated_class_names,
    )
    artifacts.update(schema)

    # 4. Project config (per-domain fallback — orchestrator generates definitive version)
    has_gold = False
    if systems:
        # Build silver model registry for gold ref() resolution (DD-027)
        silver_name_reg, silver_cols_reg = _build_silver_model_registry(
            silver_entity_meta, classes, graph,
        )

        # 5. Gold entity models (thick gold — pre-materialized star schema)
        gold = _gen_gold_models(
            classes, graph, namespace, shapes_dir, onto_name, gold_ext_path, env, meta,
            silver_name_registry=silver_name_reg,
            silver_columns_registry=silver_cols_reg,
        )
        artifacts.update(gold)
        has_gold = len(gold) > 0
        if gold:
            logger.info("Generated %d gold model(s)", len(gold))

        # Extract generated gold model names for schema YAML filtering
        gold_prefix = f"models/gold/{onto_name}/"
        shared_prefix = "models/gold/shared/"
        generated_gold_names = {
            p.removeprefix(gold_prefix).removesuffix(".sql")
            for p in gold if p.startswith(gold_prefix) and p.endswith(".sql")
        } | {
            p.removeprefix(shared_prefix).removesuffix(".sql")
            for p in gold if p.startswith(shared_prefix) and p.endswith(".sql")
        }

        # 6. Gold schema YAML with tests
        gold_schema = _gen_gold_schema_yaml(
            classes, graph, namespace, shapes_dir, onto_name, gold_ext_path, env, meta,
            generated_gold_names=generated_gold_names,
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
            logger.info("Generated coverage report")

    # 8. Platform macros
    macros = _gen_macros(template_dir)
    artifacts.update(macros)
    if macros:
        logger.info("Generated %d platform macro(s)", len(macros))

    # 9. Post-generation validation
    _validate_dbt_artifacts(artifacts)

    return artifacts


# ---------------------------------------------------------------------------
# Post-generation validation helpers
# ---------------------------------------------------------------------------


def _validate_dbt_artifacts(artifacts: dict[str, str]) -> None:
    """Run lightweight validation checks on generated dbt artifacts.

    Emits warnings via logger — does NOT raise. Checks:
    1. Jinja syntax: all .sql files parse with standard {% %} delimiters
    2. Ref consistency: every ref('x') points to an artifact that exists
    3. Self-join detection: no model refs itself
    """
    model_names = _extract_model_names(artifacts)
    # Cross-domain FK joins generate ref() to models in other domains.
    # Collect these as known external refs to avoid false-positive warnings.
    external_refs = _collect_join_ref_targets(artifacts)
    known_models = model_names | external_refs
    for path, content in artifacts.items():
        if not path.endswith(".sql"):
            continue
        _check_jinja_syntax(path, content)
        _check_refs(path, content, known_models)


def _extract_model_names(artifacts: dict[str, str]) -> set[str]:
    """Derive the set of model names from artifact paths."""
    names: set[str] = set()
    for path in artifacts:
        if path.endswith(".sql"):
            # models/silver_<schema>/<name>.sql -> name (without .sql)
            name = path.rsplit("/", 1)[-1].removesuffix(".sql")
            names.add(name)
    return names


_JOIN_REF_PATTERN = re.compile(r"""join\s+\{?\{?\s*ref\(\s*['"]([^'"]+)['"]\s*\)""", re.I)


def _collect_join_ref_targets(artifacts: dict[str, str]) -> set[str]:
    """Collect ref() targets used in JOIN clauses (cross-domain FK refs)."""
    targets: set[str] = set()
    for path, content in artifacts.items():
        if not path.endswith(".sql"):
            continue
        for match in _JOIN_REF_PATTERN.finditer(content):
            targets.add(match.group(1))
    return targets


def _check_jinja_syntax(path: str, content: str) -> None:
    """Verify that generated SQL parses as valid Jinja2."""
    from jinja2 import Environment as J2Env, TemplateSyntaxError

    env = J2Env()  # default {% %} / {{ }} delimiters
    try:
        env.parse(content)
    except TemplateSyntaxError as exc:
        logger.warning(
            "dbt validation: Jinja syntax error in %s line %s: %s",
            path, exc.lineno, exc.message,
        )


_REF_PATTERN = re.compile(r"""\bref\(\s*['"]([^'"]+)['"]\s*\)""")


def _check_refs(path: str, content: str, model_names: set[str]) -> None:
    """Check ref() calls point to known models and don't self-reference."""
    model_name = path.rsplit("/", 1)[-1].removesuffix(".sql")
    for match in _REF_PATTERN.finditer(content):
        target = match.group(1)
        if target == model_name:
            logger.warning(
                "dbt validation: self-referential ref('%s') in %s",
                target, path,
            )
        elif target not in model_names:
            logger.warning(
                "dbt validation: ref('%s') in %s does not match any generated model",
                target, path,
            )


def generate_dbt_project_config(
    systems: list[dict],
    ontology_names: list[str],
    template_dir,
    project_name: str = "kairos_project",
    gold_domain_names: list[str] | None = None,
    platform: str = DEFAULT_PLATFORM,
) -> dict[str, str]:
    """Generate project-level dbt config files (dbt_project.yml, packages.yml, README).

    Called by the orchestrator AFTER all per-domain projections are complete,
    so the project config includes all domains.

    Args:
        systems: Aggregated source systems from all domains.
        ontology_names: All domain names that produced artifacts.
        template_dir: Path to dbt Jinja2 templates directory.
        project_name: dbt project name.
        gold_domain_names: Domain names that produced gold models.
        platform: Target SQL platform.

    Returns:
        Dictionary of {file_path: content} for project-level files.
    """
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    gold_domains = [{"name": n} for n in (gold_domain_names or [])]
    return _gen_project_config(
        systems, ontology_names, env, project_name,
        gold_domains=gold_domains,
        platform=platform,
    )


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
    for col_uri, col_maps_list in mappings.get("column_maps", {}).items():
        for col_map in col_maps_list:
            if col_map.get("target_uri"):
                target_to_source[col_map["target_uri"]] = col_uri

    # Build set of all consumed source column URIs
    consumed_source_cols = set(mappings.get("column_maps", {}).keys())

    for cls in classes:
        cls_uri = cls["uri"]
        local = cls["name"]
        model_name = _camel_to_snake(local)

        # Include inherited properties from parent classes
        domain_classes = _get_class_and_parents(graph, cls_uri)

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
            if domain and str(domain) in domain_classes:
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
                for tbl_map in mappings.get("table_maps", {}).get(tbl["uri"], []):
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


# ---------------------------------------------------------------------------
# dbt Session Log — per-domain Markdown report for .sessions-projection/
# ---------------------------------------------------------------------------


def write_dbt_session_log(
    domain: str,
    entity_metadata: list[dict],
    sessions_dir: Path,
    toolkit_version: str = "",
    warnings: list[str] | None = None,
) -> Path | None:
    """Write a separate dbt projection session log.

    Filename: ``dbt-{domain}-{YYYY-MM-DD_HH-MM-SS}.md``

    Args:
        domain: Domain name (e.g. "client", "invoice").
        entity_metadata: List of per-entity metadata dicts from _gen_silver_models.
        sessions_dir: Path to ``.sessions-projection/`` directory.
        toolkit_version: Installed toolkit version string.
        warnings: Optional list of projection warning messages.

    Returns:
        Path to the written file, or None if sessions_dir is unavailable.
    """
    if not sessions_dir or not entity_metadata:
        return None

    sessions_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"dbt-{domain}-{date_str}.md"
    path = sessions_dir / filename

    lines: list[str] = []
    lines.append(f"# dbt Projection Report — {domain}")
    lines.append("")
    lines.append(f"**Generated:** {now.strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"**Toolkit version:** {toolkit_version}  ")
    lines.append(f"**Domain:** {domain}  ")
    lines.append("")

    # Silver Models table
    generated = [e for e in entity_metadata if not e.get("skipped")]
    if generated:
        lines.append("## Silver Models")
        lines.append("")
        lines.append("| Entity | Model File | SCD | Sources | Columns | FK Joins |")
        lines.append("|--------|-----------|-----|---------|---------|----------|")
        for e in generated:
            src_label = str(e["source_count"])
            if e["source_count"] > 1:
                src_label += " (multi)"
            lines.append(
                f"| {e['class_name']} | {e['model_file']} "
                f"| {e['scd_type']} | {src_label} "
                f"| {e['column_count']} | {e['fk_join_count']} |"
            )
        lines.append("")

    # Skipped classes
    skipped = [e for e in entity_metadata if e.get("skipped")]
    if skipped:
        lines.append("## Skipped Classes (no mapping)")
        lines.append("")
        for e in skipped:
            lines.append(f"- `{e['class_name']}` — {e.get('skip_reason', 'Unknown')}")
        lines.append("")

    # Warnings (deduplicated, excluding messages already shown in Skipped section)
    skipped_class_names = {e["class_name"] for e in entity_metadata if e.get("skipped")}
    seen: set[str] = set()
    unique_warnings: list[str] = []
    for w in (warnings or []):
        if w not in seen:
            # Skip warnings about classes already listed in Skipped section
            is_about_skipped = any(
                f"'{name}'" in w and "skipping" in w.lower()
                for name in skipped_class_names
            )
            if not is_about_skipped:
                seen.add(w)
                unique_warnings.append(w)

    if unique_warnings:
        lines.append("## ⚠️ Warnings")
        lines.append("")
        for w in unique_warnings:
            lines.append(f"- {w}")
        lines.append("")

    if not skipped and not unique_warnings:
        lines.append("## ✅ No issues")
        lines.append("")
        lines.append("All entities projected without warnings.")
        lines.append("")

    content = "\n".join(lines)
    path.write_text(content, encoding="utf-8")
    return path
