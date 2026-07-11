# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic Claim Registry coverage gate (``check-claims``).

Single governance gate that replaces both former alignment-era gates
(``check-alignment`` + ``check-source-coverage``) now that the Claim Registry is
the one source of truth (decision log ``DD-EL-1``). It is deterministic and
AI-free — every input is committed, structured YAML/TTL:

* the Claim Registry (``model/claims/{domain}-claims.yaml``) — schema validity,
  per-table coverage snapshot, freshness digest, ownership, claim status;
* the affinity reports (``_analysis/*-affinity.yaml``) — the ``(system, table)``
  set each domain must cover, and the freshness baseline;
* the source vocabularies + mapping files — pre-silver mapping coverage (reused
  verbatim from :mod:`source_coverage`).

The gate buckets each affinity domain with priority
``missing > invalid > incomplete > stale > unverifiable > ok`` (parity with the
retired alignment gate), and additionally surfaces cross-file duplicate
``approved`` claims, ownership gaps vs ``data-domains.yaml``, and — under
``--strict`` — registries that still carry undecided (``proposed``) claims.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .alignment_coverage import (
    ALIGNMENT_ALGORITHM_VERSION,
    compute_affinity_hash,
    load_affinity_domain_tables,
)
from .claim_registry import (
    Claim,
    ClaimRegistry,
    load_registry,
    registry_path,
    validate_registry,
    validation_errors,
)

logger = logging.getLogger(__name__)


def _registry_covered_tables(registry: ClaimRegistry) -> set[tuple[str, str]]:
    """Return the ``(system, table)`` set present in a registry's coverage."""
    covered: set[tuple[str, str]] = set()
    for syscov in registry.coverage:
        for tbl in syscov.tables:
            if syscov.system and tbl.table:
                covered.add((syscov.system, tbl.table))
    return covered


#: Statuses that count an MDM anchor as *known / decided* (methodology §5.4 —
#: anchors must be known, not necessarily fully implemented). A still-``proposed``
#: anchor is undecided and does not satisfy the gate.
_ANCHOR_DECIDED = ("approved", "deferred")


def _is_broad_class_claim(claim: Claim) -> bool:
    """A broad domain claim = an approved materializing class claim (§5.4)."""
    return (
        claim.type == "class"
        and claim.status == "approved"
        and claim.disposition in ("claim", "specialize")
    )


def _uri_owners(uri: str, uri_index: dict[str, set[str]]) -> set[str]:
    """Return the data-domain ids that own ``uri`` by namespace-prefix match.

    ``data-domains.yaml`` ``uris`` are reference-model namespace prefixes; a class
    URI is owned by a domain when it starts with one of that domain's prefixes.
    """
    owners: set[str] = set()
    for prefix, domains in uri_index.items():
        if uri.startswith(prefix):
            owners |= domains
    return owners


def _build_uri_owner_index(
    data_domains: dict[str, object] | None,
) -> dict[str, set[str]]:
    """Map each declared reference-model namespace prefix → owning data-domain ids.

    Built from ``data-domains.yaml`` ``uris`` lists so the ownership-boundary
    check can tell which domain a claim's ``class_uri`` belongs to.
    """
    index: dict[str, set[str]] = {}
    if not data_domains:
        return index
    for domain_id, meta in data_domains.items():
        if not isinstance(meta, dict):
            continue
        for uri in meta.get("uris", []) or []:
            if not uri:
                continue
            index.setdefault(str(uri), set()).add(domain_id)
    return index


@dataclass
class DuplicateApproved:
    """A cross-file duplicate ``approved`` claim for the same identifying URI."""

    uri: str
    first: str  # "domain:claim_id"
    second: str  # "domain:claim_id"


@dataclass
class OwnershipConflict:
    """An approved claim whose URI is owned by a *different* data-domain."""

    domain: str  # registry domain that approved the claim
    claim_id: str
    uri: str
    owners: list[str]  # data-domain ids that declare ownership of the URI


@dataclass
class ClaimCheckReport:
    """Result of the deterministic ``check-claims`` gate.

    Domain-id buckets mirror the retired alignment gate; ``orphan`` holds claims
    file domain names with no matching affinity domain.
    """

    missing: list[str] = field(default_factory=list)
    invalid: dict[str, list[str]] = field(default_factory=dict)
    incomplete: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    orphan: list[str] = field(default_factory=list)
    #: domain → sorted "system.table" strings affinity-assigned but absent from
    #: the registry's coverage snapshot.
    uncovered_tables: dict[str, list[str]] = field(default_factory=dict)
    #: domains whose registry exists but is absent from ``data-domains.yaml``.
    unowned: list[str] = field(default_factory=list)
    #: cross-file duplicate approved identifying URIs (blocking).
    duplicate_approved: list[DuplicateApproved] = field(default_factory=list)
    #: duplicate approved URIs explicitly shared via an ownership_override
    #: (conformed dimension) — surfaced as a warning, not a block.
    shared_dimensions: list[DuplicateApproved] = field(default_factory=list)
    #: domain → count of claims still in ``proposed`` status (undecided).
    proposed_counts: dict[str, int] = field(default_factory=dict)
    #: MDM-anchor gate — domain → undecided (proposed) anchor claim ids that
    #: must be decided before its broad class claims may stand (blocking).
    anchor_pending: dict[str, list[str]] = field(default_factory=dict)
    #: domains with approved broad class claims but **no** declared MDM anchors
    #: at all (warning — pragmatic nudge, §5.4 "anchors must be known").
    anchor_missing: list[str] = field(default_factory=list)
    #: deviation-log — domain → approved ``gap`` claim ids lacking a deviation
    #: record (owner + reason) (blocking).
    deviation_missing: dict[str, list[str]] = field(default_factory=dict)
    #: ownership-boundary — approved claims owned by a different data-domain and
    #: not covered by an ownership_override (blocking).
    ownership_conflicts: list[OwnershipConflict] = field(default_factory=list)
    #: passthrough-review — domain → high-use passthrough claim ids not yet
    #: marked ``passthrough_reviewed`` (warning).
    passthrough_review: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        """True on any hard failure."""
        return bool(
            self.missing
            or self.invalid
            or self.incomplete
            or self.stale
            or self.duplicate_approved
            or self.anchor_pending
            or self.deviation_missing
            or self.ownership_conflicts
        )

    @property
    def has_warnings(self) -> bool:
        """True when a non-blocking concern exists."""
        return bool(
            self.unverifiable
            or self.orphan
            or self.unowned
            or self.anchor_missing
            or self.shared_dimensions
            or self.passthrough_review
        )

    @property
    def total_proposed(self) -> int:
        return sum(self.proposed_counts.values())

    def has_undecided_claims(self) -> bool:
        """True when any registry still carries an undecided ``proposed`` claim."""
        return self.total_proposed > 0


def _has_ownership_override(claim: Claim) -> bool:
    """True when a claim carries a well-formed ownership_override exception."""
    ovr = claim.ownership_override
    return bool(ovr and ovr.owner and ovr.rationale)


#: Evidence-source types that signal a passthrough field is *high-use* and so a
#: promotion-review candidate (methodology §11.2 promotion triggers).
_HIGH_USE_EVIDENCE = frozenset(
    {
        "powerbi_measure",
        "powerbi_slicer",
        "powerbi_filter",
        "powerbi_hierarchy",
        "join",
        "foreign_key",
        "fk",
        "sample_signal",
    }
)


def _is_high_use_passthrough(claim: Claim) -> bool:
    """A passthrough claim is high-use when it spans ≥2 source systems or is used
    in a Power BI measure/slicer/filter or a join/FK (§11.2)."""
    systems = {ev.system for ev in claim.evidence_sources if ev.system}
    if len(systems) >= 2:
        return True
    return any(
        ev.measure or ev.type in _HIGH_USE_EVIDENCE for ev in claim.evidence_sources
    )


def _run_governance_scans(
    domain: str,
    registry: ClaimRegistry,
    report: ClaimCheckReport,
    uri_index: dict[str, set[str]],
    *,
    check_mdm_anchor: bool,
    check_ownership: bool,
) -> None:
    """Apply the Slice 4 governance scans (MDM-anchor, deviation-log,
    ownership-boundary, passthrough-review) to one loaded registry."""
    # MDM-anchor gate (§5.4): broad domain claims need known reference anchors.
    if check_mdm_anchor and any(_is_broad_class_claim(c) for c in registry.claims):
        anchors = [
            c for c in registry.claims if c.mdm_anchor and c.type == "reference_data"
        ]
        if not anchors:
            report.anchor_missing.append(domain)
        else:
            pending = sorted(c.id for c in anchors if c.status not in _ANCHOR_DECIDED)
            if pending:
                report.anchor_pending[domain] = pending

    # deviation-log (§12 / §14): approved client-native (gap) claims need a record.
    deviation_missing = sorted(
        c.id
        for c in registry.claims
        if c.status == "approved"
        and c.disposition == "gap"
        and (c.deviation is None or not c.deviation.owner or not c.deviation.reason)
    )
    if deviation_missing:
        report.deviation_missing[domain] = deviation_missing

    # ownership-boundary (§14): approved claims must be owned by their data-domain.
    if check_ownership and uri_index:
        for claim in registry.claims:
            if claim.status != "approved":
                continue
            uri = claim.identifying_uri()
            if not uri:
                continue
            owners = _uri_owners(uri, uri_index)
            if not owners or domain in owners:
                continue
            if _has_ownership_override(claim):
                continue
            report.ownership_conflicts.append(
                OwnershipConflict(
                    domain=domain,
                    claim_id=claim.id,
                    uri=uri,
                    owners=sorted(owners),
                )
            )

    # passthrough-review (§11.2): high-use passthrough fields awaiting review.
    flagged = sorted(
        c.id
        for c in registry.claims
        if c.disposition == "passthrough"
        and not c.passthrough_reviewed
        and _is_high_use_passthrough(c)
    )
    if flagged:
        report.passthrough_review[domain] = flagged


def check_claims_coverage(
    *,
    claims_dir: Path,
    analysis_dir: Path,
    data_domains: dict[str, object] | None = None,
    domains_filter: list[str] | None = None,
    check_mdm_anchor: bool = True,
    check_ownership: bool = True,
) -> ClaimCheckReport:
    """Verify every affinity domain has a valid, complete, fresh Claim Registry.

    For each domain enumerated in the affinity reports:
      - **missing**      — no ``{domain}-claims.yaml`` → blocking.
      - **invalid**      — registry fails structural validation → blocking
        (``invalid[domain]`` lists the error messages).
      - **incomplete**   — registry coverage omits an affinity table → blocking
        (``uncovered_tables`` lists the gaps).
      - **stale**        — registry ``freshness.affinity_sha256`` differs from the
        current affinity table set → blocking.
      - **unverifiable** — registry is complete but has no freshness hash or was
        produced by an older algorithm version → warn.
      - **ok**           — valid, complete, and fresh.
      - **orphan**       — claims file for a domain absent from affinity → warn.

    Cross-file duplicate ``approved`` identifying URIs are collected globally and
    are blocking (unless an ``ownership_override`` marks the shared class as a
    conformed dimension, in which case it lands in ``shared_dimensions``, a
    warning). Domains whose registry exists but are absent from
    ``data-domains.yaml`` are reported as ``unowned`` (warning).

    Slice 4 governance scans run on each valid registry:

      - **MDM-anchor gate** — broad (approved) class claims require their domain's
        declared ``mdm_anchor`` reference-data anchors to be decided
        (approved/deferred); pending anchors block (``anchor_pending``), and a
        domain with broad claims but no declared anchors warns
        (``anchor_missing``).
      - **deviation-log** — approved ``gap`` (client-native) claims must carry a
        deviation record (owner + reason); missing → ``deviation_missing``
        (blocking).
      - **ownership-boundary** — approved claims whose ``class_uri`` namespace is
        owned by a *different* data-domain (per ``data-domains.yaml``) block as
        ``ownership_conflicts`` unless an ``ownership_override`` is present.
      - **passthrough-review** — high-use (multi-source / measure / join)
        passthrough claims not yet ``passthrough_reviewed`` → ``passthrough_review``
        (warning).
    """
    report = ClaimCheckReport()
    domain_tables = load_affinity_domain_tables(analysis_dir)
    uri_index = _build_uri_owner_index(data_domains)

    lower_filter = [d.lower() for d in domains_filter] if domains_filter else None

    def in_scope(domain: str) -> bool:
        if lower_filter is None:
            return True
        return any(f in domain.lower() for f in lower_filter)

    # uri -> (label, claim) of the first approved claim that owns it.
    approved_uris: dict[str, tuple[str, Claim]] = {}
    seen_files: set[str] = set()

    def scan_duplicates(domain: str, registry: ClaimRegistry) -> None:
        for claim in registry.claims:
            if claim.status != "approved":
                continue
            uri = claim.identifying_uri()
            if not uri:
                continue
            label = f"{domain}:{claim.id}"
            if uri in approved_uris:
                prev_label, prev_claim = approved_uris[uri]
                dup = DuplicateApproved(uri=uri, first=prev_label, second=label)
                if _has_ownership_override(claim) or _has_ownership_override(prev_claim):
                    report.shared_dimensions.append(dup)
                else:
                    report.duplicate_approved.append(dup)
            else:
                approved_uris[uri] = (label, claim)

    for domain in sorted(domain_tables):
        if not in_scope(domain):
            continue
        expected = domain_tables[domain]
        path = registry_path(claims_dir, domain)
        seen_files.add(path.name)

        if not path.exists():
            report.missing.append(domain)
            report.uncovered_tables[domain] = sorted(f"{s}.{t}" for s, t in expected)
            continue

        try:
            registry = load_registry(path)
        except Exception as exc:
            report.invalid[domain] = [f"could not load registry: {exc}"]
            continue

        if data_domains is not None and domain not in data_domains:
            report.unowned.append(domain)

        errors = validation_errors(validate_registry(registry))
        if errors:
            report.invalid[domain] = [i.message for i in errors]
            scan_duplicates(domain, registry)
            continue

        proposed = sum(1 for c in registry.claims if c.status == "proposed")
        if proposed:
            report.proposed_counts[domain] = proposed

        scan_duplicates(domain, registry)
        _run_governance_scans(
            domain,
            registry,
            report,
            uri_index,
            check_mdm_anchor=check_mdm_anchor,
            check_ownership=check_ownership,
        )

        covered = _registry_covered_tables(registry)
        gaps = expected - covered
        if gaps:
            report.incomplete.append(domain)
            report.uncovered_tables[domain] = sorted(f"{s}.{t}" for s, t in gaps)
            continue

        stored = registry.freshness.affinity_sha256
        algorithm_version = registry.algorithm_version or 0
        if not stored or algorithm_version < ALIGNMENT_ALGORITHM_VERSION:
            report.unverifiable.append(domain)
            continue

        if stored != compute_affinity_hash(expected):
            report.stale.append(domain)
        else:
            report.ok.append(domain)

    # Orphan claims files: a registry for a domain not present in affinity.
    if claims_dir.is_dir():
        for claims_file in sorted(claims_dir.glob("*-claims.yaml")):
            if claims_file.name in seen_files:
                continue
            orphan_domain = claims_file.name.replace("-claims.yaml", "")
            if not in_scope(orphan_domain):
                continue
            report.orphan.append(orphan_domain)
            try:
                registry = load_registry(claims_file)
            except Exception:
                continue
            scan_duplicates(orphan_domain, registry)
            _run_governance_scans(
                orphan_domain,
                registry,
                report,
                uri_index,
                check_mdm_anchor=check_mdm_anchor,
                check_ownership=check_ownership,
            )

    return report
