# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic claim curation — query + bulk status decisions.

The Claim Registry (``model/claims/{domain}-claims.yaml``) is the single governed,
git-tracked source of truth (DD-094). It is intentionally **not** backed by a
database: the runtime already loads the whole registry into memory, and a binary
store would sacrifice the reviewable-diff governance model. The friction that
motivated this module (issue #190 items 2 & 3) is the *missing query + bulk-update
API* — curators previously hand-edited YAML, producing unreviewable diffs.

This module provides:

* :func:`select_claims` — a composable, read-only, in-memory **query** layer
  (status / disposition / type / origin filters + id and source-column globs).
* :func:`apply_decisions` — a **bulk** ``status`` mutation that only touches the
  ``status`` field, honours :data:`STATUS_TRANSITIONS`, and reports skipped/invalid
  transitions. Callers persist via the existing canonical
  :func:`kairos_ontology.core.claim_registry.write_registry`, so diffs stay minimal.

The module is AI-free and side-effect-free (no I/O); the CLI owns load/write.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from .claim_registry import (
    VALID_DISPOSITIONS,
    VALID_ORIGINS,
    VALID_STATUSES,
    VALID_TYPES,
    Claim,
    ClaimRegistry,
    approval_gate_errors,
    is_valid_transition,
)


@dataclass
class ClaimSelector:
    """A composable, read-only filter over a registry's claims.

    Empty / ``None`` fields match everything. List fields match if the claim's
    value is in the list. ``id_globs`` / ``column_globs`` use shell-style globbing
    (:func:`fnmatch.fnmatchcase` for ids; case-insensitive for columns).
    """

    status: list[str] | None = None
    disposition: list[str] | None = None
    type: list[str] | None = None
    origin: list[str] | None = None
    id_globs: list[str] = field(default_factory=list)
    column_globs: list[str] = field(default_factory=list)

    def matches(self, claim: Claim) -> bool:
        if self.status and claim.status not in self.status:
            return False
        if self.disposition and claim.disposition not in self.disposition:
            return False
        if self.type and claim.type not in self.type:
            return False
        if self.origin and claim.origin not in self.origin:
            return False
        if self.id_globs and not any(
            fnmatch.fnmatchcase(claim.id, pat) for pat in self.id_globs
        ):
            return False
        if self.column_globs and not _claim_matches_column_globs(claim, self.column_globs):
            return False
        return True

    @property
    def is_empty(self) -> bool:
        """True when no filter is set (the selector would match every claim)."""
        return not any(
            (self.status, self.disposition, self.type, self.origin, self.id_globs, self.column_globs)
        )


def _claim_matches_column_globs(claim: Claim, globs: list[str]) -> bool:
    columns = [src.column for src in claim.evidence_sources if src.column]
    for column in columns:
        lowered = column.lower()
        if any(fnmatch.fnmatchcase(lowered, pat.lower()) for pat in globs):
            return True
    return False


def select_claims(registry: ClaimRegistry, selector: ClaimSelector) -> list[Claim]:
    """Return the registry claims matching *selector* (insertion order preserved)."""
    return [claim for claim in registry.claims if selector.matches(claim)]


def parse_by_disposition(spec: str) -> dict[str, str]:
    """Parse a ``disposition=status,...`` mapping (e.g. ``claim=approved,skip=rejected``).

    Raises :class:`ValueError` on an unknown disposition or status, or malformed pair.
    """
    mapping: dict[str, str] = {}
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"malformed disposition=status pair: {item!r}")
        disposition, status = (part.strip() for part in item.split("=", 1))
        if disposition not in VALID_DISPOSITIONS:
            raise ValueError(
                f"unknown disposition {disposition!r} "
                f"(allowed: {', '.join(VALID_DISPOSITIONS)})"
            )
        if status not in VALID_STATUSES:
            raise ValueError(
                f"unknown status {status!r} (allowed: {', '.join(VALID_STATUSES)})"
            )
        mapping[disposition] = status
    if not mapping:
        raise ValueError("no disposition=status pairs provided")
    return mapping


@dataclass
class DecisionResult:
    """Outcome of a single attempted status decision on a claim."""

    claim_id: str
    from_status: str
    to_status: str
    applied: bool
    reason: str | None = None  # populated when ``applied`` is False
    blocking: bool = False


@dataclass
class DecisionSummary:
    """Aggregate outcome of a bulk decision run."""

    results: list[DecisionResult] = field(default_factory=list)

    @property
    def applied(self) -> list[DecisionResult]:
        return [r for r in self.results if r.applied]

    @property
    def skipped(self) -> list[DecisionResult]:
        return [r for r in self.results if not r.applied]

    @property
    def blocked(self) -> list[DecisionResult]:
        return [r for r in self.results if r.blocking]

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def _decide_one(claim: Claim, target_status: str, *, apply: bool) -> DecisionResult:
    current = claim.status
    if current == target_status:
        return DecisionResult(claim.id, current, target_status, False, "already in target status")
    if not is_valid_transition(current, target_status):
        return DecisionResult(
            claim.id,
            current,
            target_status,
            False,
            f"invalid transition {current} → {target_status}",
        )
    if apply:
        claim.status = target_status
    return DecisionResult(claim.id, current, target_status, True)


def _target_for_claim(
    claim: Claim,
    *,
    set_status: str | None,
    by_disposition: dict[str, str] | None,
) -> str | None:
    if set_status is not None:
        return set_status
    return by_disposition.get(claim.disposition) if by_disposition is not None else None


def _approval_blocker(claim: Claim, target_status: str) -> DecisionResult | None:
    current = claim.status
    if target_status != "approved" or current == target_status:
        return None
    if not is_valid_transition(current, target_status):
        return None
    errors = approval_gate_errors(claim, target_status=target_status)
    if not errors:
        return None
    return DecisionResult(
        claim.id,
        current,
        target_status,
        False,
        "approval blocked: " + "; ".join(errors),
        True,
    )


def apply_decisions(
    registry: ClaimRegistry,
    *,
    selector: ClaimSelector,
    set_status: str | None = None,
    by_disposition: dict[str, str] | None = None,
    dry_run: bool = False,
) -> DecisionSummary:
    """Apply bulk status decisions to *registry* (mutates in place unless ``dry_run``).

    Exactly one of ``set_status`` or ``by_disposition`` must be provided:

    * ``set_status`` — set every selected claim to that single status.
    * ``by_disposition`` — set each selected claim to the status mapped from its
      ``disposition`` (claims whose disposition is not in the map are left untouched).

    Only the ``status`` field is changed, and only along an allowed transition
    (:func:`is_valid_transition`); same-status and invalid transitions are recorded
    as skipped in the returned :class:`DecisionSummary`.
    """
    if (set_status is None) == (by_disposition is None):
        raise ValueError("provide exactly one of set_status or by_disposition")
    if set_status is not None and set_status not in VALID_STATUSES:
        raise ValueError(f"unknown status {set_status!r} (allowed: {', '.join(VALID_STATUSES)})")

    summary = DecisionSummary()
    targets: list[tuple[Claim, str]] = []
    for claim in select_claims(registry, selector):
        target = _target_for_claim(
            claim, set_status=set_status, by_disposition=by_disposition
        )
        if target is None:
            continue
        targets.append((claim, target))
        blocker = _approval_blocker(claim, target)
        if blocker is not None:
            summary.results.append(blocker)

    if summary.blocked:
        return summary

    for claim, target in targets:
        summary.results.append(_decide_one(claim, target, apply=not dry_run))
    return summary


def validate_filter_values(
    *,
    status: list[str] | None,
    disposition: list[str] | None,
    type_: list[str] | None,
    origin: list[str] | None,
) -> None:
    """Raise :class:`ValueError` for any unknown filter enum value."""
    for label, values, allowed in (
        ("status", status, VALID_STATUSES),
        ("disposition", disposition, VALID_DISPOSITIONS),
        ("type", type_, VALID_TYPES),
        ("origin", origin, VALID_ORIGINS),
    ):
        for value in values or []:
            if value not in allowed:
                raise ValueError(
                    f"unknown {label} {value!r} (allowed: {', '.join(allowed)})"
                )
