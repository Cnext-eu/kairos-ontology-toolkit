# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""TMDL parser — line-based, indent-aware parser for Power BI TMDL files.

Extracts tables, columns, measures, and relationships from TMDL definition
files. This is intentionally a "good enough" parser that handles the common
patterns needed for ontology engineering input, not a full TMDL grammar parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TmdlColumn:
    """A column within a TMDL table."""

    name: str
    data_type: str = ""
    format_string: str = ""
    source_column: str = ""
    is_hidden: bool = False
    lineage_tag: str = ""
    description: str = ""


@dataclass
class TmdlMeasure:
    """A DAX measure within a TMDL table."""

    name: str
    expression: str = ""
    format_string: str = ""
    description: str = ""


@dataclass
class TmdlPartition:
    """A partition (data source) within a TMDL table."""

    name: str
    mode: str = ""  # e.g., "import", "directLake", "directQuery"
    source_type: str = ""  # e.g., "m", "entity", "calculated"


@dataclass
class TmdlTable:
    """A table definition parsed from TMDL."""

    name: str
    lineage_tag: str = ""
    description: str = ""
    columns: list[TmdlColumn] = field(default_factory=list)
    measures: list[TmdlMeasure] = field(default_factory=list)
    partitions: list[TmdlPartition] = field(default_factory=list)
    is_hidden: bool = False

    @property
    def table_type(self) -> str:
        """Infer table type from naming convention."""
        lower = self.name.lower()
        if lower.startswith("f_") or lower.startswith("fact_"):
            return "fact"
        if lower.startswith("d_") or lower.startswith("dim_"):
            return "dimension"
        if lower.startswith("bridge_"):
            return "bridge"
        # Check if it's a measure-only table
        if self.measures and not self.columns:
            return "measure_table"
        return "unknown"

    @property
    def partition_type(self) -> str:
        """Return the primary partition mode."""
        if self.partitions:
            return self.partitions[0].mode or self.partitions[0].source_type
        return ""


@dataclass
class TmdlRelationship:
    """A relationship between two tables."""

    name: str = ""
    from_table: str = ""
    from_column: str = ""
    to_table: str = ""
    to_column: str = ""
    from_cardinality: str = ""
    to_cardinality: str = ""
    cross_filtering: str = ""
    is_active: bool = True


@dataclass
class TmdlModel:
    """A complete TMDL semantic model."""

    name: str = ""
    compatibility_level: str = ""
    default_mode: str = ""
    tables: list[TmdlTable] = field(default_factory=list)
    relationships: list[TmdlRelationship] = field(default_factory=list)
    source_path: str = ""


def _get_indent(line: str) -> int:
    """Return the indentation level (number of leading tabs or 4-space groups)."""
    stripped = line.lstrip("\t")
    tabs = len(line) - len(stripped)
    if tabs > 0:
        return tabs
    stripped = line.lstrip(" ")
    spaces = len(line) - len(stripped)
    return spaces // 4


def _strip_quotes(value: str) -> str:
    """Strip surrounding quotes from a TMDL value."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def parse_tmdl_content(content: str) -> list[TmdlTable | TmdlRelationship]:
    """Parse TMDL text content and return tables and relationships.

    This handles both table definitions (from tables/*.tmdl) and relationship
    definitions (from relationships.tmdl).
    """
    lines = content.splitlines()
    results: list[TmdlTable | TmdlRelationship] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("///"):
            i += 1
            continue

        if stripped.startswith("table "):
            table, i = _parse_table(lines, i)
            results.append(table)
        elif stripped.startswith("relationship "):
            rel, i = _parse_relationship(lines, i)
            results.append(rel)
        else:
            i += 1

    return results


def _parse_table(lines: list[str], start: int) -> tuple[TmdlTable, int]:
    """Parse a table block starting at the given line index."""
    header = lines[start].strip()
    # table <name> or table '<name with spaces>'
    match = re.match(r"table\s+['\"]?(.+?)['\"]?\s*$", header)
    name = match.group(1) if match else header[6:].strip().strip("'\"")
    table = TmdlTable(name=name)

    base_indent = _get_indent(lines[start])
    i = start + 1

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("///"):
            i += 1
            continue

        indent = _get_indent(line)
        if indent <= base_indent and stripped:
            break

        if stripped.startswith("column "):
            col, i = _parse_column(lines, i, indent)
            table.columns.append(col)
        elif stripped.startswith("measure "):
            measure, i = _parse_measure(lines, i, indent)
            table.measures.append(measure)
        elif stripped.startswith("partition "):
            partition, i = _parse_partition(lines, i, indent)
            table.partitions.append(partition)
        elif ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "lineageTag":
                table.lineage_tag = _strip_quotes(value)
            elif key == "isHidden":
                table.is_hidden = value.lower() == "true"
            elif key == "description":
                table.description = _strip_quotes(value)
            i += 1
        else:
            i += 1

    return table, i


def _parse_column(lines: list[str], start: int, parent_indent: int) -> tuple[TmdlColumn, int]:
    """Parse a column block."""
    header = lines[start].strip()
    match = re.match(r"column\s+['\"]?(.+?)['\"]?\s*$", header)
    name = match.group(1) if match else header[7:].strip().strip("'\"")
    col = TmdlColumn(name=name)

    i = start + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("///"):
            i += 1
            continue

        indent = _get_indent(line)
        if indent <= parent_indent and stripped:
            break

        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "dataType":
                col.data_type = value
            elif key == "formatString":
                col.format_string = _strip_quotes(value)
            elif key == "sourceColumn":
                col.source_column = _strip_quotes(value)
            elif key == "isHidden":
                col.is_hidden = value.lower() == "true"
            elif key == "lineageTag":
                col.lineage_tag = _strip_quotes(value)
            elif key == "description":
                col.description = _strip_quotes(value)
        i += 1

    return col, i


def _parse_measure(lines: list[str], start: int, parent_indent: int) -> tuple[TmdlMeasure, int]:
    """Parse a measure block, including multiline DAX expressions."""
    header = lines[start].strip()
    # TMDL measures: `measure <Name> = <expr>` or `measure <Name> =` (multiline)
    # Also possible: `measure <Name>` (no expression on header line)
    eq_match = re.match(r"measure\s+['\"]?(.+?)['\"]?\s*=\s*(.*)", header)
    if eq_match:
        name = eq_match.group(1).strip().strip("'\"")
        first_expr = eq_match.group(2).strip()
    else:
        match = re.match(r"measure\s+['\"]?(.+?)['\"]?\s*$", header)
        name = match.group(1) if match else header[8:].strip().strip("'\"")
        first_expr = None

    measure = TmdlMeasure(name=name)

    i = start + 1

    # If we got an inline expression from the header, start collecting
    if first_expr is not None:
        if first_expr:
            # Single-line or start of multiline DAX
            expr_lines = [first_expr]
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                next_indent = _get_indent(next_line)
                if not next_stripped:
                    i += 1
                    continue
                if next_indent <= parent_indent:
                    break
                if re.match(
                    r"^(formatString|description|lineageTag|isHidden|displayFolder)\s*[:=]",
                    next_stripped,
                ):
                    break
                expr_lines.append(next_stripped)
                i += 1
            measure.expression = "\n".join(expr_lines)
        else:
            # `measure Name =` with empty RHS → multiline DAX follows
            expr_lines = []
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                next_indent = _get_indent(next_line)
                if not next_stripped:
                    i += 1
                    continue
                if next_indent <= parent_indent:
                    break
                if re.match(
                    r"^(formatString|description|lineageTag|isHidden|displayFolder)\s*[:=]",
                    next_stripped,
                ):
                    break
                expr_lines.append(next_stripped)
                i += 1
            measure.expression = "\n".join(expr_lines)

    # Parse remaining properties
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("///"):
            i += 1
            continue

        indent = _get_indent(line)
        if indent <= parent_indent and stripped:
            break

        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "formatString":
                measure.format_string = _strip_quotes(value)
            elif key == "description":
                measure.description = _strip_quotes(value)
        i += 1

    return measure, i


def _parse_partition(
    lines: list[str], start: int, parent_indent: int
) -> tuple[TmdlPartition, int]:
    """Parse a partition block."""
    header = lines[start].strip()
    match = re.match(r"partition\s+['\"]?(.+?)['\"]?\s*$", header)
    name = match.group(1) if match else header[10:].strip().strip("'\"")
    partition = TmdlPartition(name=name)

    i = start + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("///"):
            i += 1
            continue

        indent = _get_indent(line)
        if indent <= parent_indent and stripped:
            break

        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "mode":
                partition.mode = value.lower()
            elif key == "type":
                partition.source_type = value.lower()
            elif key == "source":
                # Sometimes source type is on same line
                if value:
                    partition.source_type = value.lower()
        i += 1

    return partition, i


def _parse_relationship(
    lines: list[str], start: int
) -> tuple[TmdlRelationship, int]:
    """Parse a relationship block."""
    header = lines[start].strip()
    match = re.match(r"relationship\s+['\"]?(.+?)['\"]?\s*$", header)
    name = match.group(1) if match else header[13:].strip().strip("'\"")
    rel = TmdlRelationship(name=name)

    base_indent = _get_indent(lines[start])
    i = start + 1

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("///"):
            i += 1
            continue

        indent = _get_indent(line)
        if indent <= base_indent and stripped:
            break

        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = _strip_quotes(value.strip())
            if key == "fromColumn":
                rel.from_column = value
            elif key == "toColumn":
                rel.to_column = value
            elif key == "fromTable":
                rel.from_table = value
            elif key == "toTable":
                rel.to_table = value
            elif key == "fromCardinality":
                rel.from_cardinality = value
            elif key == "toCardinality":
                rel.to_cardinality = value
            elif key == "crossFilteringBehavior":
                rel.cross_filtering = value
            elif key == "isActive":
                rel.is_active = value.lower() != "false"
        i += 1

    return rel, i


def parse_model_tmdl(content: str) -> dict[str, str]:
    """Parse model.tmdl for model-level metadata.

    Returns a dict with keys like 'compatibilityLevel', 'defaultMode', etc.
    """
    metadata: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "compatibilityLevel":
                metadata["compatibilityLevel"] = value
            elif key == "defaultMode":
                metadata["defaultMode"] = value
            elif key == "culture":
                metadata["culture"] = _strip_quotes(value)
    return metadata


def parse_model_folder(definition_dir: Path) -> TmdlModel:
    """Parse an entire SemanticModel/definition/ folder into a TmdlModel.

    Expected structure:
        definition/
            model.tmdl
            relationships.tmdl  (optional)
            tables/
                <table>.tmdl
    """
    model = TmdlModel()
    model.source_path = str(definition_dir)

    # Parse model.tmdl for metadata
    model_file = definition_dir / "model.tmdl"
    if model_file.exists():
        meta = parse_model_tmdl(model_file.read_text(encoding="utf-8"))
        model.compatibility_level = meta.get("compatibilityLevel", "")
        model.default_mode = meta.get("defaultMode", "")

    # Parse tables
    tables_dir = definition_dir / "tables"
    if tables_dir.is_dir():
        for tmdl_file in sorted(tables_dir.glob("*.tmdl")):
            content = tmdl_file.read_text(encoding="utf-8")
            items = parse_tmdl_content(content)
            for item in items:
                if isinstance(item, TmdlTable):
                    model.tables.append(item)

    # Parse relationships
    rel_file = definition_dir / "relationships.tmdl"
    if rel_file.exists():
        content = rel_file.read_text(encoding="utf-8")
        items = parse_tmdl_content(content)
        for item in items:
            if isinstance(item, TmdlRelationship):
                model.relationships.append(item)

    # Derive model name from parent folder
    # e.g., "MyModel.SemanticModel/definition/" → "MyModel"
    parent = definition_dir.parent
    if parent.name.endswith(".SemanticModel"):
        model.name = parent.name.rsplit(".SemanticModel", 1)[0]
    else:
        model.name = parent.name

    return model
