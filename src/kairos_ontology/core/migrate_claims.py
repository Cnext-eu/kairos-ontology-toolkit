# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One-way migration: ``{domain}-alignment.yaml`` → ``{domain}-claims.yaml``.

Deterministic and AI-free (DD-094, schema doc §3). Converts the
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
import os
import re
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
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
    from .inventory import InventoryMigrationRequiredError, load_inventory

    classes: list[dict[str, Any]] = []
    if not inventory_dir.is_dir():
        return {}, {}
    for yaml_file in sorted(inventory_dir.glob("*.yaml")):
        try:
            inv = load_inventory(yaml_file)
        except InventoryMigrationRequiredError:
            # A retired stem-named inventory must never be silently skipped: that
            # would drop URI candidates and make a claims migration incomplete.
            raise
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
        f"{path.name} is retired (DD-094). Run the one-shot migration to "
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
    # F2/F7 (toolkit-optimizations): track which source tables (and their candidate
    # business entities) collapse onto each ref_class, so a merge that fuses
    # *different* grains onto one class can be flagged as a blocking grain conflict.
    class_table_entities: dict[str, list[dict[str, str]]] = {}
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
            source_column_count=int(table.get("source_column_count", 0) or 0),
            source_column_sha256=table.get("source_column_sha256"),
        )

        # Class claim (one per distinct ref class).
        if ref_class:
            likely_entity = str(table.get("likely_entity", "") or "")
            class_table_entities.setdefault(ref_class, []).append({
                "system": system,
                "table": tname,
                "likely_entity": likely_entity,
            })
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

    # F2/F7: detect grain conflicts — a single ref_class that multiple source
    # tables with *different* candidate business entities (likely_entity) collapsed
    # onto. This is the merge-by-nearest-anchor failure mode: distinct grains fused
    # into one class. Deterministic; emitted only when 2+ distinct entities collide.
    grain_conflicts: list[dict[str, Any]] = []
    for ref_class in sorted(class_table_entities):
        members = class_table_entities[ref_class]
        distinct_entities = sorted(
            {m["likely_entity"] for m in members if m["likely_entity"]}
        )
        if len(distinct_entities) > 1:
            grain_conflicts.append({
                "type": "grain_conflict",
                "ref_class": ref_class,
                "class_claim_id": f"{domain}-{_slug(ref_class)}",
                "candidate_entities": distinct_entities,
                "source_tables": sorted(
                    f"{m['system']}.{m['table']}"
                    for m in members
                ),
                "requires_human_confirmation": True,
                "rationale": (
                    f"{len(members)} source tables with {len(distinct_entities)} "
                    f"different candidate business entities "
                    f"({', '.join(distinct_entities)}) collapsed onto the single "
                    f"reference class '{ref_class}'. Confirm they share a grain or "
                    "split the model before approving the class claim."
                ),
            })

    return ClaimRegistry(
        domain=domain,
        generated_at=data.get("generated_at"),
        algorithm_version=data.get("algorithm_version"),
        freshness=freshness,
        coverage=coverage,
        claims=all_claims,
        relationship_candidates=relationship_candidates,
        grain_conflicts=grain_conflicts,
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


# ---------------------------------------------------------------------------
# Explicit legacy format migration
# ---------------------------------------------------------------------------


class LegacyFormatMigrationError(ValueError):
    """Raised when a legacy format cannot be migrated without losing information."""


@dataclass
class LegacyFormatMigrationPlan:
    """Fully validated, no-write plan consumed by the existing ``migrate`` command."""

    hub: Path
    writes: dict[Path, bytes] = field(default_factory=dict)
    removals: set[Path] = field(default_factory=set)
    inventory_moves: list[tuple[Path, Path]] = field(default_factory=list)
    projection_domains: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.writes or self.removals)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def legacy_format_backup_dir(hub: Path) -> Path:
    """Return the durable backup location used by the one-shot format migration."""
    return hub / ".kairos-migrations" / "legacy-format-backups"


def _plan_inventory_format_migration(
    plan: LegacyFormatMigrationPlan,
    *,
    ref_models_dir: Path | None,
    inventory_dir: Path,
) -> None:
    """Move unambiguous old stem inventories to their canonical namespaced names."""
    from .inventory import find_legacy_inventory_files, legacy_inventory_error

    for finding in find_legacy_inventory_files(
        ref_models_dir=ref_models_dir,
        inventory_dir=inventory_dir,
    ):
        if finding.error:
            plan.errors.append(legacy_inventory_error(finding))
            continue
        if len(finding.source_paths) != 1 or len(finding.canonical_filenames) != 1:
            plan.errors.append(legacy_inventory_error(finding))
            continue

        destination = inventory_dir / finding.canonical_filenames[0]
        source_bytes = finding.path.read_bytes()
        if destination.exists():
            if destination.read_bytes() != source_bytes:
                plan.errors.append(
                    f"{finding.path.name} and canonical {destination.name} both exist with "
                    "different content; retain both, resolve the collision manually, then "
                    "rerun `kairos-ontology migrate --hub <hub>`."
                )
                continue
        else:
            plan.writes[destination] = source_bytes

        plan.removals.add(finding.path)
        plan.inventory_moves.append((finding.path, destination))


def plan_legacy_format_migration(
    hub: Path,
    *,
    ref_models_dir: Path | None = None,
    inventory_dir: Path | None = None,
) -> LegacyFormatMigrationPlan:
    """Plan all retired-format conversions without writing any files.

    The plan is intentionally all-or-nothing.  A malformed or ambiguous inventory,
    malformed managed block, or unsafe Turtle declaration prevents *every* legacy
    conversion so a user never receives a partially migrated hub.
    """
    hub = Path(hub)
    plan = LegacyFormatMigrationPlan(hub=hub)
    inventories = inventory_dir or hub / "referencemodels-unpacked"
    _plan_inventory_format_migration(
        plan,
        ref_models_dir=ref_models_dir,
        inventory_dir=inventories,
    )

    from .claim_projection_sync import plan_legacy_projection_sync_migration

    projection_plan = plan_legacy_projection_sync_migration(
        claims_dir=hub / "model" / "claims",
        ontologies_dir=hub / "model" / "ontologies",
        extensions_dir=hub / "model" / "extensions",
    )
    plan.errors.extend(projection_plan.errors)
    plan.projection_domains.extend(projection_plan.domains)
    for path, text in projection_plan.writes.items():
        content = text.encode("utf-8")
        if not path.is_file() or path.read_bytes() != content:
            plan.writes[path] = content

    return plan


def _backup_destination(hub: Path, backup_root: Path, path: Path) -> Path:
    """Map a changed hub path into its durable, collision-safe backup location."""
    try:
        relative = path.resolve().relative_to(hub.resolve())
    except ValueError as exc:
        raise LegacyFormatMigrationError(
            f"Cannot back up migration path outside the hub: {path}"
        ) from exc
    return backup_root / relative


def _publish_legacy_format_plan(plan: LegacyFormatMigrationPlan) -> list[Path]:
    """Atomically publish staged rewrites and restore originals on any failure."""
    if not plan.is_valid:
        raise LegacyFormatMigrationError("\n".join(plan.errors))
    if not plan.has_changes:
        return []

    hub = plan.hub
    backup_root = legacy_format_backup_dir(hub)
    originals = sorted(
        {
            *plan.removals,
            *(path for path in plan.writes if path.exists()),
        },
        key=str,
    )
    backups: dict[Path, Path] = {}
    staged: dict[Path, Path] = {}
    published: list[Path] = []
    new_destinations = {path for path in plan.writes if not path.exists()}

    try:
        # Backups persist after a successful migration for a manual rollback.  Refuse
        # to overwrite a previous backup with different bytes.
        for original in originals:
            backup = _backup_destination(hub, backup_root, original)
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                if backup.read_bytes() != original.read_bytes():
                    raise LegacyFormatMigrationError(
                        f"Existing migration backup differs from {original}: {backup}. "
                        "Resolve it before rerunning the migration."
                    )
            else:
                shutil.copy2(original, backup)
            backups[original] = backup

        for destination, content in plan.writes.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.legacy-migration-",
                delete=False,
            ) as handle:
                handle.write(content)
                staged[destination] = Path(handle.name)
            if destination.exists():
                shutil.copymode(destination, staged[destination])

        for destination in sorted(staged, key=str):
            os.replace(staged[destination], destination)
            published.append(destination)
            staged.pop(destination)
        for path in sorted(plan.removals, key=str):
            path.unlink()
            published.append(path)
    except Exception:
        restore_errors: list[str] = []
        for original, backup in backups.items():
            try:
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, original)
            except OSError as exc:
                restore_errors.append(f"{original}: {exc}")
        for destination in new_destinations:
            if destination.exists() and destination not in backups:
                try:
                    destination.unlink()
                except OSError as exc:
                    restore_errors.append(f"{destination}: {exc}")
        if restore_errors:
            raise RuntimeError(
                "Legacy-format migration failed and rollback was incomplete: "
                + "; ".join(restore_errors)
            ) from None
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)

    return published


def apply_legacy_format_migration(plan: LegacyFormatMigrationPlan) -> list[Path]:
    """Apply a validated legacy-format migration plan exactly once."""
    return _publish_legacy_format_plan(plan)
