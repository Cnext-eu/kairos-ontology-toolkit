# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Claim-independent source affinity and SKOS mapping analysis."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml
from rdflib import Graph, URIRef
from rdflib.namespace import SKOS

from .source_catalog import SourceCatalog, build_source_catalog

logger = logging.getLogger(__name__)

ALIGNMENT_HASH_SCHEMA_VERSION = 2
ALIGNMENT_ALGORITHM_VERSION = 2

_MATCH_PREDICATES = (
    SKOS.exactMatch,
    SKOS.closeMatch,
    SKOS.narrowMatch,
    SKOS.broadMatch,
    SKOS.relatedMatch,
)


@dataclass(frozen=True)
class AffinityAssignment:
    """One domain assignment for a source-system table."""

    domain: str
    system: str
    table: str
    total_columns: int = 0


@dataclass(frozen=True)
class MappingRecord:
    """One committed source-to-domain SKOS statement."""

    source_uri: str
    predicate_uri: str
    target_uri: str
    path: Path


@dataclass(frozen=True)
class SourceTableRecord:
    """Canonical source-table identity and all mapping-eligible IRIs."""

    table_uris: frozenset[str] = frozenset()
    all_uris: frozenset[str] = frozenset()


def compute_affinity_hash(pairs: Iterable[tuple[str, str]]) -> str:
    """Return a deterministic SHA-256 over a domain's ``(system, table)`` set."""
    items = sorted({f"{system}\t{table}" for system, table in pairs})
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()


def load_affinity_assignments(
    analysis_dir: Path,
    *,
    excluded_systems: set[str] | None = None,
) -> tuple[AffinityAssignment, ...]:
    """Read schema-v2 affinity assignments from committed report files."""
    assignments: dict[tuple[str, str, str], AffinityAssignment] = {}
    if not analysis_dir.is_dir():
        return ()
    excluded = excluded_systems or set()
    for affinity_file in sorted(analysis_dir.glob("*-affinity.yaml")):
        try:
            data = yaml.safe_load(affinity_file.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not read affinity file %s: %s", affinity_file, exc)
            continue
        if not isinstance(data, dict) or data.get("schema_version") != 2:
            continue
        system = str(data.get("system", affinity_file.stem.replace("-affinity", "")) or "")
        if system in excluded:
            continue
        for raw_table in data.get("tables", []):
            if not isinstance(raw_table, dict):
                continue
            domain = str(raw_table.get("domain", "") or "")
            table = str(raw_table.get("table", "") or "")
            if not domain or not table:
                continue
            try:
                total_columns = int(raw_table.get("total_columns", 0) or 0)
            except (TypeError, ValueError):
                total_columns = 0
            item = AffinityAssignment(domain, system, table, total_columns)
            assignments[(domain, system, table)] = item
    return tuple(
        sorted(assignments.values(), key=lambda item: (item.domain, item.system, item.table))
    )


def load_affinity_domain_tables(
    analysis_dir: Path,
    *,
    excluded_systems: set[str] | None = None,
) -> dict[str, set[tuple[str, str]]]:
    """Map every domain to its assigned ``(system, table)`` set."""
    result: dict[str, set[tuple[str, str]]] = {}
    for item in load_affinity_assignments(analysis_dir, excluded_systems=excluded_systems):
        result.setdefault(item.domain, set()).add((item.system, item.table))
    return result


def load_affinity_domain_table_columns(
    analysis_dir: Path,
    *,
    excluded_systems: set[str] | None = None,
) -> dict[str, dict[tuple[str, str], int]]:
    """Map every domain to affinity-recorded source-column counts."""
    result: dict[str, dict[tuple[str, str], int]] = {}
    for item in load_affinity_assignments(analysis_dir, excluded_systems=excluded_systems):
        result.setdefault(item.domain, {})[(item.system, item.table)] = item.total_columns
    return result


def collect_mapping_records(mappings_dir: Path) -> list[MappingRecord]:
    """Return committed, mapping-eligible SKOS statements from Turtle files."""
    records: list[MappingRecord] = []
    if not mappings_dir or not mappings_dir.is_dir():
        return records
    for ttl in sorted(mappings_dir.rglob("*.ttl")):
        graph = Graph()
        try:
            graph.parse(ttl, format="turtle")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not parse mapping file %s: %s", ttl.name, exc)
            continue
        for predicate in _MATCH_PREDICATES:
            for subject, target in graph.subject_objects(predicate):
                if isinstance(subject, URIRef) and isinstance(target, URIRef):
                    records.append(MappingRecord(str(subject), str(predicate), str(target), ttl))
    return sorted(
        records,
        key=lambda item: (
            item.source_uri,
            item.predicate_uri,
            item.target_uri,
            str(item.path),
        ),
    )


def collect_mapped_subjects(mappings_dir: Path) -> set[str]:
    """Return source IRIs participating in a supported SKOS mapping."""
    return {record.source_uri for record in collect_mapping_records(mappings_dir)}


def _source_table_records_from_catalog(
    catalog: SourceCatalog,
) -> dict[tuple[str, str], SourceTableRecord]:
    values: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
    for table in sorted(
        catalog.tables.values(),
        key=lambda item: (item.system, item.table_name, item.table_iri),
    ):
        table_uris, all_uris = values.setdefault((table.system, table.table_name), (set(), set()))
        table_uris.add(table.table_iri)
        all_uris.update(table.all_uris)
    return {
        key: SourceTableRecord(frozenset(table_uris), frozenset(all_uris))
        for key, (table_uris, all_uris) in values.items()
    }


def collect_source_table_records(
    sources_dir: Path,
) -> dict[tuple[str, str], SourceTableRecord]:
    """Index canonical Bronze tables by affinity key."""
    if not sources_dir or not sources_dir.is_dir():
        return {}
    return _source_table_records_from_catalog(build_source_catalog(sources_dir))


def collect_source_tables(sources_dir: Path) -> dict[tuple[str, str], set[str]]:
    """Return the source table/column URI index."""
    return {
        key: set(record.all_uris)
        for key, record in collect_source_table_records(sources_dir).items()
    }
