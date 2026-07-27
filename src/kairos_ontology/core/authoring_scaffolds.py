# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic, evidence-grounded design and recovery scaffolds."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from .design_validation import validate_mapping_design, validate_silver_extension
from .ontology_loader import load_ontology
from .projections.dbt.mapping_bind import bind_mapping_graph

BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
EXT = Namespace("https://kairos.cnext.eu/ext#")
KMAP = Namespace("https://kairos.cnext.eu/mapping#")
AUTHORING = Namespace("https://kairos.cnext.eu/authoring#")


class AuthoringScaffoldError(ValueError):
    """Raised when evidence is missing, ambiguous, or an output would be overwritten."""


@dataclass(frozen=True, slots=True)
class RdfScaffold:
    """One generated RDF scaffold and its focused validation report."""

    graph: Graph
    validation: dict
    proposals: int
    review_items: int
    advisories: int = 0

    def serialize(self) -> str:
        """Serialize the graph using rdflib."""
        return self.graph.serialize(format="turtle")


def _token(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").casefold()
    return slug or "resource"


def _local_name(uri: str) -> str:
    return uri.rstrip("/#").rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _resource(namespace: Namespace, kind: str, *parts: str) -> URIRef:
    readable = "__".join(_slug(_local_name(part)) for part in parts)
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:12]
    return namespace[f"{kind}__{readable}__{digest}"]


def _load_source_graph(source_root: Path) -> Graph:
    graph = Graph()
    paths = tuple(sorted(source_root.rglob("*.ttl"))) if source_root.is_dir() else ()
    if not paths:
        raise AuthoringScaffoldError(f"No source vocabularies found under {source_root}")
    for path in paths:
        try:
            graph.parse(path, format="turtle")
        except Exception as exc:
            raise AuthoringScaffoldError(
                f"Could not parse source vocabulary {path}: {exc}"
            ) from exc
    return graph


def _source_columns(graph: Graph, table: URIRef) -> tuple[URIRef, ...]:
    columns = set(graph.subjects(BRONZE.sourceTable, table))
    columns.update(graph.subjects(BRONZE.belongsToTable, table))
    return tuple(sorted((item for item in columns if isinstance(item, URIRef)), key=str))


def _column_name(graph: Graph, column: URIRef) -> str:
    return str(graph.value(column, BRONZE.columnName) or _local_name(str(column)))


def _mapping_namespace(source_table_uri: str, target_class_uri: str) -> Namespace:
    digest = hashlib.sha256(f"{source_table_uri}\0{target_class_uri}".encode()).hexdigest()[:16]
    return Namespace(f"https://kairos.cnext.eu/authoring/mapping/{digest}#")


def build_mapping_scaffold(
    *,
    source_root: Path,
    ontology_path: Path,
    source_table_uri: str,
    target_class_uri: str,
    catalog_path: Path | None = None,
    existing_mapping_paths: Iterable[Path] = (),
) -> RdfScaffold:
    """Build named v2 proposals without asserting that their semantics are approved."""
    source_graph = _load_source_graph(source_root)
    table = URIRef(source_table_uri)
    if (table, RDF.type, BRONZE.SourceTable) not in source_graph:
        raise AuthoringScaffoldError(f"Unknown source table: {source_table_uri}")
    columns = _source_columns(source_graph, table)
    if not columns:
        raise AuthoringScaffoldError(f"Source table has no columns: {source_table_uri}")

    loaded = load_ontology(ontology_path, catalog_path=catalog_path, profile="kairos-design")
    target_class = loaded.semantic_index.class_by_uri(target_class_uri)
    if target_class is None:
        raise AuthoringScaffoldError(
            f"Target class does not resolve in the scoped domain closure: {target_class_uri}"
        )
    properties = loaded.semantic_index.class_properties(target_class_uri)
    candidates: dict[str, list[dict]] = {}
    for item in properties:
        prop = loaded.semantic_index.property_by_uri(item["property_uri"])
        if prop is None:
            continue
        for label in {prop.name, prop.label, _local_name(prop.uri)}:
            candidates.setdefault(_token(label), []).append(item)

    namespace = _mapping_namespace(source_table_uri, target_class_uri)
    graph = Graph()
    for prefix, value in (
        ("authoring", AUTHORING),
        ("kairos-map", KMAP),
        ("map", namespace),
        ("skos", SKOS),
    ):
        graph.bind(prefix, value)

    table_mapping = _resource(namespace, "table", source_table_uri, target_class_uri)
    graph.add((table_mapping, RDF.type, KMAP.TableMapping))
    graph.add((table_mapping, KMAP.sourceTable, table))
    graph.add((table_mapping, KMAP.targetClass, URIRef(target_class_uri)))
    graph.add((table_mapping, KMAP.mappingType, Literal("direct")))
    graph.add((table_mapping, KMAP.matchType, Literal("relatedMatch")))
    graph.add((table_mapping, KMAP.reviewState, Literal("proposed")))
    graph.add((table, SKOS.relatedMatch, URIRef(target_class_uri)))

    proposals = 1
    review_items = 0
    advisories = 0
    matched: set[str] = set()
    unmatched_columns: list[URIRef] = []
    for column in columns:
        name = _column_name(source_graph, column)
        matches = {item["property_uri"]: item for item in candidates.get(_token(name), ())}
        if len(matches) == 1:
            target_uri = next(iter(matches))
            mapping = _resource(namespace, "column", str(column), target_uri)
            graph.add((mapping, RDF.type, KMAP.ColumnMapping))
            graph.add((mapping, KMAP.sourceColumn, column))
            graph.add((mapping, KMAP.targetProperty, URIRef(target_uri)))
            graph.add((mapping, KMAP.matchType, Literal("closeMatch")))
            graph.add((mapping, KMAP.reviewState, Literal("proposed")))
            graph.add((column, SKOS.closeMatch, URIRef(target_uri)))
            matched.add(target_uri)
            proposals += 1
            continue

        review = _resource(namespace, "review", str(column))
        graph.add((review, RDF.type, AUTHORING.ReviewItem))
        graph.add((review, AUTHORING.reviewState, Literal("out-of-scope")))
        graph.add((review, KMAP.sourceColumn, column))
        reason = "no deterministic lexical target" if not matches else "ambiguous lexical targets"
        graph.add((review, RDFS.comment, Literal(reason)))
        unmatched_columns.append(column)
        review_items += 1

    mapped_classes: set[str] = set()
    mapped_properties: set[str] = set()
    for path in sorted(existing_mapping_paths):
        existing = Graph()
        existing.parse(path, format="turtle")
        facts = bind_mapping_graph(existing, include_proposals=True)
        mapped_classes.update(item.target_class_uri for item in facts.tables)
        mapped_properties.update(item.target_property_uri for item in facts.columns)
    for column in unmatched_columns:
        name_token = _token(_column_name(source_graph, column))
        likely = sorted(
            prop.uri
            for prop in loaded.semantic_index.properties
            if prop.uri in mapped_properties
            and any(domain.uri in mapped_classes - {target_class_uri} for domain in prop.domains)
            and name_token in {_token(prop.name), _token(prop.label), _token(_local_name(prop.uri))}
        )
        for property_uri in likely:
            advisory = _resource(namespace, "advisory", str(column), property_uri)
            graph.add((advisory, RDF.type, AUTHORING.DenormalizedOwnershipAdvisory))
            graph.add((advisory, AUTHORING.reviewState, Literal("out-of-scope")))
            graph.add((advisory, KMAP.sourceColumn, column))
            graph.add((advisory, KMAP.targetProperty, URIRef(property_uri)))
            graph.add(
                (
                    advisory,
                    RDFS.comment,
                    Literal("Likely denormalized column already owned by another mapped entity."),
                )
            )
            advisories += 1

    validation = validate_mapping_design(
        mapping_paths=(),
        mapping_graph=graph,
        source_root=source_root,
        ontology_path=ontology_path,
        catalog_path=catalog_path,
        include_proposals=True,
    )
    if not validation["passed"]:
        raise AuthoringScaffoldError(
            f"Generated mapping scaffold failed focused validation: {validation['diagnostics']}"
        )
    return RdfScaffold(graph, validation, proposals, review_items, advisories)


def _silver_type(source_type: str) -> str | None:
    value = source_type.casefold()
    if any(token in value for token in ("char", "text", "string", "varchar")):
        return "STRING"
    if "timestamp" in value or "datetime" in value:
        return "TIMESTAMP"
    if value == "date":
        return "DATE"
    if any(token in value for token in ("int", "long", "short")):
        return "BIGINT"
    if any(token in value for token in ("decimal", "numeric")):
        return "DECIMAL"
    if any(token in value for token in ("bool", "bit")):
        return "BOOLEAN"
    return None


def build_silver_scaffold(
    *,
    source_root: Path,
    ontology_path: Path,
    mapping_paths: Iterable[Path],
    shapes_path: Path,
    catalog_path: Path | None = None,
) -> RdfScaffold:
    """Build only mechanically evidenced Silver annotations and explicit review items."""
    source_graph = _load_source_graph(source_root)
    mapping_graph = Graph()
    for path in sorted(mapping_paths):
        mapping_graph.parse(path, format="turtle")
    facts = bind_mapping_graph(mapping_graph, include_proposals=True)
    if not facts.tables:
        raise AuthoringScaffoldError(
            "No TableMapping evidence is available for Silver scaffolding."
        )

    loaded = load_ontology(
        ontology_path,
        catalog_path=catalog_path,
        profile="asserted",
    )
    root_source = next(source for source in loaded.sources if source.manifest.import_depth == 0)
    ontology_resources = tuple(root_source.graph.subjects(RDF.type, OWL.Ontology))
    if len(ontology_resources) != 1:
        raise AuthoringScaffoldError("The domain ontology must declare exactly one owl:Ontology.")

    graph = Graph()
    for prefix, value in (
        ("authoring", AUTHORING),
        ("kairos-ext", EXT),
        ("owl", OWL),
        ("rdfs", RDFS),
    ):
        graph.bind(prefix, value)
    scaffold_ontology = URIRef(f"{ontology_resources[0]}/silver-scaffold")
    graph.add((scaffold_ontology, RDF.type, OWL.Ontology))
    graph.add((scaffold_ontology, RDFS.label, Literal("Evidence-grounded Silver scaffold")))
    graph.add(
        (
            scaffold_ontology,
            RDFS.comment,
            Literal(
                "Mechanical evidence only; every authoring:ReviewItem requires governance review."
            ),
        )
    )
    graph.add((scaffold_ontology, OWL.versionInfo, Literal("1.0.0")))

    table_by_column: dict[str, str] = {}
    for column in source_graph.subjects(RDF.type, BRONZE.SourceColumn):
        table = source_graph.value(column, BRONZE.sourceTable) or source_graph.value(
            column, BRONZE.belongsToTable
        )
        if isinstance(column, URIRef) and isinstance(table, URIRef):
            table_by_column[str(column)] = str(table)
    table_targets = {item.source_table_uri: item.target_class_uri for item in facts.tables}

    proposals = 0
    for table_uri, class_uri in sorted(table_targets.items()):
        target = URIRef(class_uri)
        graph.add((target, EXT.silverSourceRef, URIRef(table_uri)))
        graph.add((target, AUTHORING.reviewState, Literal("proposed")))
        proposals += 1
        for choice in (
            "businessGrain",
            "identityStrategy",
            "entityInstanceIriPolicy",
            "keyScope",
            "sourceIdentity",
            "changeDetectionStrategy",
            "scdType",
            "incrementalPolicy",
            "foreignKeyPolicy",
        ):
            item = _resource(AUTHORING, "silver-review", class_uri, choice)
            graph.add((item, RDF.type, AUTHORING.ReviewItem))
            graph.add((item, AUTHORING.reviewState, Literal("proposed")))
            graph.add((item, AUTHORING.forResource, target))
            graph.add((item, AUTHORING.governanceChoice, Literal(choice)))

    for column in facts.columns:
        table_uri = table_by_column.get(column.source_column_uri)
        if table_targets.get(table_uri or "") is None:
            continue
        source = URIRef(column.source_column_uri)
        target = URIRef(column.target_property_uri)
        graph.add((target, EXT.silverColumnName, Literal(_column_name(source_graph, source))))
        source_type = str(source_graph.value(source, BRONZE.dataType) or "")
        silver_type = _silver_type(source_type)
        if silver_type:
            graph.add((target, EXT.silverDataType, Literal(silver_type)))
        nullable = source_graph.value(source, BRONZE.nullable)
        if isinstance(nullable, Literal):
            graph.add(
                (
                    target,
                    EXT.nullable,
                    Literal(bool(nullable.toPython()), datatype=XSD.boolean),
                )
            )
        graph.add((target, AUTHORING.reviewState, Literal("proposed")))
        proposals += 1

    validation = validate_silver_extension(
        extension_path=None,
        extension_graph=graph,
        ontology_path=ontology_path,
        shapes_path=shapes_path,
        catalog_path=catalog_path,
    )
    if not validation["passed"]:
        raise AuthoringScaffoldError(
            f"Generated Silver scaffold failed focused validation: {validation['diagnostics']}"
        )
    review_items = len(tuple(graph.subjects(RDF.type, AUTHORING.ReviewItem)))
    return RdfScaffold(graph, validation, proposals, review_items)


def write_text(path: Path, content: str, *, overwrite: bool = False) -> None:
    """Write one scaffold only when explicitly allowed to replace an existing file."""
    if path.exists() and not overwrite:
        raise AuthoringScaffoldError(
            f"Refusing to overwrite existing file without --overwrite: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
