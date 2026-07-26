# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Preview and apply the legacy dbt virtual-column IRI migration."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from .dbt_contract_sync import (
    KAIROS_BRONZE,
    KAIROS_DBT,
    column_iri,
    legacy_column_iri,
)


class ColumnIriMigrationError(ValueError):
    """Raised when a column IRI migration cannot be applied safely."""


@dataclass(frozen=True)
class ColumnIriChange:
    """One legacy to PN_LOCAL-safe IRI replacement."""

    old_iri: str
    new_iri: str
    files: tuple[Path, ...]


@dataclass(frozen=True)
class ColumnIriMigrationReport:
    """Deterministic migration preview or apply result."""

    applied: bool
    changes: tuple[ColumnIriChange, ...]
    changed_files: tuple[Path, ...]
    backup_dir: Path | None = None


def _rdf_paths(hub_root: Path) -> tuple[Path, ...]:
    roots = (
        hub_root / "integration" / "sources",
        hub_root / "model" / "mappings",
    )
    return tuple(sorted(path for root in roots if root.is_dir() for path in root.rglob("*.ttl")))


def _load_graphs(paths: tuple[Path, ...]) -> dict[Path, Graph]:
    graphs: dict[Path, Graph] = {}
    for path in paths:
        graph = Graph()
        try:
            graph.parse(path, format="turtle")
        except Exception as exc:
            raise ColumnIriMigrationError(f"Cannot parse {path}: {exc}") from exc
        graphs[path] = graph
    return graphs


def _candidate_replacements(graphs: dict[Path, Graph]) -> dict[URIRef, URIRef]:
    replacements: dict[URIRef, URIRef] = {}
    for graph in graphs.values():
        for resource in graph.subjects(RDF.type, KAIROS_BRONZE.SourceColumn):
            if not isinstance(resource, URIRef):
                continue
            if graph.value(resource, KAIROS_DBT.modelRef) is None:
                continue
            table = graph.value(resource, KAIROS_BRONZE.sourceTable)
            name = graph.value(resource, KAIROS_BRONZE.columnName)
            if not isinstance(table, URIRef) or not isinstance(name, Literal):
                continue
            legacy = legacy_column_iri(str(table), str(name))
            if resource == legacy:
                replacements[resource] = column_iri(str(table), str(name))
    return replacements


def _detect_collisions(graphs: dict[Path, Graph], replacements: dict[URIRef, URIRef]) -> None:
    targets: dict[URIRef, URIRef] = {}
    all_terms = {
        term
        for graph in graphs.values()
        for triple in graph
        for term in triple
        if isinstance(term, URIRef)
    }
    for old, new in replacements.items():
        previous = targets.get(new)
        if previous is not None and previous != old:
            raise ColumnIriMigrationError(
                f"Column IRI collision: {previous} and {old} both migrate to {new}"
            )
        if new in all_terms:
            raise ColumnIriMigrationError(
                f"Column IRI collision: migration target already exists: {new}"
            )
        targets[new] = old


def _rewrite_graph(graph: Graph, replacements: dict[URIRef, URIRef]) -> bool:
    changed = False
    for subject, predicate, object_ in tuple(graph):
        rewritten = (
            replacements.get(subject, subject),
            replacements.get(predicate, predicate),
            replacements.get(object_, object_),
        )
        if rewritten != (subject, predicate, object_):
            graph.remove((subject, predicate, object_))
            graph.add(rewritten)
            changed = True
    return changed


def migrate_column_iris(
    hub_root: Path,
    *,
    apply: bool = False,
    backup_dir: Path | None = None,
) -> ColumnIriMigrationReport:
    """Preview or apply legacy virtual-column IRI replacements across a hub."""

    root = Path(hub_root).resolve()
    if not root.is_dir():
        raise ColumnIriMigrationError(f"Hub directory does not exist: {root}")
    if apply and backup_dir is None:
        raise ColumnIriMigrationError("--apply requires an explicit --backup-dir")
    if not apply and backup_dir is not None:
        raise ColumnIriMigrationError("--backup-dir is only valid with --apply")

    paths = _rdf_paths(root)
    graphs = _load_graphs(paths)
    replacements = _candidate_replacements(graphs)
    _detect_collisions(graphs, replacements)

    changed_paths = tuple(
        path for path, graph in graphs.items() if _rewrite_graph(graph, replacements)
    )
    changes = tuple(
        ColumnIriChange(
            str(old),
            str(new),
            tuple(path for path in changed_paths if any(new in triple for triple in graphs[path])),
        )
        for old, new in sorted(replacements.items(), key=lambda pair: str(pair[0]))
    )
    if not apply or not changed_paths:
        return ColumnIriMigrationReport(False, changes, changed_paths)

    backup = Path(backup_dir).resolve()
    if backup.exists():
        raise ColumnIriMigrationError(f"Backup path already exists; refusing overwrite: {backup}")
    if backup.is_relative_to(root):
        raise ColumnIriMigrationError("Backup directory must be outside the hub being migrated")
    backup.mkdir(parents=True)
    for path in changed_paths:
        destination = backup / path.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    for path in changed_paths:
        graphs[path].serialize(path, format="turtle")

    return ColumnIriMigrationReport(True, changes, changed_paths, backup)
