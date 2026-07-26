# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Claim Registry schema v1 — model, loader, and structural validator.

The Claim Registry (``model/claims/{domain}-claims.yaml``) is the single governed
source of truth for *which concepts are approved to materialize* in a hub, with
evidence, ownership, dispositions, and silver-contract impact. It replaces the
former ``{domain}-alignment.yaml`` (DD-094).

This module is deterministic and AI-free: it defines the dataclass model for
schema v1, a tolerant YAML loader, a structural validator, and round-trip
``*_to_dict`` / ``*_from_dict`` helpers used by the one-way migration (golden
tests rely on byte-stable output).

Governance vocabulary (DD-094 / schema doc §2):

* ``status``      proposed | approved | rejected | deferred | deprecated
* ``disposition`` claim | specialize | passthrough | skip | gap
* ``type``        class | property | relationship | reference_data | measure
* ``origin``      imported | authored   (``DD-EL-3`` Finding-3 local-class rule)
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: Current Claim Registry schema version.
CLAIM_REGISTRY_SCHEMA_VERSION = 1

VALID_STATUSES = ("proposed", "approved", "rejected", "deferred", "deprecated")
VALID_DISPOSITIONS = ("claim", "specialize", "passthrough", "skip", "gap")
VALID_TYPES = ("class", "property", "relationship", "reference_data", "measure")
VALID_ORIGINS = ("imported", "authored")
#: ``confirmed`` (uri-anchor-contract) — the table's class was resolved from
#: confirmed discovery evidence (an explicit URI), overriding any name-similarity
#: guess. ``unresolved`` — multiple confirmed anchors were plausible and the
#: table was deliberately left un-anchored (see ``unresolved_anchors.py``)
#: rather than silently picking the nearest class; no property claims are
#: generated for it until the anchor resolves.
VALID_ANCHOR_STATES = (
    "matched", "fallback", "rejected", "unmatched", "confirmed", "unresolved",
)
#: The one anchor state that means "this table deliberately emitted no claims and
#: no covered columns". Named so consumers (e.g. the ``check-claims`` coverage
#: gate) can tell a *deliberate* empty coverage record apart from columns that
#: were dropped on the way to the registry.
ANCHOR_STATE_UNRESOLVED = "unresolved"
VALID_CHANGE_TYPES = ("additive", "breaking")

#: Alignment-reliability — schema version for the additive
#: ``ClaimRegistry.generation_outcomes`` records (independent of
#: ``CLAIM_REGISTRY_SCHEMA_VERSION`` since it tracks its own, narrower shape).
GENERATION_OUTCOME_SCHEMA_VERSION = 1
VALID_GENERATION_OUTCOMES = ("semantic_success", "provider_failure", "fallback_only")

#: proposal-quality — schema version for the additive
#: ``ClaimRegistry.domain_handoffs`` records (independent of
#: ``CLAIM_REGISTRY_SCHEMA_VERSION`` since it tracks its own, narrower shape).
DOMAIN_HANDOFF_SCHEMA_VERSION = 1

#: Allowed ``status`` transitions (schema doc §2.4). ``rejected`` and
#: ``deprecated`` are terminal — re-opening requires a new claim id.
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"approved", "rejected", "deferred"}),
    "approved": frozenset({"deprecated"}),
    "deferred": frozenset({"proposed", "approved"}),
    "rejected": frozenset(),
    "deprecated": frozenset(),
}

#: Custom-column triage values (former ``CUSTOM_DISPOSITIONS``) → schema v1
#: dispositions (migration map, schema doc §3.2).
TRIAGE_TO_DISPOSITION: dict[str, str] = {
    "model": "specialize",
    "silver-passthrough": "passthrough",
    "skip": "skip",
}


def is_valid_transition(current: str, target: str) -> bool:
    """Return True if ``current`` → ``target`` is an allowed status transition."""
    return target in STATUS_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class EvidenceSource:
    """A typed, table/column-granular evidence reference for a claim."""

    type: str
    system: str | None = None
    table: str | None = None
    column: str | None = None
    model: str | None = None  # powerbi model
    measure: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        for key in ("system", "table", "column", "model", "measure", "note"):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceSource:
        return cls(
            type=data.get("type", ""),
            system=data.get("system"),
            table=data.get("table"),
            column=data.get("column"),
            model=data.get("model"),
            measure=data.get("measure"),
            note=data.get("note"),
        )


@dataclass
class ReferenceData:
    """MDM / reference-data descriptor for a ``reference_data`` claim (§5.3).

    Captures the authoritative source, code system, natural key, and SCD strategy
    of a conformed dimension / code list / crosswalk so the MDM-anchor gate has a
    concrete, reviewable record rather than a bare class claim.
    """

    authority_system: str | None = None
    code_system: str | None = None
    key: str | None = None
    scd_type: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for attr in ("authority_system", "code_system", "key", "scd_type"):
            val = getattr(self, attr)
            if val is not None:
                out[attr] = val
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReferenceData:
        scd = data.get("scd_type")
        return cls(
            authority_system=data.get("authority_system"),
            code_system=data.get("code_system"),
            key=data.get("key"),
            scd_type=int(scd) if scd is not None else None,
        )


@dataclass
class Deviation:
    """Recorded deviation / upstream-gap decision for a client-native claim (§12).

    Every ``gap`` (client-native) claim must, on approval, carry a deviation record
    so client-native concepts are tracked and the upstream accelerator gap process
    is visible (the ``deviation-log`` check).
    """

    reason: str | None = None
    owner: str | None = None
    gap_request: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for attr in ("reason", "owner", "gap_request"):
            val = getattr(self, attr)
            if val is not None:
                out[attr] = val
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Deviation:
        return cls(
            reason=data.get("reason"),
            owner=data.get("owner"),
            gap_request=data.get("gap_request"),
        )


@dataclass
class OwnershipOverride:
    """Documented exception allowing a claim to cross a ``data-domains.yaml``
    ownership boundary or to share a class as a conformed dimension (§14).

    The override turns an otherwise-blocking ownership conflict / duplicate
    ``approved`` claim into an explicit, reviewed decision — it must name an
    ``owner`` and a ``rationale``.
    """

    owner: str | None = None
    rationale: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.owner is not None:
            out["owner"] = self.owner
        if self.rationale is not None:
            out["rationale"] = self.rationale
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OwnershipOverride:
        return cls(owner=data.get("owner"), rationale=data.get("rationale"))


@dataclass
class SilverImpact:
    """Declared silver-contract impact of a claim."""

    table: str | None = None
    column: str | None = None
    change_type: str = "additive"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.table is not None:
            out["table"] = self.table
        if self.column is not None:
            out["column"] = self.column
        out["change_type"] = self.change_type
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SilverImpact:
        return cls(
            table=data.get("table"),
            column=data.get("column"),
            change_type=data.get("change_type", "additive"),
        )


@dataclass
class Claim:
    """A single governed claim entry."""

    id: str
    type: str
    status: str = "proposed"
    disposition: str = "claim"
    origin: str = "imported"
    class_uri: str | None = None
    property_uri: str | None = None
    owner: str | None = None
    evidence_sources: list[EvidenceSource] = field(default_factory=list)
    silver_impact: SilverImpact | None = None
    reference_data: ReferenceData | None = None
    mdm_anchor: bool = False
    deviation: Deviation | None = None
    ownership_override: OwnershipOverride | None = None
    passthrough_reviewed: bool = False
    rationale: str | None = None
    proposed_confidence: float | None = None
    superseded_by: str | None = None

    def identifying_uri(self) -> str | None:
        return self.class_uri or self.property_uri

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "type": self.type}
        if self.class_uri is not None:
            out["class_uri"] = self.class_uri
        if self.property_uri is not None:
            out["property_uri"] = self.property_uri
        out["origin"] = self.origin
        out["status"] = self.status
        out["disposition"] = self.disposition
        if self.owner is not None:
            out["owner"] = self.owner
        if self.evidence_sources:
            out["evidence_sources"] = [e.to_dict() for e in self.evidence_sources]
        if self.silver_impact is not None:
            out["silver_impact"] = self.silver_impact.to_dict()
        if self.reference_data is not None:
            ref = self.reference_data.to_dict()
            if ref:
                out["reference_data"] = ref
        if self.mdm_anchor:
            out["mdm_anchor"] = True
        if self.deviation is not None:
            dev = self.deviation.to_dict()
            if dev:
                out["deviation"] = dev
        if self.ownership_override is not None:
            ovr = self.ownership_override.to_dict()
            if ovr:
                out["ownership_override"] = ovr
        if self.passthrough_reviewed:
            out["passthrough_reviewed"] = True
        if self.rationale is not None:
            out["rationale"] = self.rationale
        if self.proposed_confidence is not None:
            out["proposed_confidence"] = self.proposed_confidence
        if self.superseded_by is not None:
            out["superseded_by"] = self.superseded_by
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Claim:
        return cls(
            id=str(data.get("id", "")),
            type=data.get("type", ""),
            status=data.get("status", "proposed"),
            disposition=data.get("disposition", "claim"),
            origin=data.get("origin", "imported"),
            class_uri=data.get("class_uri"),
            property_uri=data.get("property_uri"),
            owner=data.get("owner"),
            evidence_sources=[
                EvidenceSource.from_dict(e) for e in data.get("evidence_sources", [])
            ],
            silver_impact=(
                SilverImpact.from_dict(data["silver_impact"])
                if data.get("silver_impact")
                else None
            ),
            reference_data=(
                ReferenceData.from_dict(data["reference_data"])
                if data.get("reference_data")
                else None
            ),
            mdm_anchor=bool(data.get("mdm_anchor", False)),
            deviation=(
                Deviation.from_dict(data["deviation"]) if data.get("deviation") else None
            ),
            ownership_override=(
                OwnershipOverride.from_dict(data["ownership_override"])
                if data.get("ownership_override")
                else None
            ),
            passthrough_reviewed=bool(data.get("passthrough_reviewed", False)),
            rationale=data.get("rationale"),
            proposed_confidence=data.get("proposed_confidence"),
            superseded_by=data.get("superseded_by"),
        )


@dataclass
class CoverageTable:
    """Per-table registry snapshot consumed by canonical completeness facts."""

    table: str
    total_columns: int = 0
    mapped_columns: int = 0
    custom_columns: int = 0
    anchor_state: str = "unmatched"
    ref_class: str | None = None
    #: F6 (toolkit-optimizations) — the true source-vocabulary column count and a
    #: deterministic digest of the sorted column names, persisted independently of
    #: any prompt truncation so ``check-claims`` can detect columns dropped before
    #: they reached the registry. ``0`` / ``None`` mean "not recorded" (pre-F6).
    source_column_count: int = 0
    source_column_sha256: str | None = None
    #: uri-anchor-contract — the canonical inventory URI a confirmed discovery
    #: alias (or explicit rename) resolved *this* table's class to, persisted
    #: alongside the display-only ``ref_class`` name. ``None`` when the anchor
    #: was not resolved from confirmed evidence (pre-feature registries, or a
    #: table anchored purely by the model/lexical-similarity path).
    likely_entity_uri: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "table": self.table,
            "total_columns": self.total_columns,
            "mapped_columns": self.mapped_columns,
            "custom_columns": self.custom_columns,
            "anchor_state": self.anchor_state,
        }
        if self.ref_class is not None:
            out["ref_class"] = self.ref_class
        # F6: emit only when recorded so pre-F6 registries stay byte-identical.
        if self.source_column_count:
            out["source_column_count"] = self.source_column_count
        if self.source_column_sha256:
            out["source_column_sha256"] = self.source_column_sha256
        # uri-anchor-contract: emit only when resolved (pre-feature registries
        # stay byte-identical).
        if self.likely_entity_uri:
            out["likely_entity_uri"] = self.likely_entity_uri
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoverageTable:
        return cls(
            table=data.get("table", ""),
            total_columns=int(data.get("total_columns", 0)),
            mapped_columns=int(data.get("mapped_columns", 0)),
            custom_columns=int(data.get("custom_columns", 0)),
            anchor_state=data.get("anchor_state", "unmatched"),
            ref_class=data.get("ref_class"),
            source_column_count=int(data.get("source_column_count", 0)),
            source_column_sha256=data.get("source_column_sha256"),
            likely_entity_uri=data.get("likely_entity_uri"),
        )


@dataclass
class CoverageSystem:
    """Per-source-system coverage grouping."""

    system: str
    tables: list[CoverageTable] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"system": self.system, "tables": [t.to_dict() for t in self.tables]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoverageSystem:
        return cls(
            system=data.get("system", ""),
            tables=[CoverageTable.from_dict(t) for t in data.get("tables", [])],
        )


@dataclass
class Freshness:
    """Freshness digests enabling deterministic staleness detection."""

    affinity_sha256: str | None = None
    alignment_params_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.affinity_sha256 is not None:
            out["affinity_sha256"] = self.affinity_sha256
        if self.alignment_params_sha256 is not None:
            out["alignment_params_sha256"] = self.alignment_params_sha256
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Freshness:
        return cls(
            affinity_sha256=data.get("affinity_sha256"),
            alignment_params_sha256=data.get("alignment_params_sha256"),
        )


@dataclass
class GenerationOutcome:
    """Alignment-reliability — one table's typed semantic-generation outcome.

    Additive record persisted alongside (not instead of) the structural claims:
    it says whether ``propose-alignment`` actually produced trustworthy semantic
    output for ``(system, table)``, distinct from whether the resulting claims
    are structurally valid. ``provider`` / ``model`` / ``error`` are only ever
    populated for a non-``semantic_success`` outcome and ``error`` is always a
    pre-sanitized (redacted, length-capped) message — never a raw exception.
    """

    system: str
    table: str
    outcome: str
    provider: str | None = None
    model: str | None = None
    error: str | None = None
    schema_version: int = GENERATION_OUTCOME_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "system": self.system,
            "table": self.table,
            "outcome": self.outcome,
            "schema_version": self.schema_version,
        }
        if self.provider is not None:
            out["provider"] = self.provider
        if self.model is not None:
            out["model"] = self.model
        if self.error is not None:
            out["error"] = self.error
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerationOutcome:
        return cls(
            system=data.get("system", ""),
            table=data.get("table", ""),
            outcome=data.get("outcome", ""),
            provider=data.get("provider"),
            model=data.get("model"),
            error=data.get("error"),
            schema_version=int(
                data.get("schema_version", GENERATION_OUTCOME_SCHEMA_VERSION)
            ),
        )


@dataclass
class DomainHandoff:
    """Cross-domain evidence deliberately NOT claimed in this domain's registry.

    Emitted instead of an in-domain property claim when a column's matched
    reference class/property is owned by a *different* accelerator data-domain —
    the ``owns`` / ``does_not_own`` boundary declared in ``data-domains.yaml`` and
    resolved by ``propose-alignment``'s DD-070 cross-module tagging
    (``ColumnAlignment.ref_module`` / ``belongs_to_domain(s)``). A handoff keeps
    the source evidence (never lost) and names the owning domain(s) so the
    finding can be routed to the correct registry, instead of silently
    materializing a claim this domain has no right to approve (proposal-quality;
    Booking design-session finding #7).
    """

    ref_class: str
    ref_property: str
    owning_domains: list[str] = field(default_factory=list)
    ref_module: str | None = None
    ref_module_uri: str | None = None
    evidence_sources: list[EvidenceSource] = field(default_factory=list)
    schema_version: int = DOMAIN_HANDOFF_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ref_class": self.ref_class,
            "ref_property": self.ref_property,
            "owning_domains": list(self.owning_domains),
            "schema_version": self.schema_version,
        }
        if self.ref_module:
            out["ref_module"] = self.ref_module
        if self.ref_module_uri:
            out["ref_module_uri"] = self.ref_module_uri
        if self.evidence_sources:
            out["evidence_sources"] = [e.to_dict() for e in self.evidence_sources]
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainHandoff:
        return cls(
            ref_class=data.get("ref_class", ""),
            ref_property=data.get("ref_property", ""),
            owning_domains=list(data.get("owning_domains") or []),
            ref_module=data.get("ref_module"),
            ref_module_uri=data.get("ref_module_uri"),
            evidence_sources=[
                EvidenceSource.from_dict(e)
                for e in data.get("evidence_sources", []) or []
            ],
            schema_version=int(
                data.get("schema_version", DOMAIN_HANDOFF_SCHEMA_VERSION)
            ),
        )


@dataclass
class ClaimRegistry:
    """A whole-domain Claim Registry document (schema v1)."""

    domain: str
    schema_version: int = CLAIM_REGISTRY_SCHEMA_VERSION
    generated_at: str | None = None
    algorithm_version: int | None = None
    freshness: Freshness = field(default_factory=Freshness)
    coverage: list[CoverageSystem] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    #: Issue #192 (Phase A1) — advisory, deterministic relationship candidates
    #: (e.g. clustered address columns → a ``hasAddress`` relationship). These are
    #: NOT governed claims: they carry ``requires_human_confirmation`` and are
    #: surfaced to the modeling skill's Relationship & Satellite-Entity Review gate.
    #: Emitted only when a detector fires, so default output stays unchanged.
    relationship_candidates: list[dict[str, Any]] = field(default_factory=list)
    #: F2/F7 (toolkit-optimizations) — grain-conflict records. Each entry flags a
    #: single ``ref_class`` that multiple source tables with *different* candidate
    #: business entities (``likely_entity``) collapsed into, i.e. a merge-by-nearest-
    #: anchor that may fuse distinct grains. These are blocking governance signals
    #: (surfaced by ``check-claims``): a human must confirm the tables really share a
    #: grain or split the model. Emitted only when a conflict is detected.
    grain_conflicts: list[dict[str, Any]] = field(default_factory=list)
    #: Alignment-reliability — per-table typed generation outcome records
    #: (``semantic_success`` / ``provider_failure`` / ``fallback_only``), one per
    #: ``(system, table)`` migrated from the alignment run. Additive and emitted
    #: only when non-empty, so a registry produced before this feature (or a
    #: fully-successful run) stays byte-identical. Lets ``check-claims`` warn on
    #: incomplete semantic generation without conflating it with structural
    #: validity (owned by :mod:`kairos_ontology.core.claim_coverage`).
    generation_outcomes: list[GenerationOutcome] = field(default_factory=list)
    #: proposal-quality — cross-domain evidence deliberately excluded from this
    #: registry's claims because the matched property/class is owned by a
    #: different accelerator data-domain (``owns`` / ``does_not_own`` boundary).
    #: Additive; emitted only when non-empty, so a registry produced before this
    #: feature (or a run with no cross-domain evidence) stays byte-identical.
    domain_handoffs: list[DomainHandoff] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "domain": self.domain,
        }
        if self.generated_at is not None:
            out["generated_at"] = self.generated_at
        if self.algorithm_version is not None:
            out["algorithm_version"] = self.algorithm_version
        freshness = self.freshness.to_dict()
        if freshness:
            out["freshness"] = freshness
        if self.coverage:
            out["coverage"] = {"systems": [s.to_dict() for s in self.coverage]}
        if self.relationship_candidates:
            out["relationship_candidates"] = self.relationship_candidates
        if self.grain_conflicts:
            out["grain_conflicts"] = self.grain_conflicts
        if self.generation_outcomes:
            out["generation_outcomes"] = [g.to_dict() for g in self.generation_outcomes]
        if self.domain_handoffs:
            out["domain_handoffs"] = [h.to_dict() for h in self.domain_handoffs]
        out["claims"] = [c.to_dict() for c in self.claims]
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClaimRegistry:
        cov_raw = data.get("coverage") or {}
        systems = cov_raw.get("systems", []) if isinstance(cov_raw, dict) else []
        return cls(
            domain=data.get("domain", ""),
            schema_version=int(data.get("schema_version", CLAIM_REGISTRY_SCHEMA_VERSION)),
            generated_at=data.get("generated_at"),
            algorithm_version=data.get("algorithm_version"),
            freshness=Freshness.from_dict(data.get("freshness") or {}),
            coverage=[CoverageSystem.from_dict(s) for s in systems],
            claims=[Claim.from_dict(c) for c in data.get("claims", [])],
            relationship_candidates=list(data.get("relationship_candidates") or []),
            grain_conflicts=list(data.get("grain_conflicts") or []),
            generation_outcomes=[
                GenerationOutcome.from_dict(g)
                for g in data.get("generation_outcomes") or []
            ],
            domain_handoffs=[
                DomainHandoff.from_dict(h)
                for h in data.get("domain_handoffs") or []
            ],
        )


# ---------------------------------------------------------------------------
# Loader / dumper
# ---------------------------------------------------------------------------


def registry_path(claims_dir: Path, domain: str) -> Path:
    """Return the conventional path for a domain's claims file."""
    return claims_dir / f"{domain}-claims.yaml"


def load_registry(path: Path) -> ClaimRegistry:
    """Load and parse a claims YAML file into a :class:`ClaimRegistry`."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: claims file is not a mapping")
    return ClaimRegistry.from_dict(data)


def dump_registry(registry: ClaimRegistry) -> str:
    """Serialize a registry to deterministic YAML (insertion-ordered keys)."""
    return yaml.safe_dump(
        registry.to_dict(),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


def write_registry(registry: ClaimRegistry, path: Path) -> None:
    """Write a registry to ``path`` deterministically (creating parents)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_registry(registry), encoding="utf-8")


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------


def approval_gate_errors(claim: Claim, *, target_status: str | None = None) -> list[str]:
    """Return errors that would make *claim* invalid as an approved claim.

    ``target_status`` lets curation commands pre-flight a transition before mutating
    the claim, while ``validate_registry`` uses the claim's persisted status.
    """
    status = target_status if target_status is not None else claim.status
    if status != "approved":
        return []

    errors: list[str] = []
    needs_uri = claim.disposition in ("claim", "specialize")
    if needs_uri:
        if claim.type in ("class", "reference_data") and not claim.class_uri:
            errors.append(f"approved {claim.type} claim requires 'class_uri'")
        if claim.type in ("property", "measure") and not claim.property_uri:
            errors.append(f"approved {claim.type} claim requires 'property_uri'")
        if claim.type == "relationship" and not claim.identifying_uri():
            errors.append("approved relationship claim requires a class_uri or property_uri")

    if not claim.evidence_sources:
        errors.append("approved claim has no evidence_sources")
    return errors


@dataclass
class ValidationIssue:
    """A single structural validation finding."""

    level: str  # "error" | "warning"
    message: str
    claim_id: str | None = None


def validate_registry(registry: ClaimRegistry) -> list[ValidationIssue]:
    """Structurally validate a registry. Returns issues (errors + warnings).

    This is deterministic and self-contained: it checks schema version, enum
    membership, id uniqueness, per-type identifying URIs, status/disposition
    rules, evidence presence for approved claims, ``superseded_by`` integrity and
    intra-file duplicate ``approved`` claims. Cross-file duplicate detection and
    ownership checks are the gate's responsibility (Slice 1 ``check-claims``).
    """
    issues: list[ValidationIssue] = []

    def err(msg: str, cid: str | None = None) -> None:
        issues.append(ValidationIssue("error", msg, cid))

    def warn(msg: str, cid: str | None = None) -> None:
        issues.append(ValidationIssue("warning", msg, cid))

    if registry.schema_version != CLAIM_REGISTRY_SCHEMA_VERSION:
        err(
            f"unsupported schema_version {registry.schema_version!r} "
            f"(expected {CLAIM_REGISTRY_SCHEMA_VERSION})"
        )
    if not registry.domain:
        err("registry has no 'domain'")

    seen_ids: set[str] = set()
    approved_uris: dict[str, str] = {}  # identifying_uri -> first claim id
    known_ids = {c.id for c in registry.claims if c.id}

    for claim in registry.claims:
        cid = claim.id or "<missing-id>"
        if not claim.id:
            err("claim is missing 'id'", cid)
        elif claim.id in seen_ids:
            err(f"duplicate claim id {claim.id!r}", cid)
        else:
            seen_ids.add(claim.id)

        if claim.type not in VALID_TYPES:
            err(f"invalid type {claim.type!r} (allowed: {', '.join(VALID_TYPES)})", cid)
        if claim.status not in VALID_STATUSES:
            err(f"invalid status {claim.status!r}", cid)
        if claim.disposition not in VALID_DISPOSITIONS:
            err(f"invalid disposition {claim.disposition!r}", cid)
        if claim.origin not in VALID_ORIGINS:
            err(f"invalid origin {claim.origin!r}", cid)

        # Approval gates are not proposal-time structural requirements: candidates
        # may lack resolved URIs/evidence until a curator approves them.
        for message in approval_gate_errors(claim):
            err(message, cid)

        if claim.silver_impact and claim.silver_impact.change_type not in VALID_CHANGE_TYPES:
            err(
                f"invalid silver_impact.change_type "
                f"{claim.silver_impact.change_type!r}",
                cid,
            )

        for ev in claim.evidence_sources:
            if not ev.type:
                err("evidence_source is missing 'type'", cid)

        # reference_data block belongs only on reference_data claims (Slice 4 §5.3)
        if claim.reference_data is not None and claim.type != "reference_data":
            warn("reference_data block set on a non-reference_data claim", cid)
        # mdm_anchor marks a required reference-data anchor; only meaningful there
        if claim.mdm_anchor and claim.type != "reference_data":
            warn("mdm_anchor set on a non-reference_data claim", cid)

        # ownership_override must name an owner *and* a rationale (Slice 4 §14)
        ovr = claim.ownership_override
        if ovr is not None and (not ovr.owner or not ovr.rationale):
            err("ownership_override requires both 'owner' and 'rationale'", cid)

        # superseded_by only meaningful when deprecated, and must resolve
        if claim.superseded_by is not None:
            if claim.status != "deprecated":
                warn("superseded_by set on a non-deprecated claim", cid)
            if claim.superseded_by not in known_ids:
                err(f"superseded_by {claim.superseded_by!r} is not a known claim id", cid)

        # intra-file duplicate approved identifying URI
        uri = claim.identifying_uri()
        if claim.status == "approved" and uri:
            if uri in approved_uris:
                err(
                    f"duplicate approved claim for {uri} "
                    f"(also {approved_uris[uri]})",
                    cid,
                )
            else:
                approved_uris[uri] = claim.id

    # coverage anchor-state enum
    for syscov in registry.coverage:
        for tbl in syscov.tables:
            if tbl.anchor_state not in VALID_ANCHOR_STATES:
                err(
                    f"coverage {syscov.system}.{tbl.table}: invalid anchor_state "
                    f"{tbl.anchor_state!r}"
                )

    # Alignment-reliability — generation-outcome enum (additive, warn-level only:
    # an unrecognized outcome value is a forward-compat concern, not a
    # structural-validity blocker owned by this validator).
    for gen in registry.generation_outcomes:
        if gen.outcome not in VALID_GENERATION_OUTCOMES:
            warn(
                f"generation_outcomes {gen.system}.{gen.table}: unknown outcome "
                f"{gen.outcome!r}"
            )

    # proposal-quality — a handoff naming this registry's own domain as an
    # "owning" domain contradicts its own reason for existing (it should have
    # been an in-domain claim). Warning-level only: additive, non-blocking
    # diagnostic, never a hard structural error.
    for handoff in registry.domain_handoffs:
        if registry.domain and registry.domain in handoff.owning_domains:
            warn(
                f"domain_handoffs: handoff for {handoff.ref_class}."
                f"{handoff.ref_property} names this registry's own domain "
                f"{registry.domain!r} as an owner"
            )

    # uri-anchor-contract — an imported claim/specialize record without a
    # resolvable identifying URI is flagged so a table that was never really
    # anchored to a reference-model concept never silently looks equivalent to
    # a properly-anchored one. Warning-level only, never a hard structural
    # error: a 'proposed' claim may legitimately await human URI curation
    # (DD-094), and a registry written before this diagnostic existed must load
    # exactly as it did before (backward-compatible loading/migration
    # diagnostics).
    for claim in registry.claims:
        if claim.origin != "imported" or claim.disposition not in ("claim", "specialize"):
            continue
        cid = claim.id or "<missing-id>"
        if claim.type in ("class", "reference_data") and not claim.class_uri:
            warn(
                f"imported {claim.disposition} claim has no resolvable class_uri "
                "(uri-anchor-contract)",
                cid,
            )
        elif claim.type in ("property", "measure") and not claim.property_uri:
            warn(
                f"imported {claim.disposition} claim has no resolvable property_uri "
                "(uri-anchor-contract)",
                cid,
            )

    return issues


def validation_errors(issues: Iterable[ValidationIssue]) -> list[ValidationIssue]:
    """Filter to error-level issues."""
    return [i for i in issues if i.level == "error"]


# ---------------------------------------------------------------------------
# Re-run merge (preserve human decisions)
# ---------------------------------------------------------------------------

#: Fields curated by a human reviewer that must survive a re-run of the
#: producing command (the claim-level analog of disposition preservation).
HUMAN_CURATED_FIELDS = (
    "type",
    "status",
    "disposition",
    "origin",
    "owner",
    "silver_impact",
    "reference_data",
    "mdm_anchor",
    "deviation",
    "ownership_override",
    "passthrough_reviewed",
    "class_uri",
    "property_uri",
    "rationale",
    "superseded_by",
)


def _merge_decided_claim(candidate: Claim, previous: Claim) -> Claim:
    """Refresh generated values while preserving the declared governance policy."""
    curated_values = {
        field_name: getattr(previous, field_name) for field_name in HUMAN_CURATED_FIELDS
    }
    evidence_sources = (
        list(candidate.evidence_sources)
        if candidate.evidence_sources
        else list(previous.evidence_sources)
    )
    return replace(candidate, **curated_values, evidence_sources=evidence_sources)


#: proposal-quality — relationship-candidate keys owned by the detector; always
#: refreshed from the new run so a re-run *reports membership changes* (columns
#: added/removed from a cluster). Any additional key present only on an existing
#: cluster (e.g. a human-curated annotation) is not in this set and therefore
#: survives the merge untouched.
_RELATIONSHIP_CANDIDATE_DETECTOR_KEYS = frozenset({
    "type", "source_table", "role", "suggested_relationship", "target_concept",
    "source_columns", "address_parts", "requires_human_confirmation",
    "rationale", "cardinality", "target_class_uri", "target_resolved",
    "cluster_id",
})


def _merge_relationship_candidates(
    new_candidates: list[dict[str, Any]],
    existing_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge freshly-detected relationship clusters over existing ones.

    Keyed on the stable, content-addressed ``cluster_id`` (source table +
    semantic role/prefix + target class + cardinality — never the current column
    membership; see ``propose_alignment._relationship_cluster_id``), so:

    * detector-owned fields (contributing columns, rationale, cardinality, ...)
      always refresh from the new run — a re-run reports cluster *membership*
      changes instead of silently keeping stale evidence;
    * any additional key a human curator added directly to an existing cluster
      (anything outside the detector's own field set) is preserved across the
      refresh — a decision is never replaced just because the alignment ran
      again;
    * a candidate with no ``cluster_id`` (pre-feature output) passes through
      unmerged, so older registries stay compatible.
    """
    existing_by_id = {
        c.get("cluster_id"): c
        for c in existing_candidates
        if isinstance(c, dict) and c.get("cluster_id")
    }
    merged: list[dict[str, Any]] = []
    for cand in new_candidates:
        cluster_id = cand.get("cluster_id") if isinstance(cand, dict) else None
        prev = existing_by_id.get(cluster_id) if cluster_id else None
        if prev is not None:
            curated = {
                k: v for k, v in prev.items()
                if k not in _RELATIONSHIP_CANDIDATE_DETECTOR_KEYS
            }
            merged.append({**cand, **curated})
        else:
            merged.append(cand)
    return merged


def merge_preserving_decisions(
    new: ClaimRegistry, existing: ClaimRegistry
) -> ClaimRegistry:
    """Merge a freshly-generated registry over an existing one, never clobbering
    a human decision (DD-094; schema doc §2.4 id stability).

    Rules (keyed on stable claim ``id``):

    * registries for different domains are rejected before any decisions can leak
      across domain boundaries;
    * existing claim is still ``proposed`` → the new candidate replaces it
      (regeneration refreshes an undecided candidate);
    * existing claim is **decided** (``approved`` / ``rejected`` / ``deferred`` /
      ``deprecated``) → its curated fields are preserved, but its
      ``evidence_sources`` are refreshed from the new run (so evidence stays
      current; if the new run has none, the prior evidence is kept);
    * an existing **decided** claim that no longer appears in the new run is
      retained (a human decision is never silently dropped);
    * an existing ``proposed`` claim absent from the new run is dropped (a stale
      candidate);
    * coverage / freshness / generated_at / algorithm_version always come from the
      new run.

    ``generation_outcomes`` follows the same "always from the new run" rule as
    coverage/freshness — it is per-run reliability metadata, not a decision that
    could ever need preserving across a merge. ``domain_handoffs`` follows the
    same rule (proposal-quality) — it is derived cross-domain evidence, not a
    curated decision.

    ``relationship_candidates`` are merged by their stable ``cluster_id`` (see
    :func:`_merge_relationship_candidates`): detector-owned fields (membership,
    rationale, cardinality) always refresh, while any human-added key on an
    existing cluster survives the refresh.

    The result is sorted by ``id`` for byte-stable output.
    """
    if new.domain != existing.domain:
        raise ValueError(
            "cannot merge claim registries for different domains: "
            f"{new.domain!r} != {existing.domain!r}"
        )

    existing_by_id = {c.id: c for c in existing.claims if c.id}
    new_ids = {c.id for c in new.claims if c.id}
    merged: list[Claim] = []

    for cand in new.claims:
        prev = existing_by_id.get(cand.id)
        if prev is not None and prev.status != "proposed":
            merged.append(_merge_decided_claim(cand, prev))
        else:
            merged.append(cand)

    # retain decided claims that vanished from the new run
    for prev in existing.claims:
        if prev.id and prev.id not in new_ids and prev.status != "proposed":
            merged.append(prev)

    merged.sort(key=lambda c: c.id)

    return ClaimRegistry(
        domain=new.domain,
        schema_version=new.schema_version,
        generated_at=new.generated_at,
        algorithm_version=new.algorithm_version,
        freshness=new.freshness,
        coverage=new.coverage,
        claims=merged,
        relationship_candidates=_merge_relationship_candidates(
            new.relationship_candidates, existing.relationship_candidates
        ),
        grain_conflicts=new.grain_conflicts,
        generation_outcomes=new.generation_outcomes,
        domain_handoffs=new.domain_handoffs,
    )
