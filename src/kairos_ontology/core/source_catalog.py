# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical discovery and identity for Bronze source vocabularies."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdflib import RDF, Graph, Namespace, URIRef

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
KAIROS_DBT = Namespace("https://kairos.cnext.eu/dbt-contract#")


class SourceCatalogError(ValueError):
    """Raised when source vocabulary definitions conflict."""


@dataclass
class SourceCatalogTable:
    """One canonical SourceTable definition and its equivalent file views."""

    system: str
    table_name: str
    table_iri: str
    columns: list[dict[str, Any]]
    all_uris: set[str]
    generated: bool
    signature: tuple[str, ...]
    paths: list[Path] = field(default_factory=list)


@dataclass
class SourceCatalog:
    """Canonical source tables plus any conflicting duplicate definitions."""

    root: Path
    tables: dict[str, SourceCatalogTable] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    managed_generated_stems: set[str] = field(default_factory=set)

    def require_consistent(self) -> None:
        """Raise when any table IRI has divergent or cross-system authority."""

        if self.conflicts:
            raise SourceCatalogError("; ".join(self.conflicts))

    def analysis_tables(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Return non-generated tables grouped by stable source-system key."""

        systems: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for table in self.tables.values():
            if table.generated:
                continue
            systems.setdefault(table.system, {})[table.table_name] = table.columns
        return systems

    def generated_report_stems(self) -> set[str]:
        """Return legacy affinity report stems produced for generated vocab files."""

        stems = set(self.managed_generated_stems)
        ordinary_systems = {
            table.system for table in self.tables.values() if not table.generated
        }
        for table in self.tables.values():
            if not table.generated:
                continue
            stems.update(path.name.removesuffix(".vocabulary.ttl") for path in table.paths)
        return stems - ordinary_systems

    def superseded_report_stems(self) -> set[str]:
        """Return old per-file systems replaced by directory-level identity."""

        ordinary_systems = {
            table.system for table in self.tables.values() if not table.generated
        }
        stems = {
            path.name.removesuffix(".vocabulary.ttl")
            for table in self.tables.values()
            if not table.generated
            for path in table.paths
            if path.name.removesuffix(".vocabulary.ttl") != table.system
        }
        return stems - ordinary_systems

    def excluded_affinity_systems(self) -> set[str]:
        """Return generated and superseded systems that cannot own obligations."""

        return self.generated_report_stems() | self.superseded_report_stems()


def source_system_key(sources_dir: Path, vocab_file: Path) -> str:
    """Derive stable source identity from its top-level source directory."""

    relative = vocab_file.relative_to(sources_dir)
    if len(relative.parts) > 1:
        return relative.parts[0]
    return vocab_file.name.removesuffix(".vocabulary.ttl")


def _objects_signature(graph: Graph, subjects: set[URIRef]) -> tuple[str, ...]:
    triples = {
        f"{subject.n3()} {predicate.n3()} {value.n3()}"
        for subject in subjects
        for predicate, value in graph.predicate_objects(subject)
    }
    return tuple(sorted(triples))


def _table_definition(
    graph: Graph,
    table_uri: URIRef,
    *,
    system: str,
    path: Path,
    generated_path: bool,
) -> SourceCatalogTable:
    table_name = str(
        graph.value(table_uri, KAIROS_BRONZE.tableName)
        or str(table_uri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    )
    column_uris = set(graph.subjects(KAIROS_BRONZE.belongsToTable, table_uri))
    column_uris.update(graph.subjects(KAIROS_BRONZE.sourceTable, table_uri))
    source_systems = set(graph.objects(table_uri, KAIROS_BRONZE.sourceSystem))
    source_systems.update(graph.objects(table_uri, KAIROS_BRONZE.belongsToSystem))
    subjects = {
        subject for subject in {table_uri, *column_uris} if isinstance(subject, URIRef)
    }
    generated = generated_path or any(
        str(graph.value(subject, KAIROS_DBT.sourceKind) or "") == "dbt-contract"
        for subject in {table_uri, *source_systems}
    )
    columns: list[dict[str, Any]] = []
    for column_uri in sorted(column_uris, key=str):
        column_name = str(
            graph.value(column_uri, KAIROS_BRONZE.columnName)
            or str(column_uri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        )
        sample_values = graph.value(column_uri, KAIROS_BRONZE.sampleValues)
        columns.append(
            {
                "name": column_name,
                "data_type": str(
                    graph.value(column_uri, KAIROS_BRONZE.dataType) or "unknown"
                ),
                "nullable": bool(graph.value(column_uri, KAIROS_BRONZE.nullable)),
                "samples": str(sample_values).split(" | ") if sample_values else [],
            }
        )
    return SourceCatalogTable(
        system=system,
        table_name=table_name,
        table_iri=str(table_uri),
        columns=columns,
        all_uris={str(table_uri), *(str(column) for column in column_uris)},
        generated=generated,
        signature=_objects_signature(graph, subjects),
        paths=[path],
    )


def build_source_catalog(
    sources_dir: Path,
    *,
    generated_sources_dirs: Iterable[Path] = (),
) -> SourceCatalog:
    """Parse all Bronze vocabularies and reconcile equivalent file views."""

    root = Path(sources_dir).resolve()
    catalog = SourceCatalog(root=root)
    if not root.is_dir():
        return catalog

    generated_roots = {
        (root / "custom-transformations").resolve(),
        *(Path(path).resolve() for path in generated_sources_dirs),
    }
    for vocab_file in sorted(root.rglob("*.vocabulary.ttl")):
        resolved = vocab_file.resolve()
        generated_path = any(resolved.is_relative_to(path) for path in generated_roots)
        if generated_path:
            catalog.managed_generated_stems.add(
                resolved.name.removesuffix(".vocabulary.ttl")
            )
        graph = Graph()
        try:
            graph.parse(resolved, format="turtle")
        except Exception as exc:
            if any(resolved.is_relative_to(path) for path in generated_roots):
                continue
            catalog.conflicts.append(
                f"Could not parse Bronze vocabulary {resolved}: {exc}"
            )
            continue
        system = source_system_key(root, resolved)
        for table_uri in graph.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
            if not isinstance(table_uri, URIRef):
                continue
            current = _table_definition(
                graph,
                table_uri,
                system=system,
                path=resolved,
                generated_path=generated_path,
            )
            previous = catalog.tables.get(current.table_iri)
            if previous is None:
                catalog.tables[current.table_iri] = current
                continue
            if (
                previous.system != current.system
                or previous.signature != current.signature
                or previous.generated != current.generated
            ):
                catalog.conflicts.append(
                    f"Bronze SourceTable IRI {current.table_iri!r} has conflicting "
                    f"definitions in {previous.paths[0]} and {resolved}"
                )
                continue
            previous.paths.append(resolved)
    names: dict[tuple[str, str], str] = {}
    for table in catalog.tables.values():
        key = (table.system, table.table_name)
        previous_iri = names.get(key)
        if previous_iri is not None and previous_iri != table.table_iri:
            catalog.conflicts.append(
                f"Source system {table.system!r} defines table name "
                f"{table.table_name!r} with both {previous_iri!r} and "
                f"{table.table_iri!r}"
            )
        names[key] = table.table_iri
    return catalog
