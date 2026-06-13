# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Materialized YAML inventory generation for ontologies and reference models (DD-044).

Produces structured YAML files that capture classes, properties, and specialization
trees.  These inventories are consumed by LLM-based tools (``analyse-sources``,
``propose-alignment``) and ``coverage-report`` as a cached, designer-reviewable
alternative to re-parsing TTL files on every run.

Inventory files live in ``model/inventory/`` and are committed to git.
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

INVENTORY_VERSION = "1.0"


def compute_source_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a source TTL file's bytes."""
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


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

    Each list holds source TTL stems (or inventory file names for *orphan*).
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
    """Deterministically verify that ``model/inventory/`` is present and fresh (DD-047).

    For every source TTL under *ontology_dir* / *ref_models_dir* that would yield
    classes, checks that a matching ``{stem}-inventory.yaml`` exists and that its
    stored ``source_sha256`` matches the current file content.

    Classification:
      - **missing**  — source has classes but no inventory file → blocking.
      - **stale**    — inventory exists but its stored hash differs → blocking.
      - **unverifiable** — inventory exists but has no stored hash (pre-DD-047) → warn.
      - **ok**       — inventory exists and hash matches.
      - **orphan**   — inventory file with no corresponding source TTL → warn.
    """
    report = InventoryCheckReport()
    seen_stems: set[str] = set()

    sources: list[tuple[Path, bool]] = []
    if ref_models_dir and ref_models_dir.is_dir():
        sources += [(p, True) for p in sorted(ref_models_dir.glob("**/*.ttl"))]
    if ontology_dir and ontology_dir.is_dir():
        sources += [(p, False) for p in sorted(ontology_dir.glob("**/*.ttl"))]

    for ttl_file, include_specializations in sources:
        stem = ttl_file.stem
        yaml_path = inventory_dir / f"{stem}-inventory.yaml"
        seen_stems.add(stem)

        if not yaml_path.exists():
            if _source_has_classes(
                ttl_file, include_specializations=include_specializations
            ):
                report.missing.append(stem)
            continue

        try:
            inv = load_inventory(yaml_path)
        except Exception:
            report.stale.append(stem)
            continue

        stored = inv.get("source_sha256")
        if not stored:
            report.unverifiable.append(stem)
            continue

        if stored != compute_source_hash(ttl_file):
            report.stale.append(stem)
        else:
            report.ok.append(stem)

    if inventory_dir.is_dir():
        for inv_file in sorted(inventory_dir.glob("*-inventory.yaml")):
            stem = inv_file.name[: -len("-inventory.yaml")]
            if stem not in seen_stems:
                report.orphan.append(inv_file.name)

    return report
