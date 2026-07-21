# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic Claim Registry coverage gate (``check-claims``).

Single governance gate that replaces both former alignment-era gates
(``check-alignment`` + ``check-source-coverage``) now that the Claim Registry is
the one source of truth (DD-094). It is deterministic and
AI-free — every input is committed, structured YAML/TTL:

* the Claim Registry (``model/claims/{domain}-claims.yaml``) — schema validity,
  per-table coverage snapshot, freshness digest, ownership, claim status;
* canonical completeness facts — the affinity assignment, registry table snapshot,
  and freshness baseline computed once from committed structured inputs.

The gate buckets each affinity domain with priority
``missing > invalid > incomplete > stale > unverifiable > ok`` (parity with the
retired alignment gate), and additionally surfaces cross-file duplicate
``approved`` claims, ownership gaps vs ``data-domains.yaml``, and — under
``--strict`` — registries that still carry undecided (``proposed``) claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .completeness_model import (
    CompletenessFacts,
    DomainCompleteness,
    compute_completeness_facts,
)
from .claim_registry import (
    Claim,
)

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
    #: F6 (toolkit-optimizations) — column-omission gate. domain → sorted
    #: ``"system.table (registry N of M source columns)"`` strings where the
    #: registry covers fewer columns than the affinity report recorded for the
    #: source table (i.e. columns were dropped — e.g. by prompt truncation —
    #: before reaching the registry). Blocking: a truncated registry must never
    #: report complete.
    column_omissions: dict[str, list[str]] = field(default_factory=dict)
    #: F2/F7 (toolkit-optimizations) — grain-conflict gate. domain → sorted
    #: ``"ref_class: entityA, entityB"`` strings where multiple source tables with
    #: different candidate business entities collapsed onto one reference class
    #: (merge-by-nearest-anchor). Blocking: a human must confirm the tables share a
    #: grain or split the model before the collapsed class claim can stand.
    grain_conflicts: dict[str, list[str]] = field(default_factory=dict)

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
            or self.column_omissions
            or self.grain_conflicts
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
    claims: tuple[Claim, ...],
    report: ClaimCheckReport,
    uri_index: dict[str, set[str]],
    *,
    check_mdm_anchor: bool,
    check_ownership: bool,
) -> None:
    """Apply the Slice 4 governance scans (MDM-anchor, deviation-log,
    ownership-boundary, passthrough-review) to one registry fact."""
    # MDM-anchor gate (§5.4): broad domain claims need known reference anchors.
    if check_mdm_anchor and any(_is_broad_class_claim(c) for c in claims):
        anchors = [
            c for c in claims if c.mdm_anchor and c.type == "reference_data"
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
        for c in claims
        if c.status == "approved"
        and c.disposition == "gap"
        and (c.deviation is None or not c.deviation.owner or not c.deviation.reason)
    )
    if deviation_missing:
        report.deviation_missing[domain] = deviation_missing

    # ownership-boundary (§14): approved claims must be owned by their data-domain.
    if check_ownership and uri_index:
        for claim in claims:
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
        for c in claims
        if c.disposition == "passthrough"
        and not c.passthrough_reviewed
        and _is_high_use_passthrough(c)
    )
    if flagged:
        report.passthrough_review[domain] = flagged


def evaluate_claims_coverage(
    facts: CompletenessFacts,
    *,
    data_domains: dict[str, object] | None = None,
    domains_filter: list[str] | None = None,
    check_mdm_anchor: bool = True,
    check_ownership: bool = True,
) -> ClaimCheckReport:
    """Evaluate the Claim Registry gate over a canonical completeness snapshot."""

    report = ClaimCheckReport()
    uri_index = _build_uri_owner_index(data_domains)

    def in_scope(domain: str) -> bool:
        if domains_filter is None:
            return True
        return any(fragment.lower() in domain.lower() for fragment in domains_filter)

    # uri -> (label, claim) of the first approved claim that owns it.
    approved_uris: dict[str, tuple[str, Claim]] = {}

    def scan_duplicates(domain: str, registry: DomainCompleteness) -> None:
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

    for registry in facts.domains:
        domain = registry.domain
        if not in_scope(domain):
            continue
        table_facts = facts.tables_for_domain(domain)

        if not registry.registry_exists:
            report.missing.append(domain)
            report.uncovered_tables[domain] = sorted(
                f"{fact.system}.{fact.table}" for fact in table_facts
            )
            continue

        if registry.load_error is not None:
            report.invalid[domain] = [registry.load_error]
            continue
        if data_domains is not None and domain not in data_domains:
            report.unowned.append(domain)
        if registry.validation_errors:
            report.invalid[domain] = list(registry.validation_errors)
            scan_duplicates(domain, registry)
            continue

        proposed = sum(1 for c in registry.claims if c.status == "proposed")
        if proposed:
            report.proposed_counts[domain] = proposed

        scan_duplicates(domain, registry)
        _run_governance_scans(
            domain,
            registry.claims,
            report,
            uri_index,
            check_mdm_anchor=check_mdm_anchor,
            check_ownership=check_ownership,
        )

        # F2/F7: surface persisted grain-conflict records (distinct-grain tables
        # collapsed onto one reference class) as a blocking governance signal.
        conflicts = [
            f"{conflict.ref_class}: {', '.join(conflict.candidate_entities)}"
            for conflict in registry.grain_conflicts
        ]
        if conflicts:
            report.grain_conflicts[domain] = sorted(conflicts)

        gaps = [fact for fact in table_facts if fact.registry_coverage is None]
        if gaps:
            report.incomplete.append(domain)
            report.uncovered_tables[domain] = sorted(
                f"{fact.system}.{fact.table}" for fact in gaps
            )
            continue

        # F6: column-omission gate. Compare how many columns actually reached the
        # registry against the trustworthy affinity source-column count. A shortfall
        # means columns were dropped before the registry (e.g. prompt truncation),
        # so the registry must not be trusted as complete.
        omissions: list[str] = []
        for fact in table_facts:
            affinity_total = fact.assignment.total_columns
            reg_total = fact.registry_coverage.total_columns if fact.registry_coverage else 0
            if affinity_total and reg_total < affinity_total:
                omissions.append(
                    f"{fact.system}.{fact.table} (registry {reg_total} of {affinity_total} "
                    "source columns)"
                )
        if omissions:
            report.column_omissions[domain] = omissions
            continue

        if registry.freshness.state == "unverifiable":
            report.unverifiable.append(domain)
            continue
        if registry.freshness.state == "stale":
            report.stale.append(domain)
        else:
            report.ok.append(domain)

    # Orphan claims files: a registry for a domain not present in affinity.
    for registry in facts.orphan_registries:
        if not in_scope(registry.domain):
            continue
        report.orphan.append(registry.domain)
        if registry.load_error is not None:
            continue
        scan_duplicates(registry.domain, registry)
        _run_governance_scans(
            registry.domain,
            registry.claims,
            report,
            uri_index,
            check_mdm_anchor=check_mdm_anchor,
            check_ownership=check_ownership,
        )

    return report


def check_claims_coverage(
    *,
    claims_dir: Path,
    analysis_dir: Path,
    data_domains: dict[str, object] | None = None,
    domains_filter: list[str] | None = None,
    check_mdm_anchor: bool = True,
    check_ownership: bool = True,
    excluded_affinity_systems: set[str] | None = None,
    facts: CompletenessFacts | None = None,
) -> ClaimCheckReport:
    """Build canonical facts when needed, then evaluate the Claim Registry view."""

    facts = facts or compute_completeness_facts(
        analysis_dir=analysis_dir,
        claims_dir=claims_dir,
        domains_filter=domains_filter,
        excluded_affinity_systems=excluded_affinity_systems,
    )
    return evaluate_claims_coverage(
        facts,
        data_domains=data_domains,
        domains_filter=domains_filter,
        check_mdm_anchor=check_mdm_anchor,
        check_ownership=check_ownership,
    )
