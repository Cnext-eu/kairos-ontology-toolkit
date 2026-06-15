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


@dataclass
class DuplicateApproved:
    """A cross-file duplicate ``approved`` claim for the same identifying URI."""

    uri: str
    first: str  # "domain:claim_id"
    second: str  # "domain:claim_id"


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
    #: cross-file duplicate approved identifying URIs.
    duplicate_approved: list[DuplicateApproved] = field(default_factory=list)
    #: domain → count of claims still in ``proposed`` status (undecided).
    proposed_counts: dict[str, int] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        """True on any hard failure (missing/invalid/incomplete/stale/dup)."""
        return bool(
            self.missing
            or self.invalid
            or self.incomplete
            or self.stale
            or self.duplicate_approved
        )

    @property
    def has_warnings(self) -> bool:
        """True when a non-blocking concern exists (unverifiable/orphan/unowned)."""
        return bool(self.unverifiable or self.orphan or self.unowned)

    @property
    def total_proposed(self) -> int:
        return sum(self.proposed_counts.values())

    def has_undecided_claims(self) -> bool:
        """True when any registry still carries an undecided ``proposed`` claim."""
        return self.total_proposed > 0


def check_claims_coverage(
    *,
    claims_dir: Path,
    analysis_dir: Path,
    data_domains: dict[str, object] | None = None,
    domains_filter: list[str] | None = None,
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
    are blocking. Domains whose registry exists but are absent from
    ``data-domains.yaml`` are reported as ``unowned`` (warning).
    """
    report = ClaimCheckReport()
    domain_tables = load_affinity_domain_tables(analysis_dir)

    lower_filter = [d.lower() for d in domains_filter] if domains_filter else None

    def in_scope(domain: str) -> bool:
        if lower_filter is None:
            return True
        return any(f in domain.lower() for f in lower_filter)

    # uri -> "domain:claim_id" of the first approved claim that owns it.
    approved_uris: dict[str, str] = {}
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
                report.duplicate_approved.append(
                    DuplicateApproved(uri=uri, first=approved_uris[uri], second=label)
                )
            else:
                approved_uris[uri] = label

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

    return report
