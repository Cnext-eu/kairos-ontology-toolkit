# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Import-Source — generate or refresh bronze vocabulary TTL from introspected schema YAML.

This module provides the logic for:
1. Parsing a standardized source-schema YAML file (produced by dbt extraction or manual)
2. Generating a fresh ``kairos-bronze:`` vocabulary TTL file from the parsed schema
3. Merging introspected schema with an existing vocabulary, preserving manual enrichments
4. Producing a change report (additions, removals, type changes)

The YAML intermediate format bridges the gap between live bronze table introspection
(done in the dataplatform repo where the connection profile lives) and the vocabulary
TTL (maintained in the ontology hub as the semantic bronze contract).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rdflib import XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

logger = logging.getLogger(__name__)

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")

# Supported YAML schema versions
SUPPORTED_VERSIONS = {"1.0", "1.1"}


@dataclass
class ColumnChange:
    """Represents a change to a single column."""

    table: str
    column: str
    change_type: str  # "added", "removed", "type_changed", "nullable_changed", "pk_changed"
    old_value: str | None = None
    new_value: str | None = None


@dataclass
class ChangeReport:
    """Summary of changes when merging introspected schema with existing vocabulary."""

    added_tables: list[str] = field(default_factory=list)
    removed_tables: list[str] = field(default_factory=list)
    added_columns: list[ColumnChange] = field(default_factory=list)
    removed_columns: list[ColumnChange] = field(default_factory=list)
    type_changes: list[ColumnChange] = field(default_factory=list)
    nullable_changes: list[ColumnChange] = field(default_factory=list)
    pk_changes: list[ColumnChange] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_tables
            or self.removed_tables
            or self.added_columns
            or self.removed_columns
            or self.type_changes
            or self.nullable_changes
            or self.pk_changes
        )

    def summary(self) -> str:
        """One-line summary of changes."""
        parts = []
        if self.added_tables:
            parts.append(f"+{len(self.added_tables)} tables")
        if self.removed_tables:
            parts.append(f"-{len(self.removed_tables)} tables")
        if self.added_columns:
            parts.append(f"+{len(self.added_columns)} columns")
        if self.removed_columns:
            parts.append(f"-{len(self.removed_columns)} columns")
        if self.type_changes:
            parts.append(f"~{len(self.type_changes)} type changes")
        if self.nullable_changes:
            parts.append(f"~{len(self.nullable_changes)} nullable changes")
        if self.pk_changes:
            parts.append(f"~{len(self.pk_changes)} PK changes")
        return ", ".join(parts) if parts else "No changes"


# --------------------------------------------------------------------------- #
# YAML Parsing & Validation
# --------------------------------------------------------------------------- #


def validate_source_schema(data: dict) -> list[str]:
    """Validate a source-schema YAML dict against the v1.0 spec.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Root element must be a mapping"]

    version = data.get("version")
    if not version:
        errors.append("Missing required field: 'version'")
    elif str(version) not in SUPPORTED_VERSIONS:
        errors.append(f"Unsupported schema version: {version} (supported: {SUPPORTED_VERSIONS})")

    if not data.get("system"):
        errors.append("Missing required field: 'system'")

    tables = data.get("tables")
    if not tables:
        errors.append("Missing or empty 'tables' list")
    elif not isinstance(tables, list):
        errors.append("'tables' must be a list")
    else:
        for i, tbl in enumerate(tables):
            if not isinstance(tbl, dict):
                errors.append(f"tables[{i}]: must be a mapping")
                continue
            if not tbl.get("name"):
                errors.append(f"tables[{i}]: missing 'name'")
            columns = tbl.get("columns")
            if not columns:
                errors.append(f"tables[{i}] ({tbl.get('name', '?')}): missing or empty 'columns'")
            elif isinstance(columns, list):
                for j, col in enumerate(columns):
                    if not isinstance(col, dict):
                        errors.append(
                            f"tables[{i}].columns[{j}]: must be a mapping"
                        )
                        continue
                    if not col.get("name"):
                        errors.append(
                            f"tables[{i}].columns[{j}]: missing 'name'"
                        )
                    if not col.get("data_type"):
                        errors.append(
                            f"tables[{i}].columns[{j}] ({col.get('name', '?')}): "
                            "missing 'data_type'"
                        )

    return errors


def parse_source_schema(yaml_path: Path) -> dict:
    """Parse and validate a source-schema YAML file.

    Returns the parsed dict.
    Raises ValueError with validation errors if invalid.
    """
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise ValueError("YAML file is empty")

    errors = validate_source_schema(data)
    if errors:
        raise ValueError("Invalid source schema YAML:\n  " + "\n  ".join(errors))

    return data


def parse_source_schema_dir(schema_dir: Path) -> dict:
    """Parse a directory of per-table YAML files (v1.1 format).

    Reads _manifest.yaml for system metadata and individual table YAML files
    for column details.

    Args:
        schema_dir: Directory containing _manifest.yaml + per-table YAML files.

    Returns:
        Assembled dict in the standard source-schema format (compatible with
        generate_vocabulary_ttl).

    Raises ValueError if manifest is missing or invalid.
    """
    manifest_path = schema_dir / "_manifest.yaml"
    if not manifest_path.is_file():
        raise ValueError(f"Missing _manifest.yaml in: {schema_dir}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    if not manifest:
        raise ValueError("_manifest.yaml is empty")

    # Assemble the combined schema dict
    data = {
        "version": manifest.get("version", "1.1"),
        "system": manifest.get("system", ""),
        "platform": manifest.get("platform", "unknown"),
        "extracted_at": manifest.get("extracted_at", ""),
        "connection": manifest.get("connection", {}),
        "tables": [],
    }

    # Read each table file listed in manifest
    table_names = manifest.get("tables", [])
    for tbl_name in table_names:
        tbl_path = schema_dir / f"{tbl_name}.yaml"
        if not tbl_path.is_file():
            logger.warning(f"Table file not found: {tbl_path}")
            continue
        with open(tbl_path, encoding="utf-8") as f:
            tbl_data = yaml.safe_load(f)
        if tbl_data:
            # Merge per-column samples from sibling .samples.yaml if present
            _merge_samples_from_file(schema_dir, tbl_name, tbl_data)
            data["tables"].append(tbl_data)

    return data


def _merge_samples_from_file(schema_dir: Path, tbl_name: str, tbl_data: dict) -> None:
    """Merge per-column sample values from a .samples.yaml file into table data.

    If the table YAML already contains inline samples (backward compat with older
    extracted files), those are preserved and this function is a no-op for that column.
    """
    samples_path = schema_dir / f"{tbl_name}.samples.yaml"
    if not samples_path.is_file():
        return

    with open(samples_path, encoding="utf-8") as f:
        samples_data = yaml.safe_load(f)

    if not samples_data or "rows" not in samples_data:
        return

    rows = samples_data["rows"]
    if not rows:
        return

    # Build per-column sample lists from row data
    col_samples: dict[str, list[str]] = {}
    for row in rows:
        for col_name, val in row.items():
            if val is not None:
                col_samples.setdefault(col_name, [])
                str_val = str(val)
                if str_val and str_val not in col_samples[col_name]:
                    col_samples[col_name].append(str_val)

    # Merge into table columns (only if not already present)
    for col in tbl_data.get("columns", []):
        if col.get("samples"):
            continue  # Already has inline samples (backward compat)
        name = col.get("name", "")
        if name in col_samples:
            col["samples"] = col_samples[name][:5]


# --------------------------------------------------------------------------- #
# URI Generation (stable, deterministic)
# --------------------------------------------------------------------------- #


def _system_uri(base_ns: Namespace, system_name: str) -> URIRef:
    """Generate a stable URI for the source system."""
    return base_ns[system_name]


def _table_uri(base_ns: Namespace, table_name: str) -> URIRef:
    """Generate a stable URI for a source table."""
    return base_ns[table_name]


def _column_uri(base_ns: Namespace, table_name: str, column_name: str) -> URIRef:
    """Generate a stable URI for a source column."""
    return base_ns[f"{table_name}_{column_name}"]


# --------------------------------------------------------------------------- #
# TTL Generation
# --------------------------------------------------------------------------- #


def _json_type_to_sql(json_type: str) -> str:
    """Map a JSON value type to an approximate SQL data type."""
    mapping = {
        "string": "varchar(max)",
        "integer": "int",
        "number": "decimal",
        "boolean": "bit",
        "object": "varchar(max)",
        "array": "varchar(max)",
        "null": "varchar(max)",
    }
    return mapping.get(json_type, "varchar(max)")


def generate_vocabulary_ttl(data: dict) -> str:
    """Generate a complete vocabulary TTL file from a parsed source-schema YAML.

    Args:
        data: Validated source-schema dict (from parse_source_schema).

    Returns:
        Turtle-serialized string of the vocabulary.
    """
    system_name = data["system"]
    platform = data.get("platform", "unknown")
    environment = data.get("environment", "")
    connection = data.get("connection", {})
    database = connection.get("database", "")
    schema = connection.get("schema", "dbo")

    base_uri = f"https://kairos.cnext.eu/source/{system_name}#"
    base_ns = Namespace(base_uri)

    g = Graph()
    g.bind("kairos-bronze", KAIROS_BRONZE)
    g.bind(system_name, base_ns)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)
    g.bind("owl", OWL)

    # Source System
    sys_uri = _system_uri(base_ns, system_name)
    g.add((sys_uri, RDF.type, KAIROS_BRONZE.SourceSystem))
    g.add((sys_uri, RDFS.label, Literal(system_name)))
    g.add((sys_uri, KAIROS_BRONZE.connectionType, Literal("jdbc")))
    if database:
        g.add((sys_uri, KAIROS_BRONZE.database, Literal(database)))
    if schema:
        g.add((sys_uri, KAIROS_BRONZE.schema, Literal(schema)))

    # Add provenance annotation
    extracted_at = data.get("extracted_at", "")
    if extracted_at:
        g.add((sys_uri, RDFS.comment, Literal(
            f"Introspected from {platform} ({environment}) at {extracted_at}"
        )))

    # Tables and columns
    for tbl in data.get("tables", []):
        tbl_name = tbl["name"]
        tbl_uri = _table_uri(base_ns, tbl_name)

        g.add((tbl_uri, RDF.type, KAIROS_BRONZE.SourceTable))
        g.add((tbl_uri, RDFS.label, Literal(tbl_name)))
        g.add((tbl_uri, KAIROS_BRONZE.sourceSystem, sys_uri))
        g.add((tbl_uri, KAIROS_BRONZE.tableName, Literal(tbl_name)))

        # Primary key columns
        pk_cols = [
            col["name"] for col in tbl.get("columns", [])
            if col.get("is_primary_key")
        ]
        if pk_cols:
            g.add((tbl_uri, KAIROS_BRONZE.primaryKeyColumns, Literal(" ".join(pk_cols))))

        # Row count (v1.1 enrichment)
        row_count = tbl.get("row_count")
        if row_count is not None:
            g.add((tbl_uri, KAIROS_BRONZE.rowCount,
                   Literal(row_count, datatype=XSD.integer)))

        # Incremental column
        inc_col = tbl.get("incremental_column")
        if inc_col:
            g.add((tbl_uri, KAIROS_BRONZE.incrementalColumn, Literal(inc_col)))

        # Columns
        for col in tbl.get("columns", []):
            col_name = col["name"]
            col_uri = _column_uri(base_ns, tbl_name, col_name)

            g.add((col_uri, RDF.type, KAIROS_BRONZE.SourceColumn))
            g.add((col_uri, KAIROS_BRONZE.sourceTable, tbl_uri))
            g.add((col_uri, KAIROS_BRONZE.columnName, Literal(col_name)))
            g.add((col_uri, KAIROS_BRONZE.dataType, Literal(col["data_type"])))

            nullable = col.get("nullable", True)
            g.add((col_uri, KAIROS_BRONZE.nullable, Literal(nullable, datatype=XSD.boolean)))

            is_pk = col.get("is_primary_key", False)
            if is_pk:
                g.add((col_uri, KAIROS_BRONZE.isPrimaryKey,
                       Literal(True, datatype=XSD.boolean)))

            # JSON content type (v1.0 manual annotation)
            content_type = col.get("content_type")
            if content_type:
                g.add((col_uri, KAIROS_BRONZE.contentType, Literal(content_type)))

            # v1.1: Sample values
            samples = col.get("samples")
            if samples:
                g.add((col_uri, KAIROS_BRONZE.sampleValues,
                       Literal(" | ".join(str(s) for s in samples[:5]))))

            # v1.1: Distinct count
            distinct_count = col.get("distinct_count")
            if distinct_count is not None:
                g.add((col_uri, KAIROS_BRONZE.distinctCount,
                       Literal(distinct_count, datatype=XSD.integer)))

            # Enrichment: Suggested enum
            if col.get("suggested_enum"):
                g.add((col_uri, KAIROS_BRONZE.suggestedEnum,
                       Literal(True, datatype=XSD.boolean)))
                enum_values = col.get("enum_values", [])
                if enum_values:
                    g.add((col_uri, KAIROS_BRONZE.enumValues,
                           Literal(" | ".join(str(v) for v in enum_values))))

            # Enrichment: Format hint
            format_hint = col.get("format_hint")
            if format_hint:
                g.add((col_uri, KAIROS_BRONZE.formatHint, Literal(format_hint)))

            # Enrichment: Suggested FK
            suggested_fk = col.get("suggested_fk")
            if suggested_fk:
                fk_target_uri = _table_uri(base_ns, suggested_fk)
                g.add((col_uri, KAIROS_BRONZE.suggestedForeignKey, fk_target_uri))
                fk_confidence = col.get("fk_confidence", "medium")
                g.add((col_uri, KAIROS_BRONZE.fkConfidence, Literal(fk_confidence)))

            # Enrichment: Comment with samples for context
            if samples and not col.get("json_detected"):
                sample_comment = f"Examples: {', '.join(str(s) for s in samples[:3])}"
                g.add((col_uri, RDFS.comment, Literal(sample_comment)))

            # v1.1: JSON structure detection
            if col.get("json_detected"):
                classification = col.get("json_classification", "polymorphic")
                g.add((col_uri, KAIROS_BRONZE.contentType, Literal("json")))
                g.add((col_uri, KAIROS_BRONZE.jsonClassification,
                       Literal(classification)))

                # Generate expanded properties for flat/nested JSON
                json_structure = col.get("json_structure", [])
                if classification in ("flat", "nested") and json_structure:
                    for js in json_structure:
                        key_name = js.get("key", "")
                        if not key_name:
                            continue
                        prop_uri = _column_uri(base_ns, tbl_name, f"{col_name}__{key_name}")
                        g.add((prop_uri, RDF.type, KAIROS_BRONZE.SourceColumn))
                        g.add((prop_uri, KAIROS_BRONZE.sourceTable, tbl_uri))
                        g.add((prop_uri, KAIROS_BRONZE.columnName,
                               Literal(f"{col_name}.{key_name}")))
                        g.add((prop_uri, KAIROS_BRONZE.dataType,
                               Literal(_json_type_to_sql(js.get("type", "string")))))
                        g.add((prop_uri, KAIROS_BRONZE.derivedFromJson, col_uri))
                        if js.get("sample") is not None:
                            g.add((prop_uri, KAIROS_BRONZE.sampleValues,
                                   Literal(str(js["sample"]))))

                elif classification == "array_object" and json_structure:
                    # Generate a linked child table concept
                    child_tbl_name = f"{tbl_name}_{col_name}"
                    child_uri = _table_uri(base_ns, child_tbl_name)
                    g.add((child_uri, RDF.type, KAIROS_BRONZE.SourceTable))
                    g.add((child_uri, RDFS.label, Literal(child_tbl_name)))
                    g.add((child_uri, KAIROS_BRONZE.sourceSystem, sys_uri))
                    g.add((child_uri, KAIROS_BRONZE.tableName, Literal(child_tbl_name)))
                    g.add((child_uri, KAIROS_BRONZE.derivedFromJson, col_uri))
                    g.add((child_uri, RDFS.comment, Literal(
                        f"Virtual table derived from JSON array column "
                        f"{tbl_name}.{col_name}"
                    )))
                    for js in json_structure:
                        key_name = js.get("key", "")
                        if not key_name:
                            continue
                        prop_uri = _column_uri(base_ns, child_tbl_name, key_name)
                        g.add((prop_uri, RDF.type, KAIROS_BRONZE.SourceColumn))
                        g.add((prop_uri, KAIROS_BRONZE.sourceTable, child_uri))
                        g.add((prop_uri, KAIROS_BRONZE.columnName, Literal(key_name)))
                        g.add((prop_uri, KAIROS_BRONZE.dataType,
                               Literal(_json_type_to_sql(js.get("type", "string")))))

    return g.serialize(format="turtle")


def generate_vocabulary_per_table(data: dict) -> dict[str, str]:
    """Generate one TTL file per table from a parsed source-schema YAML.

    Returns a dict mapping table_name → Turtle string. Each file contains the
    system declaration (SourceSystem) plus one table and its columns.
    This enables fine-grained git diffs and scoped LLM context loading.
    """
    system_name = data["system"]
    platform = data.get("platform", "unknown")
    environment = data.get("environment", "")
    connection = data.get("connection", {})
    database = connection.get("database", "")
    schema = connection.get("schema", "dbo")
    extracted_at = data.get("extracted_at", "")

    base_uri = f"https://kairos.cnext.eu/source/{system_name}#"
    base_ns = Namespace(base_uri)

    results: dict[str, str] = {}

    for tbl in data.get("tables", []):
        g = Graph()
        g.bind("kairos-bronze", KAIROS_BRONZE)
        g.bind(system_name, base_ns)
        g.bind("rdfs", RDFS)
        g.bind("xsd", XSD)
        g.bind("owl", OWL)

        # Ontology declaration per table
        ont_uri = URIRef(f"https://kairos.cnext.eu/source/{system_name}/vocabulary/{tbl['name']}")
        g.add((ont_uri, RDF.type, OWL.Ontology))
        g.add((ont_uri, RDFS.label, Literal(f"{system_name} — {tbl['name']} Vocabulary")))
        if extracted_at:
            g.add((ont_uri, OWL.versionInfo, Literal(f"Extracted {extracted_at}")))

        # Minimal system reference (for context)
        sys_uri = _system_uri(base_ns, system_name)
        g.add((sys_uri, RDF.type, KAIROS_BRONZE.SourceSystem))
        g.add((sys_uri, RDFS.label, Literal(system_name)))
        if database:
            g.add((sys_uri, KAIROS_BRONZE.database, Literal(database)))
        if schema:
            g.add((sys_uri, KAIROS_BRONZE.schema, Literal(schema)))

        # Generate table + columns (reuse same logic as generate_vocabulary_ttl)
        _add_table_to_graph(g, tbl, base_ns, sys_uri)

        results[tbl["name"]] = g.serialize(format="turtle")

    return results


def _add_table_to_graph(
    g: Graph, tbl: dict, base_ns: Namespace, sys_uri: URIRef
) -> None:
    """Add a single table and its columns to an rdflib Graph."""
    tbl_name = tbl["name"]
    tbl_uri = _table_uri(base_ns, tbl_name)

    g.add((tbl_uri, RDF.type, KAIROS_BRONZE.SourceTable))
    g.add((tbl_uri, RDFS.label, Literal(tbl_name)))
    g.add((tbl_uri, KAIROS_BRONZE.sourceSystem, sys_uri))
    g.add((tbl_uri, KAIROS_BRONZE.tableName, Literal(tbl_name)))

    pk_cols = [col["name"] for col in tbl.get("columns", []) if col.get("is_primary_key")]
    if pk_cols:
        g.add((tbl_uri, KAIROS_BRONZE.primaryKeyColumns, Literal(" ".join(pk_cols))))

    row_count = tbl.get("row_count")
    if row_count is not None:
        g.add((tbl_uri, KAIROS_BRONZE.rowCount, Literal(row_count, datatype=XSD.integer)))

    inc_col = tbl.get("incremental_column")
    if inc_col:
        g.add((tbl_uri, KAIROS_BRONZE.incrementalColumn, Literal(inc_col)))

    for col in tbl.get("columns", []):
        col_name = col["name"]
        col_uri = _column_uri(base_ns, tbl_name, col_name)

        g.add((col_uri, RDF.type, KAIROS_BRONZE.SourceColumn))
        g.add((col_uri, KAIROS_BRONZE.sourceTable, tbl_uri))
        g.add((col_uri, KAIROS_BRONZE.columnName, Literal(col_name)))
        g.add((col_uri, KAIROS_BRONZE.dataType, Literal(col["data_type"])))

        nullable = col.get("nullable", True)
        g.add((col_uri, KAIROS_BRONZE.nullable, Literal(nullable, datatype=XSD.boolean)))

        is_pk = col.get("is_primary_key", False)
        if is_pk:
            g.add((col_uri, KAIROS_BRONZE.isPrimaryKey, Literal(True, datatype=XSD.boolean)))

        content_type = col.get("content_type")
        if content_type:
            g.add((col_uri, KAIROS_BRONZE.contentType, Literal(content_type)))

        samples = col.get("samples")
        if samples:
            g.add((col_uri, KAIROS_BRONZE.sampleValues,
                   Literal(" | ".join(str(s) for s in samples[:5]))))

        distinct_count = col.get("distinct_count")
        if distinct_count is not None:
            g.add((col_uri, KAIROS_BRONZE.distinctCount,
                   Literal(distinct_count, datatype=XSD.integer)))

        if col.get("suggested_enum"):
            g.add((col_uri, KAIROS_BRONZE.suggestedEnum, Literal(True, datatype=XSD.boolean)))
            enum_values = col.get("enum_values", [])
            if enum_values:
                g.add((col_uri, KAIROS_BRONZE.enumValues,
                       Literal(" | ".join(str(v) for v in enum_values))))

        format_hint = col.get("format_hint")
        if format_hint:
            g.add((col_uri, KAIROS_BRONZE.formatHint, Literal(format_hint)))

        suggested_fk = col.get("suggested_fk")
        if suggested_fk:
            fk_target_uri = _table_uri(base_ns, suggested_fk)
            g.add((col_uri, KAIROS_BRONZE.suggestedForeignKey, fk_target_uri))
            fk_confidence = col.get("fk_confidence", "medium")
            g.add((col_uri, KAIROS_BRONZE.fkConfidence, Literal(fk_confidence)))

        if samples and not col.get("json_detected"):
            sample_comment = f"Examples: {', '.join(str(s) for s in samples[:3])}"
            g.add((col_uri, RDFS.comment, Literal(sample_comment)))

        if col.get("json_detected"):
            classification = col.get("json_classification", "polymorphic")
            g.add((col_uri, KAIROS_BRONZE.contentType, Literal("json")))
            g.add((col_uri, KAIROS_BRONZE.jsonClassification, Literal(classification)))

            json_structure = col.get("json_structure", [])
            if classification in ("flat", "nested") and json_structure:
                for js in json_structure:
                    key_name = js.get("key", "")
                    if not key_name:
                        continue
                    prop_uri = _column_uri(base_ns, tbl_name, f"{col_name}__{key_name}")
                    g.add((prop_uri, RDF.type, KAIROS_BRONZE.SourceColumn))
                    g.add((prop_uri, KAIROS_BRONZE.sourceTable, tbl_uri))
                    g.add((prop_uri, KAIROS_BRONZE.columnName,
                           Literal(f"{col_name}.{key_name}")))
                    g.add((prop_uri, KAIROS_BRONZE.dataType,
                           Literal(_json_type_to_sql(js.get("type", "string")))))
                    g.add((prop_uri, KAIROS_BRONZE.derivedFromJson, col_uri))
                    if js.get("sample") is not None:
                        g.add((prop_uri, KAIROS_BRONZE.sampleValues,
                               Literal(str(js["sample"]))))

            elif classification == "array_object" and json_structure:
                child_tbl_name = f"{tbl_name}_{col_name}"
                child_uri = _table_uri(base_ns, child_tbl_name)
                g.add((child_uri, RDF.type, KAIROS_BRONZE.SourceTable))
                g.add((child_uri, RDFS.label, Literal(child_tbl_name)))
                g.add((child_uri, KAIROS_BRONZE.sourceSystem, sys_uri))
                g.add((child_uri, KAIROS_BRONZE.tableName, Literal(child_tbl_name)))
                g.add((child_uri, KAIROS_BRONZE.derivedFromJson, col_uri))
                g.add((child_uri, RDFS.comment, Literal(
                    f"Virtual table derived from JSON array column "
                    f"{tbl_name}.{col_name}"
                )))
                for js in json_structure:
                    key_name = js.get("key", "")
                    if not key_name:
                        continue
                    prop_uri = _column_uri(base_ns, child_tbl_name, key_name)
                    g.add((prop_uri, RDF.type, KAIROS_BRONZE.SourceColumn))
                    g.add((prop_uri, KAIROS_BRONZE.sourceTable, child_uri))
                    g.add((prop_uri, KAIROS_BRONZE.columnName, Literal(key_name)))
                    g.add((prop_uri, KAIROS_BRONZE.dataType,
                           Literal(_json_type_to_sql(js.get("type", "string")))))


# --------------------------------------------------------------------------- #
# Merge with Existing Vocabulary
# --------------------------------------------------------------------------- #


def merge_with_existing(
    data: dict, existing_path: Path
) -> tuple[str, ChangeReport]:
    """Merge introspected schema with an existing vocabulary TTL file.

    Preserves all triples in the existing graph that are not directly managed by
    introspection (e.g., manual labels, comments, JSON schema details, enums).
    Only updates table/column existence, data types, nullable, and PK status.

    Args:
        data: Validated source-schema dict.
        existing_path: Path to the existing vocabulary TTL file.

    Returns:
        Tuple of (updated TTL string, ChangeReport).
    """
    report = ChangeReport()
    system_name = data["system"]
    base_uri = f"https://kairos.cnext.eu/source/{system_name}#"
    base_ns = Namespace(base_uri)

    # Parse existing graph
    existing = Graph()
    existing.parse(existing_path, format="turtle")

    # Build index of existing tables and columns
    existing_tables: dict[str, URIRef] = {}
    existing_columns: dict[str, dict] = {}  # key: "table_col"

    for tbl_uri in existing.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
        tbl_name = str(
            existing.value(tbl_uri, KAIROS_BRONZE.tableName)
            or existing.value(tbl_uri, RDFS.label)
            or ""
        )
        if tbl_name:
            existing_tables[tbl_name] = tbl_uri

    for col_uri in existing.subjects(RDF.type, KAIROS_BRONZE.SourceColumn):
        col_name = str(existing.value(col_uri, KAIROS_BRONZE.columnName) or "")
        tbl_uri = existing.value(col_uri, KAIROS_BRONZE.sourceTable)
        if tbl_uri and col_name:
            tbl_name = str(
                existing.value(tbl_uri, KAIROS_BRONZE.tableName)
                or existing.value(tbl_uri, RDFS.label)
                or ""
            )
            if tbl_name:
                key = f"{tbl_name}_{col_name}"
                col_type = str(existing.value(col_uri, KAIROS_BRONZE.dataType) or "")
                nullable_val = existing.value(col_uri, KAIROS_BRONZE.nullable)
                nullable = True if nullable_val is None else str(nullable_val).lower() == "true"
                is_pk_val = existing.value(col_uri, KAIROS_BRONZE.isPrimaryKey)
                is_pk = str(is_pk_val).lower() == "true" if is_pk_val else False
                existing_columns[key] = {
                    "uri": col_uri,
                    "table": tbl_name,
                    "name": col_name,
                    "data_type": col_type,
                    "nullable": nullable,
                    "is_pk": is_pk,
                }

    # Build set of introspected tables/columns
    new_tables: set[str] = set()
    new_columns: dict[str, dict] = {}

    for tbl in data.get("tables", []):
        tbl_name = tbl["name"]
        new_tables.add(tbl_name)
        for col in tbl.get("columns", []):
            col_name = col["name"]
            key = f"{tbl_name}_{col_name}"
            new_columns[key] = {
                "table": tbl_name,
                "name": col_name,
                "data_type": col.get("data_type", "string"),
                "nullable": col.get("nullable", True),
                "is_pk": col.get("is_primary_key", False),
                "content_type": col.get("content_type"),
            }

    # Detect changes
    existing_table_names = set(existing_tables.keys())

    # Added tables
    for tbl_name in sorted(new_tables - existing_table_names):
        report.added_tables.append(tbl_name)

    # Removed tables (mark deprecated, don't delete)
    for tbl_name in sorted(existing_table_names - new_tables):
        report.removed_tables.append(tbl_name)

    # Column-level changes
    existing_col_keys = set(existing_columns.keys())
    new_col_keys = set(new_columns.keys())

    for key in sorted(new_col_keys - existing_col_keys):
        col_info = new_columns[key]
        report.added_columns.append(ColumnChange(
            table=col_info["table"], column=col_info["name"], change_type="added"
        ))

    for key in sorted(existing_col_keys - new_col_keys):
        col_info = existing_columns[key]
        # Only report removal for columns whose table still exists in new schema
        if col_info["table"] in new_tables:
            report.removed_columns.append(ColumnChange(
                table=col_info["table"], column=col_info["name"], change_type="removed"
            ))

    # Type/nullable/PK changes for columns that exist in both
    for key in sorted(existing_col_keys & new_col_keys):
        old = existing_columns[key]
        new = new_columns[key]

        if old["data_type"] != new["data_type"]:
            report.type_changes.append(ColumnChange(
                table=old["table"], column=old["name"],
                change_type="type_changed",
                old_value=old["data_type"], new_value=new["data_type"],
            ))
        if old["nullable"] != new["nullable"]:
            report.nullable_changes.append(ColumnChange(
                table=old["table"], column=old["name"],
                change_type="nullable_changed",
                old_value=str(old["nullable"]), new_value=str(new["nullable"]),
            ))
        if old["is_pk"] != new["is_pk"]:
            report.pk_changes.append(ColumnChange(
                table=old["table"], column=old["name"],
                change_type="pk_changed",
                old_value=str(old["is_pk"]), new_value=str(new["is_pk"]),
            ))

    # Apply changes to the existing graph (preserve all non-managed triples)
    connection = data.get("connection", {})
    database = connection.get("database", "")
    schema = connection.get("schema", "dbo")

    # Update system-level connection info if provided
    sys_uri = _system_uri(base_ns, system_name)
    if (sys_uri, RDF.type, KAIROS_BRONZE.SourceSystem) in existing:
        if database:
            existing.remove((sys_uri, KAIROS_BRONZE.database, None))
            existing.add((sys_uri, KAIROS_BRONZE.database, Literal(database)))
        if schema:
            existing.remove((sys_uri, KAIROS_BRONZE.schema, None))
            existing.add((sys_uri, KAIROS_BRONZE.schema, Literal(schema)))

    # Add new tables
    for tbl_name in report.added_tables:
        tbl_uri = _table_uri(base_ns, tbl_name)
        existing.add((tbl_uri, RDF.type, KAIROS_BRONZE.SourceTable))
        existing.add((tbl_uri, RDFS.label, Literal(tbl_name)))
        existing.add((tbl_uri, KAIROS_BRONZE.sourceSystem, sys_uri))
        existing.add((tbl_uri, KAIROS_BRONZE.tableName, Literal(tbl_name)))

    # Mark removed tables as deprecated
    for tbl_name in report.removed_tables:
        tbl_uri = existing_tables[tbl_name]
        existing.add((tbl_uri, OWL.deprecated, Literal(True, datatype=XSD.boolean)))

    # Add new columns
    for change in report.added_columns:
        key = f"{change.table}_{change.column}"
        col_data = new_columns[key]
        col_uri = _column_uri(base_ns, change.table, change.column)
        tbl_uri = existing_tables.get(change.table) or _table_uri(base_ns, change.table)

        existing.add((col_uri, RDF.type, KAIROS_BRONZE.SourceColumn))
        existing.add((col_uri, KAIROS_BRONZE.sourceTable, tbl_uri))
        existing.add((col_uri, KAIROS_BRONZE.columnName, Literal(change.column)))
        existing.add((col_uri, KAIROS_BRONZE.dataType, Literal(col_data["data_type"])))
        existing.add((col_uri, KAIROS_BRONZE.nullable,
                      Literal(col_data["nullable"], datatype=XSD.boolean)))
        if col_data["is_pk"]:
            existing.add((col_uri, KAIROS_BRONZE.isPrimaryKey,
                          Literal(True, datatype=XSD.boolean)))
        if col_data.get("content_type"):
            existing.add((col_uri, KAIROS_BRONZE.contentType,
                          Literal(col_data["content_type"])))

    # Mark removed columns as deprecated (don't delete)
    for change in report.removed_columns:
        key = f"{change.table}_{change.column}"
        col_info = existing_columns.get(key)
        if col_info:
            existing.add((col_info["uri"], OWL.deprecated,
                          Literal(True, datatype=XSD.boolean)))

    # Update type changes
    for change in report.type_changes:
        key = f"{change.table}_{change.column}"
        col_info = existing_columns[key]
        existing.remove((col_info["uri"], KAIROS_BRONZE.dataType, None))
        existing.add((col_info["uri"], KAIROS_BRONZE.dataType,
                      Literal(change.new_value)))

    # Update nullable changes
    for change in report.nullable_changes:
        key = f"{change.table}_{change.column}"
        col_info = existing_columns[key]
        existing.remove((col_info["uri"], KAIROS_BRONZE.nullable, None))
        existing.add((col_info["uri"], KAIROS_BRONZE.nullable,
                      Literal(change.new_value == "True", datatype=XSD.boolean)))

    # Update PK changes
    for change in report.pk_changes:
        key = f"{change.table}_{change.column}"
        col_info = existing_columns[key]
        existing.remove((col_info["uri"], KAIROS_BRONZE.isPrimaryKey, None))
        new_is_pk = change.new_value == "True"
        if new_is_pk:
            existing.add((col_info["uri"], KAIROS_BRONZE.isPrimaryKey,
                          Literal(True, datatype=XSD.boolean)))

    # Update primaryKeyColumns on tables that changed
    tables_with_pk_changes = {c.table for c in report.pk_changes}
    for tbl_name in tables_with_pk_changes:
        tbl_uri = existing_tables.get(tbl_name) or _table_uri(base_ns, tbl_name)
        # Gather PK columns from new data
        pk_names = [
            new_columns[k]["name"] for k in new_columns
            if new_columns[k]["table"] == tbl_name and new_columns[k]["is_pk"]
        ]
        existing.remove((tbl_uri, KAIROS_BRONZE.primaryKeyColumns, None))
        if pk_names:
            existing.add((tbl_uri, KAIROS_BRONZE.primaryKeyColumns,
                          Literal(" ".join(pk_names))))

    return existing.serialize(format="turtle"), report


# --------------------------------------------------------------------------- #
# Main Orchestration
# --------------------------------------------------------------------------- #


def run_import_source(
    yaml_path: Path,
    system_name: str | None = None,
    output_dir: Path | None = None,
    dry_run: bool = False,
    enrich: bool = True,
    enum_threshold: int = 25,
    split_tables: bool = False,
) -> tuple[Path | None, ChangeReport | None]:
    """Orchestrate the import-source workflow.

    Args:
        yaml_path: Path to the source-schema YAML file.
        system_name: Override system name (default: from YAML).
        output_dir: Output directory (default: integration/sources/{system}/).
        dry_run: If True, show changes but don't write files.
        enrich: If True, run inference enrichment (enum/format/FK detection).
        enum_threshold: Max distinct values for enum detection.
        split_tables: If True, generate one TTL per table in a vocabulary/ subfolder.

    Returns:
        Tuple of (output file/dir path or None if dry-run, ChangeReport or None if fresh).
    """
    data = parse_source_schema(yaml_path)

    if system_name:
        data["system"] = system_name

    # Run enrichment if enabled and data has samples (v1.1)
    if enrich and _has_enrichable_data(data):
        from .enrich_vocabulary import enrich_source_schema
        enrich_source_schema(data, enum_threshold=enum_threshold)

    sys_name = data["system"]

    if output_dir is None:
        # Detect hub root: check cwd/ontology-hub/ first, then cwd itself
        cwd = Path.cwd()
        hub_root = None
        for candidate in [cwd / "ontology-hub", cwd]:
            if (candidate / "model" / "ontologies").is_dir():
                hub_root = candidate
                break
        if hub_root:
            output_dir = hub_root / "integration" / "sources" / sys_name
        else:
            output_dir = Path("integration/sources") / sys_name

    # --- Split-tables mode: one TTL per table ---
    if split_tables:
        vocab_dir = output_dir / "vocabulary"
        if dry_run:
            logger.info("Dry-run: would write per-table TTLs to %s", vocab_dir)
            return None, None

        vocab_dir.mkdir(parents=True, exist_ok=True)
        per_table = generate_vocabulary_per_table(data)
        for tbl_name, ttl_content in per_table.items():
            tbl_file = vocab_dir / f"{tbl_name}.vocabulary.ttl"
            tbl_file.write_text(ttl_content, encoding="utf-8")

        logger.info(
            "Written %d per-table vocabulary files to %s", len(per_table), vocab_dir
        )
        return vocab_dir, None

    # --- Standard single-file mode ---
    output_file = output_dir / f"{sys_name}.vocabulary.ttl"

    if output_file.exists():
        # Merge mode
        logger.info("Existing vocabulary found at %s — merging", output_file)
        ttl_content, report = merge_with_existing(data, output_file)
    else:
        # Fresh generation
        logger.info("No existing vocabulary — generating fresh TTL")
        ttl_content = generate_vocabulary_ttl(data)
        report = None

    if dry_run:
        return None, report

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file.write_text(ttl_content, encoding="utf-8")
    logger.info("Written vocabulary to %s", output_file)

    # Always generate per-table files alongside the monolithic file
    vocab_dir = output_dir / "vocabulary"
    vocab_dir.mkdir(parents=True, exist_ok=True)
    per_table = generate_vocabulary_per_table(data)
    for tbl_name, tbl_ttl in per_table.items():
        tbl_file = vocab_dir / f"{tbl_name}.vocabulary.ttl"
        tbl_file.write_text(tbl_ttl, encoding="utf-8")
    logger.info(
        "Written %d per-table vocabulary files to %s", len(per_table), vocab_dir
    )

    return output_file, report


def _has_enrichable_data(data: dict) -> bool:
    """Check if the schema data has samples/distinct counts worth enriching."""
    for tbl in data.get("tables", []):
        for col in tbl.get("columns", []):
            if col.get("samples") or col.get("distinct_count") is not None:
                return True
    return False
