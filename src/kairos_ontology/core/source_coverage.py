# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic source-coverage gate (DD-061).

Pre-silver counterpart to the reference-model inventory gate (DD-047).  Verifies
that every source table the affinity reports assign to an in-scope data domain is
actually represented by a source-to-domain mapping, before the silver projection
is allowed to run.

Where ``check-alignment`` gates the *inputs* to modeling (was ``propose-alignment``
run completely?), this gates the *outputs* of modeling/mapping (does the modeled
ontology + mappings actually cover every domain table?).  Both sides are committed,
structured RDF/YAML, so the check is deterministic and AI-free:

  - affinity reports (``_analysis/*-affinity.yaml``) enumerate the ``(system, table)``
    pairs each domain must cover;
  - bronze vocabularies (``*.vocabulary.ttl``) give every table its columns;
  - mapping files (``model/mappings/*.ttl``) declare, via SKOS match predicates,
    which bronze tables/columns map to domain entities.

A table is **covered** when the table URI — or any of its column URIs — is the
subject of a SKOS match statement in the mapping files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import RDF, Graph, Namespace
from rdflib.namespace import SKOS

from .alignment_coverage import load_affinity_domain_tables

logger = logging.getLogger(__name__)

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")

#: SKOS predicates that establish a source→domain mapping.
_MATCH_PREDICATES = (
    SKOS.exactMatch,
    SKOS.closeMatch,
    SKOS.narrowMatch,
    SKOS.broadMatch,
    SKOS.relatedMatch,
)


def collect_mapped_subjects(mappings_dir: Path) -> set[str]:
    """Return the set of subject URIs that participate in a SKOS mapping.

    A subject (bronze table or column URI) counts as mapped when it carries any
    SKOS match predicate in the mapping TTLs.
    """
    mapped: set[str] = set()
    if not mappings_dir or not mappings_dir.is_dir():
        return mapped

    g = Graph()
    for ttl in sorted(mappings_dir.rglob("*.ttl")):
        try:
            g.parse(ttl, format="turtle")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not parse mapping file %s: %s", ttl.name, exc)

    for predicate in _MATCH_PREDICATES:
        for subj, _obj in g.subject_objects(predicate):
            mapped.add(str(subj))
    return mapped


def collect_source_tables(sources_dir: Path) -> dict[tuple[str, str], set[str]]:
    """Map each ``(system, table)`` to the set of its bronze URIs.

    The URI set contains the table URI plus every column URI, so a mapping on any
    of them marks the table covered.  ``system`` is the vocabulary file stem
    (matching how affinity reports name systems).
    """
    result: dict[tuple[str, str], set[str]] = {}
    if not sources_dir or not sources_dir.is_dir():
        return result

    for vocab_file in sorted(sources_dir.rglob("*.vocabulary.ttl")):
        system = vocab_file.stem.replace(".vocabulary", "")
        g = Graph()
        try:
            g.parse(vocab_file, format="turtle")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not parse vocabulary %s: %s", vocab_file.name, exc)
            continue

        for tbl_uri in g.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
            tbl_name = str(
                g.value(tbl_uri, KAIROS_BRONZE.tableName)
                or str(tbl_uri).split("#")[-1].split("/")[-1]
            )
            uris = {str(tbl_uri)}
            col_uris = set(g.subjects(KAIROS_BRONZE.belongsToTable, tbl_uri))
            col_uris.update(g.subjects(KAIROS_BRONZE.sourceTable, tbl_uri))
            uris.update(str(c) for c in col_uris)
            result[(system, tbl_name)] = uris

    return result


@dataclass
class SourceCoverageReport:
    """Result of a deterministic source-coverage check (DD-061)."""

    #: domain → sorted "system.table" strings that are affinity-assigned but unmapped
    uncovered: dict[str, list[str]] = field(default_factory=dict)
    #: domain → (covered_count, total_count)
    domain_counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: domains present in affinity but with zero source tables resolvable from vocab
    unresolved_domains: list[str] = field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        """True when any in-scope domain has an uncovered (unmapped) table."""
        return any(self.uncovered.values())

    @property
    def total_uncovered(self) -> int:
        return sum(len(v) for v in self.uncovered.values())

    def coverage_pct(self, domain: str) -> float:
        covered, total = self.domain_counts.get(domain, (0, 0))
        return 100.0 * covered / total if total else 100.0


def check_source_coverage(
    *,
    analysis_dir: Path,
    sources_dir: Path,
    mappings_dir: Path,
    domains_filter: list[str] | None = None,
) -> SourceCoverageReport:
    """Verify every affinity-assigned source table is mapped to a domain entity.

    For each in-scope domain, compares the ``(system, table)`` pairs the affinity
    reports assign to it against the tables whose bronze table/column URIs appear
    in a SKOS mapping.  Uncovered tables are blocking.
    """
    report = SourceCoverageReport()
    domain_tables = load_affinity_domain_tables(analysis_dir)
    mapped_subjects = collect_mapped_subjects(mappings_dir)
    source_tables = collect_source_tables(sources_dir)

    lower_filter = [d.lower() for d in domains_filter] if domains_filter else None

    def in_scope(domain: str) -> bool:
        if lower_filter is None:
            return True
        return any(f in domain.lower() for f in lower_filter)

    for domain in sorted(domain_tables):
        if not in_scope(domain):
            continue
        expected = domain_tables[domain]
        uncovered: list[str] = []
        covered = 0
        for system, table in sorted(expected):
            uris = source_tables.get((system, table))
            if uris and (uris & mapped_subjects):
                covered += 1
            else:
                uncovered.append(f"{system}.{table}")
        report.domain_counts[domain] = (covered, len(expected))
        if uncovered:
            report.uncovered[domain] = uncovered
        if covered == 0 and not any(
            (s, t) in source_tables for s, t in expected
        ):
            report.unresolved_domains.append(domain)

    return report
