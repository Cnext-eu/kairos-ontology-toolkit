# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Claim Registry schema v1 — model, loader, and structural validator.

The Claim Registry (``model/claims/{domain}-claims.yaml``) is the single governed
source of truth for *which concepts are approved to materialize* in a hub, with
evidence, ownership, dispositions, and silver-contract impact. It replaces the
former ``{domain}-alignment.yaml`` (see the evidence-led decision log
``DD-EL-1``).

This module is deterministic and AI-free: it defines the dataclass model for
schema v1, a tolerant YAML loader, a structural validator, and round-trip
``*_to_dict`` / ``*_from_dict`` helpers used by the one-way migration (golden
tests rely on byte-stable output).

Governance vocabulary (decision log ``DD-EL-1`` / schema doc §2):

* ``status``      proposed | approved | rejected | deferred | deprecated
* ``disposition`` claim | specialize | passthrough | skip | gap
* ``type``        class | property | relationship | reference_data | measure
* ``origin``      imported | authored   (``DD-EL-3`` Finding-3 local-class rule)
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
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
VALID_ANCHOR_STATES = ("matched", "fallback", "rejected", "unmatched")
VALID_CHANGE_TYPES = ("additive", "breaking")

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
            rationale=data.get("rationale"),
            proposed_confidence=data.get("proposed_confidence"),
            superseded_by=data.get("superseded_by"),
        )


@dataclass
class CoverageTable:
    """Per-table coverage snapshot (parity with the alignment coverage gate)."""

    table: str
    total_columns: int = 0
    mapped_columns: int = 0
    custom_columns: int = 0
    anchor_state: str = "unmatched"
    ref_class: str | None = None

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
class ClaimRegistry:
    """A whole-domain Claim Registry document (schema v1)."""

    domain: str
    schema_version: int = CLAIM_REGISTRY_SCHEMA_VERSION
    generated_at: str | None = None
    algorithm_version: int | None = None
    freshness: Freshness = field(default_factory=Freshness)
    coverage: list[CoverageSystem] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)

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

        # Identifying URI is an *approval* gate, not a structural one: at proposal
        # time a candidate may not yet have a resolved URI (migrated from alignment
        # output, or a not-yet-authored specialization). Only approved materializing
        # claims (claim/specialize) must carry a resolvable URI (methodology §8.5).
        needs_uri = claim.disposition in ("claim", "specialize")
        if claim.status == "approved" and needs_uri:
            if claim.type in ("class", "reference_data") and not claim.class_uri:
                err(f"approved {claim.type} claim requires 'class_uri'", cid)
            if claim.type in ("property", "measure") and not claim.property_uri:
                err(f"approved {claim.type} claim requires 'property_uri'", cid)
            if claim.type == "relationship" and not claim.identifying_uri():
                err("approved relationship claim requires a class_uri or property_uri", cid)

        if claim.silver_impact and claim.silver_impact.change_type not in VALID_CHANGE_TYPES:
            err(
                f"invalid silver_impact.change_type "
                f"{claim.silver_impact.change_type!r}",
                cid,
            )

        for ev in claim.evidence_sources:
            if not ev.type:
                err("evidence_source is missing 'type'", cid)

        # approved claims must carry evidence (proposed/deferred may not yet)
        if claim.status == "approved" and not claim.evidence_sources:
            err("approved claim has no evidence_sources", cid)

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
    "status",
    "disposition",
    "origin",
    "owner",
    "silver_impact",
    "class_uri",
    "property_uri",
    "rationale",
    "superseded_by",
)


def merge_preserving_decisions(
    new: ClaimRegistry, existing: ClaimRegistry
) -> ClaimRegistry:
    """Merge a freshly-generated registry over an existing one, never clobbering
    a human decision (decision log ``DD-EL-1``; schema doc §2.4 id stability).

    Rules (keyed on stable claim ``id``):

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

    The result is sorted by ``id`` for byte-stable output.
    """
    existing_by_id = {c.id: c for c in existing.claims if c.id}
    new_ids = {c.id for c in new.claims if c.id}
    merged: list[Claim] = []

    for cand in new.claims:
        prev = existing_by_id.get(cand.id)
        if prev is not None and prev.status != "proposed":
            kept = Claim(
                id=prev.id,
                type=prev.type,
                status=prev.status,
                disposition=prev.disposition,
                origin=prev.origin,
                class_uri=prev.class_uri,
                property_uri=prev.property_uri,
                owner=prev.owner,
                evidence_sources=(
                    list(cand.evidence_sources)
                    if cand.evidence_sources
                    else list(prev.evidence_sources)
                ),
                silver_impact=prev.silver_impact,
                rationale=prev.rationale,
                proposed_confidence=cand.proposed_confidence,
                superseded_by=prev.superseded_by,
            )
            merged.append(kept)
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
    )
