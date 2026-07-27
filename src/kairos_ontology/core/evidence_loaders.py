# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic readers for advisory source, TMDL, and SKOS evidence."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, URIRef

logger = logging.getLogger(__name__)

_SKOS_MATCH_PREDICATES = {
    "http://www.w3.org/2004/02/skos/core#exactMatch": "exactMatch",
    "http://www.w3.org/2004/02/skos/core#closeMatch": "closeMatch",
    "http://www.w3.org/2004/02/skos/core#narrowMatch": "narrowMatch",
    "http://www.w3.org/2004/02/skos/core#broadMatch": "broadMatch",
    "http://www.w3.org/2004/02/skos/core#relatedMatch": "relatedMatch",
}


def load_affinity_by_domain(analysis_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Group schema-v2 affinity tables by primary domain."""
    by_domain: dict[str, list[dict[str, Any]]] = {}
    if not analysis_dir or not analysis_dir.is_dir():
        return by_domain
    for affinity_file in sorted(analysis_dir.glob("*-affinity.yaml")):
        try:
            data = yaml.safe_load(affinity_file.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not read affinity %s: %s", affinity_file, exc)
            continue
        if not isinstance(data, dict) or data.get("schema_version") != 2:
            continue
        system = data.get("system", affinity_file.stem.replace("-affinity", ""))
        for table in data.get("tables", []) or []:
            domain = str(table.get("domain", "") or "")
            if domain:
                by_domain.setdefault(domain, []).append(
                    {
                        "system": system,
                        "table": table.get("table", ""),
                        "likely_entity": table.get("likely_entity", ""),
                        "confidence": table.get("confidence"),
                    }
                )
    return by_domain


def load_tmdl_concept_mappings(tmdl_dir: Path) -> list[dict[str, Any]]:
    """Load all TMDL concept-mapping tables."""
    tables: list[dict[str, Any]] = []
    if not tmdl_dir or not tmdl_dir.is_dir():
        return tables
    for mapping_file in sorted(tmdl_dir.glob("*-concept-mapping.yaml")):
        try:
            data = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not read concept-mapping %s: %s", mapping_file, exc)
            continue
        if not isinstance(data, dict):
            continue
        model_name = str(data.get("model_name", "") or mapping_file.stem)
        for table in data.get("tables", []) or []:
            if isinstance(table, dict):
                entry = dict(table)
                entry["_model"] = model_name
                tables.append(entry)
    return tables


def _decode_bronze_subject(uri: str) -> tuple[str, str, str]:
    fragment = uri.rsplit("#", 1)
    local = fragment[1] if len(fragment) == 2 else uri.rsplit("/", 1)[-1]
    base = fragment[0] if len(fragment) == 2 else uri.rsplit("/", 1)[0]
    system = base.rstrip("/").rsplit("/", 1)[-1]
    table, _, column = local.partition("_")
    return system, table, column


def load_skos_links(mappings_dir: Path) -> list[dict[str, Any]]:
    """Parse mapping Turtle files into source-to-domain SKOS link records."""
    links: list[dict[str, Any]] = []
    if not mappings_dir or not mappings_dir.is_dir():
        return links
    for ttl in sorted(mappings_dir.glob("*.ttl")):
        graph = Graph()
        try:
            graph.parse(ttl, format="turtle")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not parse mapping %s: %s", ttl, exc)
            continue
        for predicate_uri, predicate_name in _SKOS_MATCH_PREDICATES.items():
            for subject, target_node in graph.subject_objects(URIRef(predicate_uri)):
                system, table, column = _decode_bronze_subject(str(subject))
                target_uri = str(target_node)
                target = (
                    target_uri.rsplit("#", 1)[-1]
                    if "#" in target_uri
                    else target_uri.rsplit("/", 1)[-1]
                )
                links.append(
                    {
                        "system": system,
                        "table": table,
                        "column": column,
                        "target": target,
                        "kind": "property" if column else "class",
                        "predicate": predicate_name,
                    }
                )
    return links
