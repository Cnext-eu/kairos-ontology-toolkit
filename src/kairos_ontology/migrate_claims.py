# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One-way migration: ``{domain}-alignment.yaml`` → ``{domain}-claims.yaml``.

Deterministic and AI-free (decision log ``DD-EL-1``, schema doc §3). Converts the
retired alignment output into a Claim Registry of ``proposed`` claims so no prior
analysis is lost; a human then approves/curates. After migration the legacy
alignment file is rejected (no dual path) — callers use
:func:`legacy_alignment_error` to surface a clear message.

Field mapping (schema doc §3.2):

* table ``ref_class``            → one ``class`` claim per *distinct* ref class
  (evidence aggregates every source table that aligned to it).
* column ``ref_property``        → one ``property`` claim per distinct
  ``(ref_class, ref_property)`` (evidence aggregates the source columns).
* ``custom_columns[].disposition`` (``model`` | ``silver-passthrough`` | ``skip``)
  → ``specialize`` | ``passthrough`` | ``skip`` (untriaged → ``passthrough``,
  flagged in the rationale).
* ``source_sha256`` / ``alignment_params_sha256`` → ``freshness``.
* ``algorithm_version`` / ``generated_at`` → top-level fields.
* per-table column counts + ``ref_class_status`` → ``coverage``.

All migrated claims land as ``status: proposed`` — migration never fabricates an
approval. URIs stay unresolved (``class_uri`` / ``property_uri`` = null) until a
human approves the claim; coverage retains the ref-class name for context.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from .claim_registry import (
    TRIAGE_TO_DISPOSITION,
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    Freshness,
)

logger = logging.getLogger(__name__)

LEGACY_ALIGNMENT_GLOB = "*-alignment.yaml"

#: A resolved URI index: ``(class_uri_by_name, property_uri_by_class_and_property)``.
#: Only *unambiguously* resolvable names are kept — a name mapping to more than one
#: URI (same class name in different reference modules) is dropped so migration never
#: guesses a URI. Unresolved claims keep ``class_uri`` / ``property_uri`` = null and
#: stay approvable only after a human supplies the URI.
UriIndex = tuple[dict[str, str], dict[tuple[str, str], str]]


def _namespace_of(uri: str) -> str:
    """Return the namespace prefix (up to and including ``#`` or final ``/``)."""
    if "#" in uri:
        return uri.rsplit("#", 1)[0] + "#"
    if "/" in uri:
        return uri.rsplit("/", 1)[0] + "/"
    return uri


def build_uri_index(inventory_classes: list[dict[str, Any]]) -> UriIndex:
    """Build a deterministic URI index from materialized inventory classes (DD-044).

    Each inventory class carries its ``uri``; property URIs are derived from the
    owning class' namespace + property ``name`` (the convention used across the
    reference models). Names that resolve to more than one URI are *omitted* so the
    caller never materializes an ambiguous guess.
    """
    name_to_class_uris: dict[str, set[str]] = defaultdict(set)
    prop_to_uris: dict[tuple[str, str], set[str]] = defaultdict(set)
    for cls in inventory_classes:
        uri = cls.get("uri")
        name = cls.get("name")
        if not uri or not name:
            continue
        name_to_class_uris[name].add(str(uri))
        namespace = _namespace_of(str(uri))
        for prop in cls.get("properties", []) or []:
            pname = prop.get("name")
            if pname:
                prop_to_uris[(name, pname)].add(namespace + pname)
    class_uri = {n: next(iter(u)) for n, u in name_to_class_uris.items() if len(u) == 1}
    property_uri = {k: next(iter(v)) for k, v in prop_to_uris.items() if len(v) == 1}
    return class_uri, property_uri


def load_inventory_uri_index(inventory_dir: Path) -> UriIndex:
    """Load every ``*-inventory.yaml`` under *inventory_dir* into a :data:`UriIndex`."""
    from .inventory import load_inventory

    classes: list[dict[str, Any]] = []
    if not inventory_dir.is_dir():
        return {}, {}
    for yaml_file in sorted(inventory_dir.glob("*.yaml")):
        try:
            inv = load_inventory(yaml_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load inventory %s: %s", yaml_file, exc)
            continue
        classes.extend(inv.get("classes", []) or [])
    return build_uri_index(classes)


def _slug(value: str) -> str:
    """Stable kebab-case slug for claim ids."""
    s = re.sub(r"[^0-9a-zA-Z]+", "-", str(value)).strip("-").lower()
    return s or "x"


def legacy_alignment_error(path: Path) -> str:
    """Return the standard message for a retired alignment file."""
    domain = path.name.replace("-alignment.yaml", "")
    return (
        f"{path.name} is retired (DD-EL-1). Run the one-shot migration to "
        f"model/claims/{domain}-claims.yaml:\n"
        f"    kairos-ontology migrate-claims --domain {domain}\n"
        f"The alignment YAML is no longer read."
    )


def find_legacy_alignment_files(search_dir: Path) -> list[Path]:
    """Return any legacy ``*-alignment.yaml`` files under *search_dir*."""
    if not search_dir.exists():
        return []
    return sorted(search_dir.glob(LEGACY_ALIGNMENT_GLOB))


def alignment_to_registry(data: dict[str, Any], *, uri_index: UriIndex | None = None) -> ClaimRegistry:
    """Convert a parsed alignment YAML mapping into a :class:`ClaimRegistry`.

    Pure function — deterministic for a given input. Claims and coverage are
    emitted in a stable (sorted) order so the output is byte-stable for golden
    tests.

    When *uri_index* is supplied (issue #190 item 4), ``class_uri`` / ``property_uri``
    are back-filled from the reference-model inventory for unambiguously resolvable
    names, so anchored claims become approvable without manual URI entry. Ambiguous
    or unknown names stay null (still valid while ``proposed``).
    """
    class_uri_map, property_uri_map = uri_index if uri_index else ({}, {})
    domain = str(data.get("domain", "") or "")
    freshness = Freshness(
        affinity_sha256=data.get("source_sha256"),
        alignment_params_sha256=data.get("alignment_params_sha256"),
    )

    # Coverage grouped by system → table.
    coverage_by_system: dict[str, dict[str, CoverageTable]] = {}
    # Issue #192 (Phase A1): advisory, deterministic relationship candidates
    # surfaced to the modeling skill's Relationship & Satellite-Entity Review gate.
    relationship_candidates: list[dict[str, Any]] = []
    # Dedup concept claims; preserve aggregated evidence.
    class_claims: dict[str, Claim] = {}            # key: ref_class
    property_claims: dict[tuple[str, str], Claim] = {}  # key: (ref_class, ref_property)
    custom_claims: dict[tuple[str, str], Claim] = {}    # key: (system, table, column) flattened

    for table in data.get("tables", []) or []:
        system = str(table.get("system", "") or "")
        tname = str(table.get("table", "") or "")
        ref_class = str(table.get("ref_class", "") or "")
        columns = table.get("columns", []) or []
        custom_columns = table.get("custom_columns", []) or []
        anchor_state = str(table.get("ref_class_status", "") or "matched")

        for cand in table.get("relationship_candidates", []) or []:
            if isinstance(cand, dict):
                relationship_candidates.append(cand)

        coverage_by_system.setdefault(system, {})[tname] = CoverageTable(
            table=tname,
            total_columns=len(columns) + len(custom_columns),
            mapped_columns=len(columns),
            custom_columns=len(custom_columns),
            anchor_state=anchor_state if anchor_state in (
                "matched", "fallback", "rejected", "unmatched") else "matched",
            ref_class=ref_class or None,
        )

        # Class claim (one per distinct ref class).
        if ref_class:
            claim = class_claims.get(ref_class)
            if claim is None:
                claim = Claim(
                    id=f"{domain}-{_slug(ref_class)}",
                    type="class",
                    status="proposed",
                    disposition="claim",
                    origin="imported",
                    class_uri=class_uri_map.get(ref_class),
                    rationale=f"Migrated from alignment: source tables aligned to "
                              f"reference class '{ref_class}'.",
                )
                class_claims[ref_class] = claim
            claim.evidence_sources.append(
                EvidenceSource(type="source_table", system=system, table=tname)
            )

        # Property claims (one per distinct ref_class + ref_property).
        for col in columns:
            ref_prop = str(col.get("ref_property", "") or "")
            if not ref_prop:
                continue  # unmatched column — no concept to claim
            col_ref_class = str(col.get("ref_class", "") or ref_class)
            key = (col_ref_class, ref_prop)
            pclaim = property_claims.get(key)
            if pclaim is None:
                pclaim = Claim(
                    id=f"{domain}-{_slug(col_ref_class)}-{_slug(ref_prop)}",
                    type="property",
                    status="proposed",
                    disposition="claim",
                    origin="imported",
                    property_uri=property_uri_map.get((col_ref_class, ref_prop)),
                    rationale=f"Migrated from alignment: maps to property "
                              f"'{ref_prop}' on '{col_ref_class}'.",
                )
                property_claims[key] = pclaim
            pclaim.evidence_sources.append(
                EvidenceSource(
                    type="source_column", system=system, table=tname,
                    column=str(col.get("column", "") or ""),
                )
            )

        # Custom-column claims (client-native; triage → disposition).
        for col in custom_columns:
            cname = str(col.get("column", "") or "")
            triage = col.get("disposition")
            disposition = TRIAGE_TO_DISPOSITION.get(triage) if triage else None
            untriaged = disposition is None
            if untriaged:
                disposition = "passthrough"
            rationale = str(col.get("rationale", "") or "").strip()
            note = (
                "Untriaged custom column — defaulted to passthrough; needs a "
                "disposition decision. " if untriaged else ""
            ) + rationale
            key = (system, tname, cname)
            custom_claims[key] = Claim(
                id=f"{domain}-custom-{_slug(system)}-{_slug(tname)}-{_slug(cname)}",
                type="property",
                status="proposed",
                disposition=disposition,
                origin="authored",
                rationale=note or None,
                evidence_sources=[
                    EvidenceSource(
                        type="source_column", system=system, table=tname, column=cname
                    )
                ],
            )

    coverage = [
        CoverageSystem(
            system=system,
            tables=[coverage_by_system[system][t] for t in sorted(coverage_by_system[system])],
        )
        for system in sorted(coverage_by_system)
    ]

    all_claims = list(class_claims.values()) + list(property_claims.values()) + \
        list(custom_claims.values())
    all_claims.sort(key=lambda c: c.id)

    relationship_candidates.sort(key=lambda c: (
        str(c.get("source_table", "")),
        str(c.get("suggested_relationship", "")),
        str(c.get("role") or ""),
    ))

    return ClaimRegistry(
        domain=domain,
        generated_at=data.get("generated_at"),
        algorithm_version=data.get("algorithm_version"),
        freshness=freshness,
        coverage=coverage,
        claims=all_claims,
        relationship_candidates=relationship_candidates,
    )


def migrate_alignment_file(path: Path, *, inventory_dir: Path | None = None) -> ClaimRegistry:
    """Load an alignment YAML file and convert it to a :class:`ClaimRegistry`.

    When *inventory_dir* is given, ``class_uri`` / ``property_uri`` are back-filled
    from the materialized reference-model inventories under it (issue #190 item 4).
    """
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: alignment file is not a mapping")
    uri_index = load_inventory_uri_index(inventory_dir) if inventory_dir else None
    return alignment_to_registry(data, uri_index=uri_index)
