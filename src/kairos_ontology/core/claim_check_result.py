# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Versioned, machine-readable ``check-claims`` result (DD-122).

Composes the existing, independently governed evaluators into one
JSON-serializable result, each facet reported on its own so a caller never has
to guess which reason belongs to which gate:

* **registry** — Claim Registry validity/freshness + governance (proposed
  count, MDM-anchor/deviation/ownership/passthrough policy) —
  :func:`claim_coverage.check_claims_coverage`;
* **semantic_generation** — per-domain/table semantic-generation reliability.
  Consumes the *additive* ``ClaimRegistry.generation_outcomes`` metadata
  (``propose-alignment``'s typed per-table outcome, surfaced non-blocking via
  :attr:`claim_coverage.ClaimCheckReport.incomplete_generation`) when present.
  A registry written before this feature existed — or with a fully
  ``semantic_success`` run — simply carries no incomplete-generation entries,
  so legacy artifacts are tolerated (vacuously complete), never penalized;
* **mapping** — source-to-domain coverage —
  :func:`source_coverage.check_source_coverage` (owned by
  ``kairos-design-mapping``, see :attr:`SourceCoverageReport.owner_skill`);
* **projection_sync** — claims ↔ ``owl:imports``/``silverInclude`` drift, plus
  any :class:`reference_modules.DisputedClaimModule` entries —
  :func:`claim_projection_sync.evaluate_projection_sync` (owned by
  ``kairos-design-domain``, see :attr:`ProjectionSyncReport.owner_skill`).

``curation_complete`` is the **only** composite/blocking signal this module
introduces: it is true iff the registry facet is clear (registry validity,
freshness, and semantic/governance policy — MDM-anchor, deviation, ownership,
duplicate-approved, column-omission, grain-conflict — DD-094) and, only under
``strict=True``, no registry carries an undecided (``proposed``) claim.
``semantic_generation``, ``mapping``, and ``projection_sync`` are deliberately
**excluded** from ``curation_complete`` — they stay visible in their own
sections (mapping/sync additionally carry ``owner_skill``) but block only in
their owning workflows (``kairos-design-mapping`` for mapping,
``kairos-design-domain``/``claims-to-silver-ext --check-only`` for sync), never
in ``check-claims`` itself (DD-122).

This module is read-only and side-effect free: it never mutates a claim, never
regenerates an ontology/extension file, and never runs a projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .claim_coverage import ClaimCheckReport, check_claims_coverage
from .claim_projection_sync import ProjectionSyncReport, evaluate_projection_sync
from .completeness_model import compute_completeness_facts
from .lifecycle_gate import (
    _claim_report_to_dict,
    _projection_sync_to_dict,
    _source_coverage_to_dict,
)
from .source_coverage import SourceCoverageReport, check_source_coverage

#: Schema version of :meth:`ClaimCheckResult.to_dict` (DD-122). Bump only on a
#: breaking change (removed/renamed key or changed meaning); additive new keys
#: do not require a bump.
CLAIM_CHECK_RESULT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SemanticGenerationFact:
    """One domain's semantic-generation reliability (DD-122).

    ``incomplete_tables`` are ``"system.table: outcome (error)"`` strings for
    every table whose ``propose-alignment`` run did not reach
    ``semantic_success`` — the literal
    :attr:`claim_coverage.ClaimCheckReport.incomplete_generation` entries for
    this domain. Empty when the domain has no such entries, whether because
    every table succeeded or because its registry predates the
    ``generation_outcomes`` feature (legacy artifact, tolerated).
    """

    domain: str
    incomplete_tables: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.incomplete_tables

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "incomplete_tables": list(self.incomplete_tables),
            "complete": self.complete,
        }


@dataclass(frozen=True)
class SemanticGenerationSummary:
    """Semantic-generation completeness across every domain with a signal.

    Consumes the additive ``generation_outcomes`` metadata via
    :attr:`claim_coverage.ClaimCheckReport.incomplete_generation` — it never
    re-derives or duplicates that computation. Domains with no entry (legacy
    registries, or a fully-successful run) are vacuously complete.
    """

    domains: tuple[SemanticGenerationFact, ...] = ()

    @property
    def complete(self) -> bool:
        return all(fact.complete for fact in self.domains)

    def to_dict(self) -> dict:
        return {
            "domains": [fact.to_dict() for fact in self.domains],
            "complete": self.complete,
        }


@dataclass
class ClaimCheckResult:
    """One versioned, machine-readable ``check-claims`` result (DD-122)."""

    schema_version: int
    hub_root: str
    strict: bool
    registry: ClaimCheckReport
    semantic_generation: SemanticGenerationSummary = field(
        default_factory=SemanticGenerationSummary
    )
    mapping: SourceCoverageReport | None = None
    projection_sync: ProjectionSyncReport = field(default_factory=ProjectionSyncReport)

    @property
    def disputed_claims(self) -> list:
        """Claim IDs (with their disputed module) retaining a disputed module
        (DD-122): a deferred/rejected claim whose reference module is still
        active for another reason. Flattened across every evaluated domain."""
        return list(self.projection_sync.disputed_claims)

    @property
    def curation_complete(self) -> bool:
        """True iff registry validity/freshness/semantic-policy pass and,
        under ``strict``, no undecided (``proposed``) claim remains.
        ``semantic_generation``/``mapping``/``projection_sync`` never gate
        this — see module docstring (DD-122)."""
        if self.registry.is_blocking:
            return False
        if self.strict and self.registry.has_undecided_claims():
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "hub_root": self.hub_root,
            "strict": self.strict,
            "curation_complete": self.curation_complete,
            "registry": _claim_report_to_dict(self.registry),
            "semantic_generation": self.semantic_generation.to_dict(),
            "mapping": (
                _source_coverage_to_dict(self.mapping) if self.mapping is not None else None
            ),
            "projection_sync": _projection_sync_to_dict(self.projection_sync),
            "disputed_claims": self.disputed_claims,
        }


def build_claim_check_result(
    *,
    hub_root: Path,
    claims_dir: Path,
    analysis_dir: Path,
    sources_dir: Path,
    mappings_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
    domains_filter: list[str] | None = None,
    data_domains: dict[str, object] | None = None,
    check_mdm_anchor: bool = True,
    check_ownership: bool = True,
    no_source_coverage: bool = False,
    no_extension_sync: bool = False,
    strict: bool = False,
) -> ClaimCheckResult:
    """Compose the deterministic, versioned ``check-claims`` result.

    Mirrors :func:`lifecycle_gate.evaluate_lifecycle_gate`'s composition of the
    registry/mapping/sync evaluators (same shared
    :class:`completeness_model.CompletenessFacts` instance, so ``check-claims``
    and ``check-release`` never see divergent facts) but stops at curation
    scope — it never evaluates release/validation/project facts, which remain
    ``check-release``'s (and ``kairos-execute-validate``'s) job.
    """
    hub_root = Path(hub_root)
    transforms_dir = hub_root / "integration" / "transforms" / "dbt"

    facts = compute_completeness_facts(
        analysis_dir=analysis_dir,
        claims_dir=claims_dir,
        sources_dir=sources_dir,
        mappings_dir=None if no_source_coverage else mappings_dir,
        domains_filter=domains_filter,
        extensions_dir=None if no_source_coverage else extensions_dir,
        hub_root=None if no_source_coverage else hub_root,
        transforms_dir=None if no_source_coverage else transforms_dir,
    )

    registry_report = check_claims_coverage(
        claims_dir=claims_dir,
        analysis_dir=analysis_dir,
        data_domains=data_domains,
        domains_filter=domains_filter,
        check_mdm_anchor=check_mdm_anchor,
        check_ownership=check_ownership,
        facts=facts,
    )

    mapping_report: SourceCoverageReport | None = None
    if not no_source_coverage:
        mapping_report = check_source_coverage(
            analysis_dir=analysis_dir,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            domains_filter=domains_filter,
            claims_dir=claims_dir,
            extensions_dir=extensions_dir,
            hub_root=hub_root,
            transforms_dir=transforms_dir,
            facts=facts,
        )

    sync_report = (
        evaluate_projection_sync(
            claims_dir=claims_dir,
            ontologies_dir=ontologies_dir,
            extensions_dir=extensions_dir,
            domains_filter=domains_filter,
        )
        if not no_extension_sync
        else ProjectionSyncReport()
    )

    semantic_generation = SemanticGenerationSummary(
        domains=tuple(
            SemanticGenerationFact(domain=domain, incomplete_tables=tuple(tables))
            for domain, tables in sorted(registry_report.incomplete_generation.items())
        )
    )

    return ClaimCheckResult(
        schema_version=CLAIM_CHECK_RESULT_SCHEMA_VERSION,
        hub_root=str(hub_root),
        strict=strict,
        registry=registry_report,
        semantic_generation=semantic_generation,
        mapping=mapping_report,
        projection_sync=sync_report,
    )
