# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Source-coverage evaluator over canonical completeness facts (DD-094).

Direct coverage is derived only from committed source-to-domain SKOS mappings.
Governed replacement coverage is derived only from committed dbt-contract, Claim
Registry, virtual mapping, and Silver-routing evidence.  Proposal evidence never
counts as mapping coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Namespace

from .completeness_model import (
    KAIROS_EXT,
    CompletenessFacts,
    MappingRecord,
    ReplacementCoverageEvidence,
    SourceTableRecord,
    collect_mapped_subjects,
    collect_mapping_records,
    collect_source_table_records,
    collect_source_tables,
    compute_completeness_facts,
)

# Kept as public module constants for callers that previously imported them here.
KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
KAIROS_DBT = Namespace("https://kairos.cnext.eu/dbt-contract#")

__all__ = (
    "KAIROS_BRONZE",
    "KAIROS_DBT",
    "KAIROS_EXT",
    "MappingRecord",
    "ReplacementCoverageEvidence",
    "SourceCoverageReport",
    "SourceTableRecord",
    "check_source_coverage",
    "collect_mapped_subjects",
    "collect_mapping_records",
    "collect_source_table_records",
    "collect_source_tables",
    "evaluate_source_coverage",
)


@dataclass
class SourceCoverageReport:
    """Result of deterministic direct and governed-replacement coverage checks."""

    uncovered: dict[str, list[str]] = field(default_factory=dict)
    domain_counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    unresolved_domains: list[str] = field(default_factory=list)
    direct_counts: dict[str, int] = field(default_factory=dict)
    replacement_counts: dict[str, int] = field(default_factory=dict)
    diagnostics: dict[str, list[str]] = field(default_factory=dict)
    replacement_evidence: dict[str, list[ReplacementCoverageEvidence]] = field(
        default_factory=dict
    )

    @property
    def is_blocking(self) -> bool:
        """Return whether any source is uncovered or a replacement invariant failed."""

        return any(self.uncovered.values()) or any(self.diagnostics.values())

    @property
    def total_uncovered(self) -> int:
        """Return the number of uncovered affinity table assignments."""

        return sum(len(values) for values in self.uncovered.values())

    def coverage_pct(self, domain: str) -> float:
        """Return the mapped percentage for one domain."""

        covered, total = self.domain_counts.get(domain, (0, 0))
        return 100.0 * covered / total if total else 100.0


def _append_unique(values: list[str], additions: tuple[str, ...]) -> None:
    """Append diagnostics once while preserving canonical fact order."""

    for message in additions:
        if message not in values:
            values.append(message)


def evaluate_source_coverage(facts: CompletenessFacts) -> SourceCoverageReport:
    """Evaluate the source mapping gate over canonical completeness facts."""

    if not facts.mapping_evaluated:
        raise ValueError(
            "source coverage requires completeness facts computed with sources_dir and mappings_dir"
        )

    report = SourceCoverageReport()
    for domain_fact in facts.domains:
        domain = domain_fact.domain
        table_facts = facts.tables_for_domain(domain)
        uncovered: list[str] = []
        diagnostics: list[str] = []
        direct_count = 0
        replacement_count = 0

        for fact in table_facts:
            coverage = fact.mapping
            _append_unique(diagnostics, coverage.reasons)
            if coverage.state == "direct":
                direct_count += 1
                continue
            if coverage.state == "governed_replacement":
                replacement_count += 1
                report.replacement_evidence.setdefault(domain, []).extend(
                    coverage.replacement.evidence
                )
                continue
            uncovered.append(f"{fact.system}.{fact.table}")

        covered = direct_count + replacement_count
        report.domain_counts[domain] = (covered, len(table_facts))
        report.direct_counts[domain] = direct_count
        report.replacement_counts[domain] = replacement_count
        if uncovered:
            report.uncovered[domain] = uncovered
        if diagnostics:
            report.diagnostics[domain] = diagnostics
        if covered == 0 and not any(fact.source_table_iris for fact in table_facts):
            report.unresolved_domains.append(domain)

    return report


def check_source_coverage(
    *,
    analysis_dir: Path,
    sources_dir: Path,
    mappings_dir: Path,
    domains_filter: list[str] | None = None,
    claims_dir: Path | None = None,
    extensions_dir: Path | None = None,
    hub_root: Path | None = None,
    transforms_dir: Path | None = None,
    facts: CompletenessFacts | None = None,
) -> SourceCoverageReport:
    """Build canonical facts when needed, then evaluate source mapping coverage."""

    facts = facts or compute_completeness_facts(
        analysis_dir=analysis_dir,
        claims_dir=claims_dir,
        sources_dir=sources_dir,
        mappings_dir=mappings_dir,
        domains_filter=domains_filter,
        extensions_dir=extensions_dir,
        hub_root=hub_root,
        transforms_dir=transforms_dir,
    )
    return evaluate_source_coverage(facts)
