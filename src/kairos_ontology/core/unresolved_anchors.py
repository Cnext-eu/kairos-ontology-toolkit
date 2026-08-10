# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Versioned, typed record of a table whose class anchor could not be resolved.

An ``unresolved_anchor`` is deliberately **not** a claim: it never enters the
Claim Registry's proposed/approved/rejected lifecycle
(:mod:`kairos_ontology.core.claim_registry`), because there is nothing yet to
claim — the table's reference-model class identity itself is still open. It
exists so that when :func:`kairos_ontology.core.anchor_resolution
.resolve_table_anchor` finds contradictory confirmed evidence (or, in future,
a modeler flags a table as ambiguous some other way), that decision-point is
recorded with a stable id, its evidence, and provenance — instead of being
silently resolved to the "nearest" class (uri-anchor-contract) or lost on the
next ``propose-alignment`` re-run.

The record is persisted separately from ``{domain}-claims.yaml``, in
``{domain}-unresolved-anchors.yaml``, and merged (not overwritten) across
re-runs: a human (or a future resolution command) can mark one ``resolved``
with a chosen URI, and that decision survives future runs exactly like a
curated Claim Registry decision does via
:func:`claim_registry.merge_preserving_decisions`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: Schema version of one :class:`UnresolvedAnchor` record.
UNRESOLVED_ANCHOR_SCHEMA_VERSION = 1

#: Schema version of the whole ``{domain}-unresolved-anchors.yaml`` document.
UNRESOLVED_ANCHOR_DOC_SCHEMA_VERSION = 1

VALID_ANCHOR_RECORD_STATUSES = ("open", "resolved")

#: Typed reasons an anchor record was raised. Additive — an unrecognized value
#: found when loading is tolerated (diagnostic only), never rejected.
REASON_AMBIGUOUS_CONFIRMED_ALIAS = "ambiguous_confirmed_alias"


def _slug(value: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "-", str(value)).strip("-").lower()
    return s or "x"


def unresolved_anchor_id(domain: str, system: str, table: str) -> str:
    """Stable id for one table's unresolved-anchor record."""
    return f"{domain}-{_slug(system)}-{_slug(table)}-anchor"


@dataclass
class UnresolvedAnchor:
    """One table whose class anchor is not yet resolved (uri-anchor-contract)."""

    id: str
    domain: str
    system: str
    table: str
    likely_entity: str = ""
    candidate_uris: list[str] = field(default_factory=list)
    reason: str = REASON_AMBIGUOUS_CONFIRMED_ALIAS
    evidence: list[str] = field(default_factory=list)
    status: str = "open"
    resolved_uri: str | None = None
    resolved_by: str | None = None
    resolved_at: str | None = None
    schema_version: int = UNRESOLVED_ANCHOR_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "schema_version": self.schema_version,
            "domain": self.domain,
            "system": self.system,
            "table": self.table,
            "reason": self.reason,
            "status": self.status,
        }
        if self.likely_entity:
            out["likely_entity"] = self.likely_entity
        if self.candidate_uris:
            out["candidate_uris"] = list(self.candidate_uris)
        if self.evidence:
            out["evidence"] = list(self.evidence)
        if self.resolved_uri is not None:
            out["resolved_uri"] = self.resolved_uri
        if self.resolved_by is not None:
            out["resolved_by"] = self.resolved_by
        if self.resolved_at is not None:
            out["resolved_at"] = self.resolved_at
        return out

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, diagnostics: list[str] | None = None
    ) -> UnresolvedAnchor | None:
        """Parse one record, tolerantly.

        Returns ``None`` (and appends a message to *diagnostics*, when given)
        for a record missing its identity (``id``/``domain``/``system``/
        ``table``) instead of raising, so a legacy or partially-written
        document never blocks the whole load. An unrecognized ``status`` is
        coerced to ``"open"`` with a diagnostic, never dropped.
        """

        def diag(msg: str) -> None:
            if diagnostics is not None:
                diagnostics.append(msg)
            else:
                logger.warning(msg)

        rid = str(data.get("id", "") or "")
        domain = str(data.get("domain", "") or "")
        system = str(data.get("system", "") or "")
        table = str(data.get("table", "") or "")
        if not rid or not domain or not system or not table:
            diag(f"Skipping malformed unresolved-anchor record (missing identity): {data!r}")
            return None

        status = str(data.get("status", "open") or "open")
        if status not in VALID_ANCHOR_RECORD_STATUSES:
            diag(f"{rid}: unknown status {status!r}; coercing to 'open'.")
            status = "open"

        schema_version = data.get("schema_version", UNRESOLVED_ANCHOR_SCHEMA_VERSION)
        try:
            schema_version = int(schema_version)
        except (TypeError, ValueError):
            diag(f"{rid}: invalid schema_version {schema_version!r}; defaulting to 1.")
            schema_version = UNRESOLVED_ANCHOR_SCHEMA_VERSION
        if schema_version > UNRESOLVED_ANCHOR_SCHEMA_VERSION:
            diag(
                f"{rid}: unresolved-anchor schema_version {schema_version} is newer "
                f"than this toolkit supports ({UNRESOLVED_ANCHOR_SCHEMA_VERSION}); "
                "loading it tolerantly (forward-compat)."
            )

        return cls(
            id=rid,
            domain=domain,
            system=system,
            table=table,
            likely_entity=str(data.get("likely_entity", "") or ""),
            candidate_uris=list(data.get("candidate_uris") or []),
            reason=str(data.get("reason", REASON_AMBIGUOUS_CONFIRMED_ALIAS) or ""),
            evidence=list(data.get("evidence") or []),
            status=status,
            resolved_uri=data.get("resolved_uri"),
            resolved_by=data.get("resolved_by"),
            resolved_at=data.get("resolved_at"),
            schema_version=schema_version,
        )


def unresolved_anchors_path(claims_dir: Path, domain: str) -> Path:
    """Path of a domain's unresolved-anchors document (sibling of its claims file)."""
    return Path(claims_dir) / f"{domain}-unresolved-anchors.yaml"


def load_unresolved_anchors_doc(
    path: Path,
) -> tuple[list[UnresolvedAnchor], list[str]]:
    """Load an unresolved-anchors document.

    Returns ``(anchors, diagnostics)``. Never raises: a missing file returns
    ``([], [])``; a malformed file, unreadable YAML, or a document that is not
    a mapping returns ``([], [<diagnostic>])`` so a caller can surface it
    without aborting (backward-compatible migration/loading diagnostics —
    uri-anchor-contract).
    """
    path = Path(path)
    if not path.is_file():
        return [], []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return [], [f"Could not parse unresolved-anchors document {path}: {exc}"]
    if not isinstance(data, dict):
        return [], [f"Unresolved-anchors document is not a mapping: {path}"]

    diagnostics: list[str] = []
    raw_anchors = data.get("anchors")
    if not isinstance(raw_anchors, list):
        if raw_anchors is not None:
            diagnostics.append(f"{path}: 'anchors' is not a list; ignoring.")
        raw_anchors = []

    anchors: list[UnresolvedAnchor] = []
    for entry in raw_anchors:
        if not isinstance(entry, dict):
            diagnostics.append(f"{path}: skipping non-mapping anchor entry {entry!r}.")
            continue
        anchor = UnresolvedAnchor.from_dict(entry, diagnostics=diagnostics)
        if anchor is not None:
            anchors.append(anchor)
    return anchors, diagnostics


def merge_preserving_anchor_resolutions(
    fresh: list[UnresolvedAnchor], existing: list[UnresolvedAnchor]
) -> list[UnresolvedAnchor]:
    """Merge a freshly-computed anchor list with a previously-persisted one.

    A ``resolved`` decision on an existing record survives even though the
    same ambiguity is (harmlessly) detected again this run — the human's
    resolution is never silently discarded, the same guarantee
    ``claim_registry.merge_preserving_decisions`` gives claims. A record only
    in *existing* (this run no longer reproduces the ambiguity — e.g. the
    conformance artifact was corrected) is dropped when still ``open`` (it is
    stale), but kept when ``resolved`` (the resolution itself is the durable
    fact worth keeping for history/audit).
    """
    existing_by_id = {a.id: a for a in existing}
    merged: list[UnresolvedAnchor] = []
    seen_ids: set[str] = set()

    for anchor in fresh:
        prior = existing_by_id.get(anchor.id)
        if prior is not None and prior.status == "resolved":
            merged.append(prior)
        else:
            merged.append(anchor)
        seen_ids.add(anchor.id)

    for anchor in existing:
        if anchor.id not in seen_ids and anchor.status == "resolved":
            merged.append(anchor)
            seen_ids.add(anchor.id)

    merged.sort(key=lambda a: a.id)
    return merged


def write_unresolved_anchors_doc(path: Path, domain: str, anchors: list[UnresolvedAnchor]) -> Path:
    """Write a domain's unresolved-anchors document deterministically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": UNRESOLVED_ANCHOR_DOC_SCHEMA_VERSION,
        "domain": domain,
        "anchors": [a.to_dict() for a in sorted(anchors, key=lambda a: a.id)],
    }
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return path
