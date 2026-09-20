# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""TMDL parser — line-based, indent-aware parser for Power BI TMDL files.

Extracts tables, columns, measures, and relationships from TMDL definition
files. This is intentionally a "good enough" parser that handles the common
patterns needed for ontology engineering input, not a full TMDL grammar parser.
"""

from __future__ import annotations

import re
import textwrap
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
    #: Bare `isKey`, and the annotations Kairos writes. Needed to harvest a Desktop edit
    #: back into authored hub inputs (#744): without annotations there is no way to tell a
    #: measure the hub emitted from one a report author added by hand.
    is_key: bool = False
    display_folder: str = ""
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass
class TmdlMeasure:
    """A DAX measure within a TMDL table."""

    name: str
    expression: str = ""
    format_string: str = ""
    description: str = ""
    display_folder: str = ""
    lineage_tag: str = ""
    is_hidden: bool = False
    annotations: dict[str, str] = field(default_factory=dict)


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
    annotations: dict[str, str] = field(default_factory=dict)
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
    #: Tables ``model.tmdl`` declares but whose definition files are absent from the
    #: export. A non-empty list means the input is incomplete, not that the model is
    #: empty -- the two were indistinguishable in every artifact written (#807).
    unresolved_table_refs: list[str] = field(default_factory=list)


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
        elif _ANNOTATION.match(stripped):
            annotation = _ANNOTATION.match(stripped)
            table.annotations[annotation.group("name")] = _strip_quotes(
                annotation.group("value").strip()
            )
            i += 1
        elif stripped == "isHidden":
            table.is_hidden = True
            i += 1
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


_ANNOTATION = re.compile(r"^annotation\s+(?P<name>[A-Za-z_][\w]*)\s*=\s*(?P<value>.*)$")

#: Terminates a multi-line DAX expression. `annotation` belongs here because Kairos emits
#: `annotation Kairos_Lifecycle` straight after a measure, and without it the annotation
#: was swallowed into the expression text (#744).
_MEASURE_PROPERTY = re.compile(
    r"^(formatString|description|lineageTag|isHidden|displayFolder|annotation)\s*[:=\s]"
)


def _doc_comment(lines: list[str], index: int) -> str:
    """Return the `///` description immediately above *index*, if any.

    TMDL writes a real description as a `///` doc comment, not a `description:` property,
    so a parser that skips `///` (as this one did) cannot see any description Power BI
    Desktop or Kairos actually emits.
    """
    parts: list[str] = []
    cursor = index - 1
    while cursor >= 0:
        stripped = lines[cursor].strip()
        if not stripped.startswith("///"):
            break
        parts.append(stripped[3:].strip())
        cursor -= 1
    return " ".join(reversed(parts))


def _parse_column(lines: list[str], start: int, parent_indent: int) -> tuple[TmdlColumn, int]:
    """Parse a column block."""
    header = lines[start].strip()
    match = re.match(r"column\s+['\"]?(.+?)['\"]?\s*$", header)
    name = match.group(1) if match else header[7:].strip().strip("'\"")
    col = TmdlColumn(name=name, description=_doc_comment(lines, start))

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

        annotation = _ANNOTATION.match(stripped)
        if annotation:
            col.annotations[annotation.group("name")] = _strip_quotes(
                annotation.group("value").strip()
            )
            i += 1
            continue
        # Bare flags: TMDL writes `isKey` and `isHidden` with no value, so a
        # colon-only reader could not see either.
        if stripped == "isKey":
            col.is_key = True
            i += 1
            continue
        if stripped == "isHidden":
            col.is_hidden = True
            i += 1
            continue

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
            elif key == "displayFolder":
                col.display_folder = _strip_quotes(value)
        i += 1

    return col, i


#: TMDL wraps a multi-line DAX expression in a ``` fence: the opening fence follows the
#: `=`, the body is indented under it, and a bare ``` closes it. The fence is delimiter,
#: never expression text (issue #875).
_EXPRESSION_FENCE = "```"


def _collect_fenced_expression(lines: list[str], start: int) -> tuple[str, int]:
    """Collect a ```-fenced expression body, preserving its internal shape.

    ``start`` is the line after the opening fence. Returns the dedented body and the
    index of the line after the closing fence (or after the last line, if the fence is
    unterminated -- a truncated export should still yield the DAX it does carry).
    """
    body: list[str] = []
    i = start
    while i < len(lines):
        if lines[i].strip() == _EXPRESSION_FENCE:
            i += 1
            break
        body.append(lines[i])
        i += 1
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return textwrap.dedent("\n".join(body)).rstrip(), i


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

    measure = TmdlMeasure(name=name, description=_doc_comment(lines, start))

    i = start + 1

    # If we got an inline expression from the header, start collecting
    if first_expr is not None:
        if first_expr.startswith(_EXPRESSION_FENCE):
            # `measure Name = ``` ` -> fenced multi-line DAX. Read to the closing
            # fence rather than guessing the end from indentation, and keep the
            # fence out of the expression text (issue #875).
            measure.expression, i = _collect_fenced_expression(lines, i)
        elif first_expr:
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
                if _MEASURE_PROPERTY.match(next_stripped):
                    break
                expr_lines.append(next_stripped)
                i += 1
            measure.expression = "\n".join(expr_lines)
        else:
            # `measure Name =` with empty RHS → multiline DAX follows, either
            # fenced or as a plain indented block.
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines) and lines[i].strip() == _EXPRESSION_FENCE:
                measure.expression, i = _collect_fenced_expression(lines, i + 1)
                expr_lines = None
            else:
                expr_lines = []
            while expr_lines is not None and i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                next_indent = _get_indent(next_line)
                if not next_stripped:
                    i += 1
                    continue
                if next_indent <= parent_indent:
                    break
                if _MEASURE_PROPERTY.match(next_stripped):
                    break
                expr_lines.append(next_stripped)
                i += 1
            if expr_lines is not None:
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

        annotation = _ANNOTATION.match(stripped)
        if annotation:
            measure.annotations[annotation.group("name")] = _strip_quotes(
                annotation.group("value").strip()
            )
            i += 1
            continue
        if stripped == "isHidden":
            measure.is_hidden = True
            i += 1
            continue

        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "formatString":
                measure.format_string = _strip_quotes(value)
            elif key == "description":
                measure.description = _strip_quotes(value)
            elif key == "displayFolder":
                measure.display_folder = _strip_quotes(value)
            elif key == "lineageTag":
                measure.lineage_tag = _strip_quotes(value)
        i += 1

    return measure, i


def _parse_partition(lines: list[str], start: int, parent_indent: int) -> tuple[TmdlPartition, int]:
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


def _parse_relationship(lines: list[str], start: int) -> tuple[TmdlRelationship, int]:
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


def parse_model_table_refs(content: str) -> list[str]:
    """Return the table names ``model.tmdl`` declares via ``ref table`` pointers.

    Table discovery is otherwise a glob over ``definition/tables/``, so an export whose
    table bodies are missing is indistinguishable from a model that genuinely has no
    tables -- `import-tmdl` reported ``Tables: 0`` on a 34-table model and exited 0
    (#807). ``model.tmdl`` names every table it expects, which is enough to notice.

    Names may be bare or single-quoted (TMDL quotes any name with a space in it).
    Order is the model's own, not the filesystem's, and duplicates are dropped.
    """
    names: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("ref table "):
            continue
        name = _strip_quotes(stripped[len("ref table ") :].strip())
        if name and name not in names:
            names.append(name)
    return names


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
    declared_tables: list[str] = []
    if model_file.exists():
        model_text = model_file.read_text(encoding="utf-8")
        meta = parse_model_tmdl(model_text)
        model.compatibility_level = meta.get("compatibilityLevel", "")
        model.default_mode = meta.get("defaultMode", "")
        declared_tables = parse_model_table_refs(model_text)

    # Parse tables. The canonical PBIP layout puts them under definition/tables/,
    # but a Power BI export saved without that folder drops every <table>.tmdl flat
    # beside model.tmdl. Read both, so a flat export is not reported as an export
    # missing all of its tables (issue #TMDL-FLAT).
    table_files: list[Path] = []
    tables_dir = definition_dir / "tables"
    if tables_dir.is_dir():
        table_files.extend(sorted(tables_dir.glob("*.tmdl")))
    table_files.extend(
        f for f in sorted(definition_dir.glob("*.tmdl")) if f.name.casefold() != "model.tmdl"
    )
    for tmdl_file in table_files:
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

    # Compared case-insensitively: the pointer and the filename are the same name and
    # TMDL does not guarantee they agree on case.
    parsed = {table.name.casefold() for table in model.tables}
    model.unresolved_table_refs = [
        name for name in declared_tables if name.casefold() not in parsed
    ]

    # Derive the model name from whichever folder actually identifies the model.
    # "MyModel.SemanticModel/definition/" → "MyModel"; a flat export folder names
    # itself. Falling through to the parent for a flat layout named every export in
    # one staging directory after that directory, so a batch import silently
    # overwrote each artifact with the next (issue #TMDL-FLAT).
    parent = definition_dir.parent
    if parent.name.endswith(".SemanticModel"):
        model.name = parent.name.rsplit(".SemanticModel", 1)[0]
    elif definition_dir.name.casefold() == "definition":
        model.name = parent.name
    else:
        model.name = definition_dir.name
    if model.name.endswith(".SemanticModel"):
        model.name = model.name.rsplit(".SemanticModel", 1)[0]

    return model
