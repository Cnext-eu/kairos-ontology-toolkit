# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Generate advisory draft SHACL shapes from bronze source profiling metadata."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, XSD
from rdflib.collection import Collection

from ._samples import example_values, is_pii_column
from .analyse_sources import KAIROS_BRONZE, parse_source_vocabulary
from .enrich_vocabulary import DEFAULT_ENUM_MIN_ROWS, FORMAT_PATTERNS

SH = Namespace("http://www.w3.org/ns/shacl#")
DRAFT_SHAPES = Namespace("https://kairos.cnext.eu/shapes/draft#")

# Datatypes that never yield an sh:in enum (#424 / DD-076 amendment):
# temporal and decimal/float values have unstable lexical forms across systems;
# boolean sh:in adds nothing over sh:datatype and brittle lexical forms
# ("1"/"true"/"True") cause false violations. Integer stays eligible —
# integer status codes are legitimate enums.
_ENUM_INELIGIBLE_DATATYPES = frozenset({XSD.date, XSD.dateTime, XSD.time, XSD.decimal, XSD.boolean})

# UUID regex source, for matching against `_detected_pattern` output. Load-bearing
# because SQL Server `uniqueidentifier` maps to xsd:string — without this check a
# low-cardinality-looking UUID column would be enumerated.
_UUID_PATTERN = next(pattern for name, pattern in FORMAT_PATTERNS if name == "uuid").pattern

_DATA_TYPE_MAP = {
    "string": XSD.string,
    "str": XSD.string,
    "char": XSD.string,
    "varchar": XSD.string,
    "nvarchar": XSD.string,
    "text": XSD.string,
    "int": XSD.integer,
    "integer": XSD.integer,
    "bigint": XSD.integer,
    "smallint": XSD.integer,
    "decimal": XSD.decimal,
    "numeric": XSD.decimal,
    "float": XSD.decimal,
    "double": XSD.decimal,
    "bool": XSD.boolean,
    "boolean": XSD.boolean,
    "bit": XSD.boolean,  # SQL Server / Parquet-mapped boolean (#424)
    "date": XSD.date,
    "datetime": XSD.dateTime,
    "timestamp": XSD.dateTime,
}


def _safe_fragment(value: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_")
    if not fragment:
        return "unnamed"
    if fragment[0].isdigit():
        return f"_{fragment}"
    return fragment


def _xsd_datatype(data_type: str | None):
    normalized = str(data_type or "").strip().lower()
    tokens = [part for part in re.split(r"[^a-z0-9]+", normalized) if part]

    if any(token in tokens for token in ("datetime", "timestamp")):
        return XSD.dateTime
    if "date" in tokens:
        return XSD.date

    for token in tokens:
        if token in _DATA_TYPE_MAP:
            return _DATA_TYPE_MAP[token]

    if "int" in normalized:
        return XSD.integer
    if any(token in normalized for token in ("decimal", "numeric", "float", "double")):
        return XSD.decimal
    if "bool" in normalized:
        return XSD.boolean
    return XSD.string


def _non_empty_samples(samples: list[Any] | None) -> list[str]:
    return [str(sample).strip() for sample in samples or [] if str(sample).strip()]


def _unique_non_empty(samples: list[Any] | None) -> list[str]:
    return list(dict.fromkeys(_non_empty_samples(samples)))


def _detected_pattern(samples: list[Any] | None) -> str | None:
    non_empty = _non_empty_samples(samples)
    if not non_empty:
        return None

    matches = [
        pattern.pattern
        for _, pattern in FORMAT_PATTERNS
        if all(pattern.match(sample) for sample in non_empty)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _literal_for_value(value: str, datatype) -> Literal:
    return Literal(value, datatype=datatype)


def _literal_to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    converted = value.toPython() if hasattr(value, "toPython") else value
    if isinstance(converted, bool):
        return converted
    text = str(converted).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _literal_to_int(value: Any) -> int | None:
    if value is None:
        return None
    converted = value.toPython() if hasattr(value, "toPython") else value
    try:
        return int(converted)
    except (TypeError, ValueError):
        return None


def _parse_source_vocabulary_with_profile(
    vocab_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Parse a bronze vocabulary into (tables, table_profiles).

    ``table_profiles`` maps table name → the DD-156 table-level evidence
    (``row_count``/``rows_sampled``/``distinct_scope``); entries are absent
    or ``None``-valued for legacy vocabularies that predate the contract.
    """
    tables = parse_source_vocabulary(vocab_path)
    by_name = {
        (table_name, column["name"]): column
        for table_name, columns in tables.items()
        for column in columns
    }
    table_profiles: dict[str, dict[str, Any]] = {}

    graph = Graph()
    graph.parse(vocab_path, format="turtle")

    for table_uri in graph.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
        table_name = str(
            graph.value(table_uri, KAIROS_BRONZE.tableName)
            or table_uri.split("#")[-1].split("/")[-1]
        )
        scope_literal = graph.value(table_uri, KAIROS_BRONZE.distinctScope)
        table_profiles[table_name] = {
            "row_count": _literal_to_int(graph.value(table_uri, KAIROS_BRONZE.rowCount)),
            "rows_sampled": _literal_to_int(graph.value(table_uri, KAIROS_BRONZE.rowsSampled)),
            "distinct_scope": str(scope_literal) if scope_literal is not None else None,
        }
        column_uris = set(graph.subjects(KAIROS_BRONZE.belongsToTable, table_uri))
        column_uris.update(graph.subjects(KAIROS_BRONZE.sourceTable, table_uri))

        for column_uri in column_uris:
            column_name = str(
                graph.value(column_uri, KAIROS_BRONZE.columnName)
                or column_uri.split("#")[-1].split("/")[-1]
            )
            column = by_name.get((table_name, column_name))
            if column is None:
                continue

            nullable = _literal_to_bool(graph.value(column_uri, KAIROS_BRONZE.nullable))
            if nullable is not None:
                column["nullable"] = nullable

            distinct_count = _literal_to_int(graph.value(column_uri, KAIROS_BRONZE.distinctCount))
            if distinct_count is not None:
                column["distinct_count"] = distinct_count

            format_hint = graph.value(column_uri, KAIROS_BRONZE.formatHint)
            if format_hint is not None:
                column["format_hint"] = str(format_hint)

    return tables, table_profiles


def _bind_prefixes(graph: Graph) -> None:
    graph.bind("sh", SH)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)
    graph.bind("draft", DRAFT_SHAPES)


def build_shapes_graph(
    tables: dict[str, list[dict[str, Any]]],
    *,
    enum_distinct_max: int = 12,
    include_sample_values: bool = True,
    mappings: dict | None = None,
    table_profiles: dict[str, dict[str, Any]] | None = None,
) -> Graph:
    """Build a draft SHACL graph for source/bronze tables and columns.

    ``table_profiles`` carries the DD-156 table-level evidence
    (``row_count``/``rows_sampled``/``distinct_scope`` per table name). The
    default (``None``) is legacy-tolerant: tables without a profile are
    treated as scope-unknown, which never yields an ``sh:in`` enum.
    """
    graph = Graph()
    _bind_prefixes(graph)

    # Extension point for DD-076+: mappings may later retarget shapes to domain properties.
    _ = mappings
    table_profiles = table_profiles or {}

    for table_name, columns in sorted(tables.items()):
        profile = table_profiles.get(table_name) or {}
        row_count = _literal_to_int(profile.get("row_count"))
        rows_sampled = _literal_to_int(profile.get("rows_sampled"))
        distinct_scope = profile.get("distinct_scope")
        distinct_scope = str(distinct_scope) if distinct_scope is not None else None
        table_fragment = _safe_fragment(table_name)
        node_shape = DRAFT_SHAPES[f"{table_fragment}Shape"]
        graph.add((node_shape, RDF.type, SH.NodeShape))
        graph.add((node_shape, RDFS.label, Literal(f"Draft source shape for {table_name}")))
        graph.add((node_shape, SH.name, Literal(table_name)))

        for column in sorted(columns, key=lambda item: str(item.get("name", ""))):
            column_name = str(column.get("name") or "unnamed")
            column_fragment = _safe_fragment(column_name)
            column_path = DRAFT_SHAPES[f"{table_fragment}_{column_fragment}"]
            property_shape = BNode()
            samples = column.get("samples") or []
            datatype = _xsd_datatype(column.get("data_type"))
            pii = is_pii_column(column_name, sample_values=samples)
            unique_samples = _unique_non_empty(samples)
            distinct_count = _literal_to_int(column.get("distinct_count"))

            graph.add((node_shape, SH.property, property_shape))
            graph.add((property_shape, RDF.type, SH.PropertyShape))
            graph.add((property_shape, SH.path, column_path))
            graph.add((property_shape, SH.name, Literal(column_name)))
            graph.add((property_shape, RDFS.label, Literal(f"{table_name}.{column_name}")))
            graph.add((property_shape, SH.datatype, datatype))
            graph.add(
                (
                    property_shape,
                    RDFS.comment,
                    Literal(
                        "DRAFT advisory PropertyShape derived from source profiling metadata "
                        "and samples; requires human review."
                    ),
                )
            )

            if _literal_to_bool(column.get("nullable")) is False:
                graph.add((property_shape, SH.minCount, Literal(1)))

            pattern = _detected_pattern(samples)
            if pattern:
                graph.add((property_shape, SH.pattern, Literal(pattern)))
                graph.add(
                    (
                        property_shape,
                        RDFS.comment,
                        Literal("Sample-derived format pattern; advisory and requires review."),
                    )
                )

            examples = example_values(samples, is_pii=pii, include=include_sample_values)
            if examples:
                graph.add(
                    (
                        property_shape,
                        RDFS.comment,
                        Literal(f"Example values: {', '.join(examples)}"),
                    )
                )

            # sh:in gate (#424 / DD-076 amendment): a distinctCount is only
            # population truth when the table asserts distinctScope="table";
            # sample-scoped or legacy (scope-absent) evidence yields advisory
            # comments, never a constraint. Datatype- and UUID-excluded columns
            # get neither (sh:datatype already carries the signal).
            format_hint = str(column.get("format_hint") or "").strip().lower()
            looks_uuid = format_hint == "uuid" or pattern == _UUID_PATTERN
            enum_candidate = (
                not pii
                and datatype not in _ENUM_INELIGIBLE_DATATYPES
                and not looks_uuid
                and isinstance(distinct_count, int)
                and 0 < distinct_count <= enum_distinct_max
            )
            enum_comment: str | None = None
            if enum_candidate and distinct_scope == "table":
                if row_count is not None and row_count < DEFAULT_ENUM_MIN_ROWS:
                    # Floor (H5): applies only when the true cardinality is
                    # known; an explicit "table" scope without rowCount
                    # (warehouse-shaped evidence) is trusted as-is.
                    profiled = rows_sampled if rows_sampled is not None else row_count
                    enum_comment = (
                        f"enum not suggested: only {profiled} rows profiled "
                        f"(< {DEFAULT_ENUM_MIN_ROWS}); re-import with a larger "
                        "--max-rows or profile the warehouse table."
                    )
                elif len(unique_samples) == distinct_count:
                    values_node = BNode()
                    Collection(
                        graph,
                        values_node,
                        [_literal_for_value(value, datatype) for value in unique_samples],
                    )
                    graph.add((property_shape, SH["in"], values_node))
                    enum_comment = (
                        f"Enum constraint from full-table distinctCount={distinct_count}; "
                        f"all {distinct_count} values observed in samples; "
                        "review before publishing."
                    )
            elif enum_candidate and distinct_scope == "sample" and rows_sampled is not None:
                if distinct_count >= rows_sampled:
                    enum_comment = (
                        f"enum not suggested: distinctCount={distinct_count} saturates the "
                        f"{rows_sampled}-row sample window; evidence cannot distinguish "
                        "an enum from an open value set."
                    )
                elif rows_sampled < DEFAULT_ENUM_MIN_ROWS:
                    enum_comment = (
                        f"enum not suggested: only {rows_sampled} rows profiled "
                        f"(< {DEFAULT_ENUM_MIN_ROWS}); re-import with a larger "
                        "--max-rows or profile the warehouse table."
                    )
                else:
                    enum_comment = (
                        f"possible enum: {distinct_count} distinct values in "
                        f"{rows_sampled} sampled rows; sample-scoped evidence — "
                        "not verified against full data."
                    )
            elif enum_candidate:
                # Scope absent (legacy vocabulary) or malformed sample scope
                # without a window size: the distinctCount predates the DD-156
                # evidence contract and cannot be trusted.
                enum_comment = (
                    "possible enum (unverified: profiling predates rows-sampled "
                    "evidence; regenerate the source vocabulary with import-source)."
                )

            if enum_comment:
                graph.add((property_shape, RDFS.comment, Literal(enum_comment)))
            elif (
                distinct_count is None
                and unique_samples
                and len(unique_samples) <= enum_distinct_max
            ):
                graph.add(
                    (
                        property_shape,
                        RDFS.comment,
                        Literal(
                            f"possible enum (unverified: only {len(unique_samples)} sampled values)"
                        ),
                    )
                )

    return graph


def suggest_shapes(
    vocab_path: Path,
    out_path: Path,
    *,
    enum_distinct_max: int = 12,
    include_sample_values: bool = True,
    force: bool = False,
    mappings: dict | None = None,
) -> Path:
    """Read bronze vocabulary metadata and write a draft SHACL Turtle file."""
    vocab_path = Path(vocab_path)
    out_path = Path(out_path)

    if out_path.exists() and not force:
        raise FileExistsError(
            f"Refusing to overwrite existing draft shapes file: {out_path}. "
            "Pass force=True to overwrite."
        )

    tables, table_profiles = _parse_source_vocabulary_with_profile(vocab_path)
    graph = build_shapes_graph(
        tables,
        enum_distinct_max=enum_distinct_max,
        include_sample_values=include_sample_values,
        mappings=mappings,
        table_profiles=table_profiles,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(graph.serialize(format="turtle"), encoding="utf-8")
    return out_path
