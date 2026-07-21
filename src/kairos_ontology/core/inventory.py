# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Materialized YAML inventory generation for ontologies and reference models (DD-044).

Produces structured YAML files that capture classes, properties, and specialization
trees.  These inventories are consumed by LLM-based tools (``analyse-sources``,
``propose-alignment``) and ``coverage-report`` as a cached, designer-reviewable
alternative to re-parsing TTL files on every run.

Inventory files live in ``referencemodels-unpacked/`` and are committed to git.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph

from .analyse_sources import parse_reference_model

logger = logging.getLogger(__name__)

INVENTORY_VERSION = "1.1"


def compute_source_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a source TTL file's bytes."""
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def inventory_filename(
    ttl_path: Path,
    *,
    ref_models_dir: Path | None = None,
) -> str:
    """Return the inventory filename for a source TTL (DD-054).

    Reference-model modules are namespaced by their owning model so that
    same-named modules from different models (e.g. ``party.ttl`` in BSP, IMO,
    DCSA…) no longer collide into a single ``{stem}-inventory.yaml`` (the
    last-write-wins data-loss bug).  Hub-owned ontologies keep plain stem naming
    because their stems are unique within a hub.

    Naming rules:
      - Reference-model TTL under ``derived-ontologies/`` →
        ``{model}-{stem}-inventory.yaml`` (model = the path segment directly
        after ``derived-ontologies``, lower-cased).
      - Anything else → ``{stem}-inventory.yaml``.

    The result is deterministic and used by both ``generate-inventory`` and
    ``check_inventories`` so source→inventory mapping always agrees.
    """
    stem = ttl_path.stem
    model = _ref_model_id(ttl_path, ref_models_dir=ref_models_dir)
    if model:
        return f"{model}-{stem}-inventory.yaml"
    return f"{stem}-inventory.yaml"


def _ref_model_id(ttl_path: Path, *, ref_models_dir: Path | None) -> str | None:
    """Return the lower-cased reference-model id owning *ttl_path*, or None.

    The model id is the path segment immediately following ``derived-ontologies``
    (e.g. ``BSP``, ``DCSA``).  Intermediate segments such as DCSA's
    ``shared-kernel`` are ignored — only the model directory disambiguates.
    """
    parts: tuple[str, ...]
    if ref_models_dir is not None:
        try:
            parts = ttl_path.resolve().relative_to(ref_models_dir.resolve()).parts
        except ValueError:
            parts = ttl_path.parts
    else:
        parts = ttl_path.parts

    marker = "derived-ontologies"
    if marker in parts:
        idx = parts.index(marker)
        if idx + 1 < len(parts):
            return parts[idx + 1].lower()
    return None


def is_archived_ref_model_source(ttl_path: Path, *, ref_models_dir: Path | None = None) -> bool:
    """Return True when *ttl_path* is under an archived reference-model version."""
    if ref_models_dir is not None:
        try:
            parts = ttl_path.resolve().relative_to(ref_models_dir.resolve()).parts
        except ValueError:
            parts = ttl_path.parts
    else:
        parts = ttl_path.parts
    return any(part.lower() == "archive" for part in parts)


def iter_reference_inventory_sources(ref_models_dir: Path) -> list[Path]:
    """Return current reference-model TTLs that should produce/check inventories."""
    return [
        ttl
        for ttl in sorted(ref_models_dir.glob("**/*.ttl"))
        if not is_archived_ref_model_source(ttl, ref_models_dir=ref_models_dir)
    ]


def generate_inventory(
    ttl_path: Path | None = None,
    *,
    graph: Graph | None = None,
    domain_name: str | None = None,
    include_specializations: bool = True,
) -> dict[str, Any]:
    """Generate a materialized inventory from an ontology or reference model.

    Delegates to ``parse_reference_model()`` with ``include_specializations=True``
    and wraps the result in an inventory envelope with version and provenance.

    Args:
        ttl_path: Path to a TTL file (mutually exclusive with *graph*).
        graph: Pre-loaded rdflib Graph.
        domain_name: Override domain name.
        include_specializations: Walk ``subClassOf`` downward (default True).

    Returns:
        Dict suitable for YAML serialization.
    """
    parsed = parse_reference_model(
        ttl_path,
        graph=graph,
        domain_name=domain_name,
        include_specializations=include_specializations,
    )

    inventory: dict[str, Any] = {
        "version": INVENTORY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generated_from": str(ttl_path) if ttl_path else "(graph)",
        "source_sha256": compute_source_hash(ttl_path) if ttl_path else None,
        "domain_name": parsed["domain_name"],
        "classes": parsed["classes"],
    }

    return inventory


def write_inventory(inventory: dict[str, Any], output_path: Path) -> Path:
    """Write an inventory dict to a YAML file.

    Creates parent directories if needed.  Returns the written path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(
            inventory,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )
    logger.info("Wrote inventory to %s", output_path)
    return output_path


def load_inventory(path: Path) -> dict[str, Any]:
    """Load a previously generated inventory from YAML.

    Raises:
        FileNotFoundError: If the path does not exist.
        yaml.YAMLError: If the file is not valid YAML.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Inventory file {path} does not contain a YAML mapping")
    return data


@dataclass
class InventoryCheckReport:
    """Result of a deterministic inventory freshness check (DD-047).

    Each list holds the inventory key (filename without the ``-inventory.yaml``
    suffix, e.g. ``bsp-party``); *orphan* holds full inventory file names.
    """

    missing: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    orphan: list[str] = field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        """True when a missing or stale inventory was found (hard failure)."""
        return bool(self.missing or self.stale)

    @property
    def has_warnings(self) -> bool:
        """True when an unverifiable (no stored hash) or orphan inventory exists."""
        return bool(self.unverifiable or self.orphan)


def _source_has_classes(ttl_path: Path, *, include_specializations: bool) -> bool:
    """Return True if a source TTL yields at least one class (mirrors generate-inventory)."""
    try:
        parsed = parse_reference_model(
            ttl_path, include_specializations=include_specializations
        )
        return bool(parsed["classes"])
    except Exception:
        # If it cannot be parsed at all we cannot judge — treat as having classes
        # so the check surfaces it rather than silently skipping.
        return True


def check_inventories(
    *,
    ontology_dir: Path | None,
    ref_models_dir: Path | None,
    inventory_dir: Path,
) -> InventoryCheckReport:
    """Deterministically verify that ``referencemodels-unpacked/`` is present and fresh (DD-047).

    For every source TTL under *ontology_dir* / *ref_models_dir* that would yield
    classes, checks that a matching inventory file (named via
    :func:`inventory_filename`, e.g. ``bsp-party-inventory.yaml``) exists and that
    its stored ``source_sha256`` matches the current file content.

    Classification:
      - **missing**  — source has classes but no inventory file → blocking.
      - **stale**    — inventory exists but its stored hash differs → blocking.
      - **unverifiable** — inventory exists but has no stored hash (pre-DD-047) → warn.
      - **ok**       — inventory exists and hash matches.
      - **orphan**   — inventory file with no corresponding source TTL → warn.
    """
    report = InventoryCheckReport()
    seen_files: set[str] = set()

    sources: list[tuple[Path, bool]] = []
    if ref_models_dir and ref_models_dir.is_dir():
        sources += [(p, True) for p in iter_reference_inventory_sources(ref_models_dir)]
    if ontology_dir and ontology_dir.is_dir():
        sources += [(p, False) for p in sorted(ontology_dir.glob("**/*.ttl"))]

    for ttl_file, include_specializations in sources:
        fname = inventory_filename(
            ttl_file,
            ref_models_dir=ref_models_dir if include_specializations else None,
        )
        key = fname[: -len("-inventory.yaml")]
        yaml_path = inventory_dir / fname
        seen_files.add(fname)

        if not yaml_path.exists():
            if _source_has_classes(
                ttl_file, include_specializations=include_specializations
            ):
                report.missing.append(key)
            continue

        try:
            inv = load_inventory(yaml_path)
        except Exception:
            report.stale.append(key)
            continue

        stored = inv.get("source_sha256")
        if not stored:
            report.unverifiable.append(key)
            continue

        if stored != compute_source_hash(ttl_file):
            report.stale.append(key)
        else:
            report.ok.append(key)

    if inventory_dir.is_dir():
        for inv_file in sorted(inventory_dir.glob("*-inventory.yaml")):
            if inv_file.name not in seen_files:
                report.orphan.append(inv_file.name)

    return report


@dataclass
class DomainScope:
    """Domain-scoped inventory readiness (toolkit-optimizations F5).

    Built by :func:`scope_inventory_report` from a repository-wide
    :class:`InventoryCheckReport` plus a domain→inventory-key mapping. Lets skill
    workflows report whether the *active* domain is ready separately from unrelated
    repository-wide failures.

    ``keys`` is the set of inventory keys (e.g. ``bsp-party``) owned by the selected
    domain(s). The status lists are the intersection of that set with the
    repository-wide report. ``unresolved`` holds domain import URIs the catalog
    could not resolve to a source TTL (surfaced so a scope gap is never silent).
    """

    domains: list[str] = field(default_factory=list)
    keys: set[str] = field(default_factory=set)
    missing: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        """True when an in-scope inventory is missing or stale."""
        return bool(self.missing or self.stale)


def resolve_domain_inventory_keys(
    domains: list[str],
    *,
    ref_models_dir: Path | None,
    catalog_path: Path | None,
    accelerator: str | None = None,
) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    """Map each selected data-domain to its reference-model inventory keys (F5).

    Resolves each domain's import URIs (from the accelerator ``data-domains.yaml``)
    through the catalog to concrete source TTL paths, then derives the inventory key
    via :func:`inventory_filename` (matching the keys produced by
    :func:`check_inventories`). This is the deterministic domain→inventory mapping
    the repository-wide check lacks.

    Returns ``(keys_by_domain, unresolved_by_domain)`` where the first maps each
    (case-insensitive substring-matched) domain id to its set of inventory keys, and
    the second maps it to the list of import URIs that could not be resolved.
    """
    from .analyse_sources import load_data_domains
    from .catalog_utils import CatalogResolver

    keys_by_domain: dict[str, set[str]] = {}
    unresolved_by_domain: dict[str, list[str]] = {}
    if not ref_models_dir or not ref_models_dir.is_dir():
        return keys_by_domain, unresolved_by_domain

    data_domains = load_data_domains(ref_models_dir, accelerator=accelerator)
    if not data_domains:
        return keys_by_domain, unresolved_by_domain

    resolver = CatalogResolver(catalog_path) if catalog_path else None
    lower_filter = [d.lower() for d in domains]

    for domain_id, meta in data_domains.items():
        if lower_filter and not any(f in domain_id.lower() for f in lower_filter):
            continue
        keys: set[str] = set()
        unresolved: list[str] = []
        for uri in meta.get("uris", []) or []:
            ttl = resolver.resolve(uri) if resolver else None
            if ttl is None:
                unresolved.append(uri)
                continue
            keys.add(
                inventory_filename(Path(ttl), ref_models_dir=ref_models_dir)[
                    : -len("-inventory.yaml")
                ]
            )
        keys_by_domain[domain_id] = keys
        if unresolved:
            unresolved_by_domain[domain_id] = unresolved

    return keys_by_domain, unresolved_by_domain


def scope_inventory_report(
    report: InventoryCheckReport,
    keys_by_domain: dict[str, set[str]],
    unresolved_by_domain: dict[str, list[str]] | None = None,
) -> DomainScope:
    """Intersect a repository-wide report with the selected domains' inventory keys.

    The repository-wide *report* is unchanged (still surfaces global failures); this
    projects it onto the active domains so a skill workflow can decide readiness
    without being blocked by unrelated missing/stale inventories (F5).
    """
    scope = DomainScope(domains=sorted(keys_by_domain))
    for keys in keys_by_domain.values():
        scope.keys |= keys
    scope.missing = sorted(k for k in report.missing if k in scope.keys)
    scope.stale = sorted(k for k in report.stale if k in scope.keys)
    scope.unverifiable = sorted(k for k in report.unverifiable if k in scope.keys)
    scope.ok = sorted(k for k in report.ok if k in scope.keys)
    if unresolved_by_domain:
        merged: list[str] = []
        for uris in unresolved_by_domain.values():
            merged.extend(uris)
        scope.unresolved = sorted(set(merged))
    return scope
