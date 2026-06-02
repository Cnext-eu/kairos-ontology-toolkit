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
SUPPORTED_VERSIONS = {"1.0"}


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

            # JSON content type
            content_type = col.get("content_type")
            if content_type:
                g.add((col_uri, KAIROS_BRONZE.contentType, Literal(content_type)))

    return g.serialize(format="turtle")


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
) -> tuple[Path | None, ChangeReport | None]:
    """Orchestrate the import-source workflow.

    Args:
        yaml_path: Path to the source-schema YAML file.
        system_name: Override system name (default: from YAML).
        output_dir: Output directory (default: integration/sources/{system}/).
        dry_run: If True, show changes but don't write files.

    Returns:
        Tuple of (output file path or None if dry-run, ChangeReport or None if fresh).
    """
    data = parse_source_schema(yaml_path)

    if system_name:
        data["system"] = system_name

    sys_name = data["system"]

    if output_dir is None:
        output_dir = Path("integration/sources") / sys_name

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

    return output_file, report
