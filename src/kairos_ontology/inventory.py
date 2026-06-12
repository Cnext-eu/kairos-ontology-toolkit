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

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph

from .analyse_sources import parse_reference_model

logger = logging.getLogger(__name__)

INVENTORY_VERSION = "1.0"


def generate_inventory(
    ttl_path: Path | None = None,
    *,
    graph: Graph | None = None,
    domain_name: str | None = None,
    include_specializations: bool = True,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Generate a materialized inventory from an ontology or reference model.

    Delegates to ``parse_reference_model()`` with ``include_specializations=True``
    and wraps the result in an inventory envelope with version and provenance.

    Args:
        ttl_path: Path to a TTL file (mutually exclusive with *graph*).
        graph: Pre-loaded rdflib Graph.
        domain_name: Override domain name.
        include_specializations: Walk ``subClassOf`` downward (default True).
        catalog_path: XML catalog for import resolution (currently unused —
            reserved for future catalog-aware parsing).

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
