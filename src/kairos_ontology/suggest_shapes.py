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
from .enrich_vocabulary import FORMAT_PATTERNS

SH = Namespace("http://www.w3.org/ns/shacl#")
DRAFT_SHAPES = Namespace("https://kairos.cnext.eu/shapes/draft#")

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


def _parse_source_vocabulary_with_profile(vocab_path: Path) -> dict[str, list[dict[str, Any]]]:
    tables = parse_source_vocabulary(vocab_path)
    by_name = {
        (table_name, column["name"]): column
        for table_name, columns in tables.items()
        for column in columns
    }

    graph = Graph()
    graph.parse(vocab_path, format="turtle")

    for table_uri in graph.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
        table_name = str(
            graph.value(table_uri, KAIROS_BRONZE.tableName)
            or table_uri.split("#")[-1].split("/")[-1]
        )
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

    return tables


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
) -> Graph:
    """Build a draft SHACL graph for source/bronze tables and columns."""
    graph = Graph()
    _bind_prefixes(graph)

    # Extension point for DD-076+: mappings may later retarget shapes to domain properties.
    _ = mappings

    for table_name, columns in sorted(tables.items()):
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
            graph.add((
                property_shape,
                RDFS.comment,
                Literal(
                    "DRAFT advisory PropertyShape derived from source profiling metadata "
                    "and samples; requires human review."
                ),
            ))

            if _literal_to_bool(column.get("nullable")) is False:
                graph.add((property_shape, SH.minCount, Literal(1)))

            pattern = _detected_pattern(samples)
            if pattern:
                graph.add((property_shape, SH.pattern, Literal(pattern)))
                graph.add((
                    property_shape,
                    RDFS.comment,
                    Literal("Sample-derived format pattern; advisory and requires review."),
                ))

            examples = example_values(samples, is_pii=pii, include=include_sample_values)
            if examples:
                graph.add((
                    property_shape,
                    RDFS.comment,
                    Literal(f"Example values: {', '.join(examples)}"),
                ))

            if (
                not pii
                and isinstance(distinct_count, int)
                and 0 < distinct_count <= enum_distinct_max
                and len(unique_samples) == distinct_count
            ):
                values_node = BNode()
                Collection(
                    graph,
                    values_node,
                    [_literal_for_value(value, datatype) for value in unique_samples],
                )
                graph.add((property_shape, SH["in"], values_node))
                graph.add((
                    property_shape,
                    RDFS.comment,
                    Literal(
                        f"Enum constraint backed by bronze distinctCount={distinct_count}; "
                        "review before publishing."
                    ),
                ))
            elif distinct_count is None and unique_samples and len(unique_samples) <= enum_distinct_max:
                graph.add((
                    property_shape,
                    RDFS.comment,
                    Literal(f"possible enum (unverified: only {len(unique_samples)} sampled values)"),
                ))

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

    tables = _parse_source_vocabulary_with_profile(vocab_path)
    graph = build_shapes_graph(
        tables,
        enum_distinct_max=enum_distinct_max,
        include_sample_values=include_sample_values,
        mappings=mappings,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(graph.serialize(format="turtle"), encoding="utf-8")
    return out_path
