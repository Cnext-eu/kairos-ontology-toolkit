# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic lifecycle gate (DD-100): one entrypoint, composed reasons.

``core/status.py`` is the sole machine truth for *objective lifecycle state*
(what phase/instance is not-started/in-progress/done, DD-080) and now also
surfaces per-instance machine-readable facts (claim ``proposed``/``approved``
counts, Silver ``bound_classes``/``aspirational_classes``/``release_eligible``,
validate ``data_valid`` — DD-096/DD-100). This module answers the orthogonal
question *"may this hub ship?"* by composing the existing, independently
governed evaluators into one deterministic report:

* **claim validity/freshness** (+ MDM-anchor/deviation/ownership/passthrough
  governance) — :func:`claim_coverage.check_claims_coverage`;
* **source completeness** (direct + governed-replacement mapping coverage) —
  :func:`source_coverage.check_source_coverage`;
* **extension sync** (claims ↔ ``owl:imports``/``silverInclude`` drift) —
  :func:`claim_projection_sync.evaluate_projection_sync`;
* **aspirational release blockers** (approved, materialization-eligible,
  unbound claims, DD-096/DEC-1) — the canonical
  :func:`binding_analysis.analyze_domain_from_hub`, the same authority the
  ``status`` scan uses for D4 aspirational-stub reporting;
* **validation** and **projection** — read (never re-run) from
  :func:`status.scan_hub_status`'s ``validate``/``project`` phases.

Every section is the *literal* return value (or a thin, lossless read) of its
existing evaluator — this module never re-implements a rule, so each keeps its
own reasons and blocking semantics exactly as when run standalone (e.g. via
``kairos-ontology check-claims``). Composition is a pure ``OR`` of each
section's own ``is_blocking``/``release_eligible`` signal.

This module is read-only and side-effect free: it never runs validation or a
projection, never approves a claim, and never persists an ``aspirational``
flag — release eligibility and validation/projection facts are recomputed
fresh on every call, exactly like ``kairos-ontology status``. No AI/LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .binding_analysis import analyze_domain_from_hub
from .claim_coverage import ClaimCheckReport, check_claims_coverage
from .claim_projection_sync import ProjectionSyncReport, evaluate_projection_sync
from .completeness_model import compute_completeness_facts
from .source_coverage import SourceCoverageReport, check_source_coverage
from .status import HubStatus, scan_hub_status
from .transformation_candidates import (
    TransformationReadinessReport,
    evaluate_transformation_readiness,
)

#: Schema version of :meth:`LifecycleGateReport.to_dict` (DD-100). Bump only on
#: a breaking change (removed/renamed key or changed meaning); additive new
#: keys do not require a bump.
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class DomainReleaseFact:
    """Per-domain release eligibility, derived from the canonical BindingAnalysis.

    ``evaluated`` is ``False`` when the domain has no claims registry/ontology
    authority to derive from (e.g. no ``model/claims/{domain}-claims.yaml``) — such
    a domain is vacuously release-eligible (nothing to block on).
    """

    domain: str
    evaluated: bool = False
    bound_classes: tuple[str, ...] = ()
    aspirational_classes: tuple[str, ...] = ()
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def release_eligible(self) -> bool:
        """True iff no approved, materialization-eligible claim is unbound."""
        return not self.aspirational_classes

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "evaluated": self.evaluated,
            "bound_classes": list(self.bound_classes),
            "aspirational_classes": list(self.aspirational_classes),
            "reasons": dict(self.reasons),
            "release_eligible": self.release_eligible,
        }


@dataclass(frozen=True)
class ValidationFact:
    """The persisted validation state, read from `status`'s ``validate`` phase.

    ``passed`` is ``None`` when validation has not been run yet, or when its
    persisted report has no recognizable pass/fail structure — "not objectively
    knowable", never guessed.
    """

    evaluated: bool
    passed: bool | None = None
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "evaluated": self.evaluated,
            "passed": self.passed,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ProjectionFact:
    """The persisted projection state, read from `status`'s ``project`` phase."""

    targets_generated: tuple[str, ...] = ()

    @property
    def evaluated(self) -> bool:
        return bool(self.targets_generated)

    def to_dict(self) -> dict:
        return {
            "evaluated": self.evaluated,
            "targets_generated": list(self.targets_generated),
        }


def _list_dict(mapping: dict) -> dict:
    return {key: list(value) for key, value in mapping.items()}


def _claim_report_to_dict(report: ClaimCheckReport) -> dict:
    """Explicit, JSON-safe projection of :class:`ClaimCheckReport`.

    Field names are unchanged from the dataclass so this is a lossless read —
    the same reasons ``check-claims`` prints are present here verbatim.
    """
    return {
        "missing": list(report.missing),
        "invalid": _list_dict(report.invalid),
        "incomplete": list(report.incomplete),
        "stale": list(report.stale),
        "unverifiable": list(report.unverifiable),
        "ok": list(report.ok),
        "orphan": list(report.orphan),
        "uncovered_tables": _list_dict(report.uncovered_tables),
        "unowned": list(report.unowned),
        "duplicate_approved": [
            {"uri": d.uri, "first": d.first, "second": d.second}
            for d in report.duplicate_approved
        ],
        "shared_dimensions": [
            {"uri": d.uri, "first": d.first, "second": d.second}
            for d in report.shared_dimensions
        ],
        "proposed_counts": dict(report.proposed_counts),
        "anchor_pending": _list_dict(report.anchor_pending),
        "anchor_missing": list(report.anchor_missing),
        "deviation_missing": _list_dict(report.deviation_missing),
        "ownership_conflicts": [
            {
                "domain": c.domain,
                "claim_id": c.claim_id,
                "uri": c.uri,
                "owners": list(c.owners),
            }
            for c in report.ownership_conflicts
        ],
        "passthrough_review": _list_dict(report.passthrough_review),
        "column_omissions": _list_dict(report.column_omissions),
        "grain_conflicts": _list_dict(report.grain_conflicts),
        "is_blocking": report.is_blocking,
        "has_warnings": report.has_warnings,
        "total_proposed": report.total_proposed,
    }


def _source_coverage_to_dict(report: SourceCoverageReport) -> dict:
    """Explicit, JSON-safe projection of :class:`SourceCoverageReport`."""
    return {
        "uncovered": _list_dict(report.uncovered),
        "domain_counts": {k: list(v) for k, v in report.domain_counts.items()},
        "unresolved_domains": list(report.unresolved_domains),
        "direct_counts": dict(report.direct_counts),
        "replacement_counts": dict(report.replacement_counts),
        "diagnostics": _list_dict(report.diagnostics),
        "is_blocking": report.is_blocking,
        "total_uncovered": report.total_uncovered,
    }


def _projection_sync_to_dict(report: ProjectionSyncReport) -> dict:
    """Explicit, JSON-safe projection of :class:`ProjectionSyncReport`."""
    return {
        "domains": [
            {
                "domain": d.domain,
                "in_sync": d.in_sync,
                "missing_imports": list(d.missing_imports),
                "extra_imports": list(d.extra_imports),
                "missing_includes": list(d.missing_includes),
                "extra_includes": list(d.extra_includes),
                "has_bulk_include_imports": d.has_bulk_include_imports,
                "error": d.error,
            }
            for d in report.domains
        ],
        "is_blocking": report.is_blocking,
    }


@dataclass
class LifecycleGateReport:
    """One deterministic, machine-readable release-readiness report.

    ``is_blocking`` is the union (``OR``) of every composed section's own
    blocking semantics — it never introduces a new rule, only aggregates
    existing ones so a CI caller has a single exit-code decision while a human
    caller can still drill into ``claims``/``source_coverage``/
    ``projection_sync``/``release``/``validation`` for the original reasons.
    """

    schema_version: int
    hub_root: str
    claims: ClaimCheckReport
    source_coverage: SourceCoverageReport | None
    projection_sync: ProjectionSyncReport
    transformation_candidates: TransformationReadinessReport
    release: tuple[DomainReleaseFact, ...]
    validation: ValidationFact
    project: ProjectionFact

    @property
    def release_blocking_domains(self) -> tuple[str, ...]:
        """Domains with at least one approved, unbound, materialization-eligible claim."""
        return tuple(sorted(r.domain for r in self.release if not r.release_eligible))

    @property
    def is_blocking(self) -> bool:
        return (
            self.claims.is_blocking
            or bool(self.source_coverage is not None and self.source_coverage.is_blocking)
            or self.projection_sync.is_blocking
            or self.transformation_candidates.is_blocking
            or bool(self.release_blocking_domains)
            or self.validation.passed is False
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "hub_root": self.hub_root,
            "is_blocking": self.is_blocking,
            "release_blocking_domains": list(self.release_blocking_domains),
            "claims": _claim_report_to_dict(self.claims),
            "source_coverage": (
                _source_coverage_to_dict(self.source_coverage)
                if self.source_coverage is not None
                else None
            ),
            "projection_sync": _projection_sync_to_dict(self.projection_sync),
            "transformation_candidates": self.transformation_candidates.to_dict(),
            "release": [r.to_dict() for r in self.release],
            "validation": self.validation.to_dict(),
            "project": self.project.to_dict(),
        }


def _compute_release_facts(
    hub_root: Path,
    claims_dir: Path,
    domains_filter: list[str] | None,
) -> tuple[DomainReleaseFact, ...]:
    """Per-domain release eligibility from the canonical BindingAnalysis (DD-096).

    Discovers domains the same way ``claims-to-silver-ext``/``status`` do — every
    ``model/claims/{domain}-claims.yaml`` file — then classifies each through
    :func:`binding_analysis.analyze_domain_from_hub`, the single authority also
    used by the ``status`` scan. Never re-derives bound/aspirational rules.
    """
    if not claims_dir.is_dir():
        return ()

    lowers = [d.lower() for d in domains_filter] if domains_filter else None

    def in_scope(name: str) -> bool:
        if lowers is None:
            return True
        return any(token in name.lower() for token in lowers)

    facts: list[DomainReleaseFact] = []
    for claims_file in sorted(claims_dir.glob("*-claims.yaml")):
        domain = claims_file.name.removesuffix("-claims.yaml")
        if not in_scope(domain):
            continue
        snapshot = analyze_domain_from_hub(hub_root, domain)
        if snapshot is None:
            facts.append(DomainReleaseFact(domain=domain, evaluated=False))
            continue
        aspirational = tuple(snapshot.aspirational_names())
        reasons = {
            name: snapshot.analysis.reason(uri)
            for uri, name in snapshot.classes_by_uri.items()
            if snapshot.analysis.is_aspirational(uri)
        }
        facts.append(
            DomainReleaseFact(
                domain=domain,
                evaluated=True,
                bound_classes=tuple(snapshot.bound_names()),
                aspirational_classes=aspirational,
                reasons=reasons,
            )
        )
    return tuple(facts)


def _validation_fact(status: HubStatus) -> ValidationFact:
    """Read the ``validate`` phase's ``data_valid`` fact — never re-runs validation."""
    phase = status.phase("validate")
    if phase is None or not phase.instances:
        return ValidationFact(evaluated=False, passed=None)
    inst = phase.instances[0]
    passed = inst.facts.get("data_valid") if inst.facts else None
    return ValidationFact(evaluated=True, passed=passed, evidence=tuple(inst.evidence))


def _project_fact(status: HubStatus) -> ProjectionFact:
    """Read the ``project`` phase's generated targets — never re-runs projection."""
    phase = status.phase("project")
    if phase is None:
        return ProjectionFact()
    return ProjectionFact(targets_generated=tuple(i.name for i in phase.instances))


def evaluate_lifecycle_gate(
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
    toolkit_version: str = "",
) -> LifecycleGateReport:
    """Compose the deterministic lifecycle gate over one hub's committed artifacts.

    Builds :class:`completeness_model.CompletenessFacts` once and passes it to
    both the claim and source-coverage evaluators (mirrors ``check-claims``'
    own composition, so the two never see divergent facts), evaluates extension
    sync, derives per-domain release eligibility, then reads validation and
    projection facts from :func:`status.scan_hub_status`. Never re-runs
    validation or a projection; never approves a claim; never persists an
    ``aspirational``/release-eligible flag.
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

    claim_report = check_claims_coverage(
        claims_dir=claims_dir,
        analysis_dir=analysis_dir,
        data_domains=data_domains,
        domains_filter=domains_filter,
        check_mdm_anchor=check_mdm_anchor,
        check_ownership=check_ownership,
        facts=facts,
    )

    source_report: SourceCoverageReport | None = None
    if not no_source_coverage:
        source_report = check_source_coverage(
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

    release = _compute_release_facts(hub_root, claims_dir, domains_filter)

    status = scan_hub_status(hub_root, toolkit_version=toolkit_version)
    transformation_candidates = evaluate_transformation_readiness(
        hub_root,
        stage="release",
    )

    return LifecycleGateReport(
        schema_version=SCHEMA_VERSION,
        hub_root=str(hub_root),
        claims=claim_report,
        source_coverage=source_report,
        projection_sync=sync_report,
        transformation_candidates=transformation_candidates,
        release=release,
        validation=_validation_fact(status),
        project=_project_fact(status),
    )
