# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic readers for advisory source, TMDL, and SKOS evidence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, URIRef

logger = logging.getLogger(__name__)

#: Where ``import-tmdl`` writes BI demand artifacts (Engineering Packs and
#: ``*-concept-mapping.yaml`` worksheets).
BI_DISCOVERY_RELPATH = Path("integration") / "discovery" / "bi"

#: Legacy pre-DD-147 location where older toolkit versions wrote the same artifacts.
LEGACY_BI_SOURCES_RELPATH = Path("integration") / "sources"

#: The ``action`` values ``import-tmdl`` offers in the worksheet header it generates
#: (``core/import_tmdl.py``). Any one of them is a recorded human decision, which is
#: what makes a row triaged -- ``skip`` and ``new_class`` included, even though neither
#: ever carries a ``reference_model_match`` (issue #687).
CONCEPT_MAPPING_ACTIONS = frozenset({"use", "specialize", "new_class", "skip"})


@dataclass(frozen=True)
class ConceptMappingScan:
    """One deterministic pass over every ``*-concept-mapping.yaml`` worksheet in a hub.

    ``tables`` pairs each table mapping with the worksheet file it came from;
    ``errors`` records unreadable worksheets as ``(path, message)``.
    Two counts, because the two consumers ask different questions (issue #687):

    * ``tables_untriaged`` — rows with no ``action`` recorded. This is the backlog:
      work a human still owes. It is what ``kairos-ontology next`` recommends on, and
      it is *reachable* — recording any of ``use | specialize | new_class | skip``
      decrements it.
    * ``tables_unfilled`` — rows with an empty ``reference_model_match``. This is the
      absence of BI weight *evidence*, which is what ``design-landscape`` reports. It
      is deliberately **not** a backlog: for ``action: skip`` (a measure-only rollup)
      and for ``action: new_class`` an empty match is the correct terminal state, so
      it legitimately never reaches zero on a fully-triaged hub.

    Conflating the two is what made ``next`` recommend ``triage-concept-mapping``
    forever on a hub where 336 of 348 rows already carried an explicit ``skip`` and a
    written rationale. Both still come from this one pass, so no two surfaces can
    disagree about either (issue #421).
    """

    tables: tuple[tuple[Path, dict[str, Any]], ...]
    errors: tuple[tuple[Path, str], ...]
    tables_total: int
    tables_unfilled: int
    directories_found: bool
    tables_untriaged: int = 0


def scan_concept_mapping_worksheets(hub_root: Path) -> ConceptMappingScan:
    """Scan a hub's TMDL concept-mapping worksheets (current and legacy locations).

    Rglobs BOTH ``integration/discovery/bi/`` (where ``import-tmdl`` writes today) and
    the legacy ``integration/sources/`` location, exactly like ``design-landscape``
    always has — the shared count must cover the same file set everywhere.
    Deliberately defensive: an unreadable worksheet is reported in ``errors`` and
    skipped, never raised.
    """
    bi_dir = hub_root / BI_DISCOVERY_RELPATH
    legacy_dir = hub_root / LEGACY_BI_SOURCES_RELPATH
    directories_found = bi_dir.is_dir() or legacy_dir.is_dir()

    mapping_files: list[Path] = []
    if bi_dir.is_dir():
        mapping_files.extend(bi_dir.rglob("*-concept-mapping.yaml"))
    if legacy_dir.is_dir():
        mapping_files.extend(legacy_dir.rglob("*-concept-mapping.yaml"))

    tables: list[tuple[Path, dict[str, Any]]] = []
    errors: list[tuple[Path, str]] = []
    unfilled = 0
    untriaged = 0
    for mapping_path in sorted(set(mapping_files)):
        try:
            document = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            errors.append((mapping_path, str(exc)))
            continue
        if not isinstance(document, dict):
            continue
        for table_dict in document.get("tables", ()) or ():
            if not isinstance(table_dict, dict):
                continue
            tables.append((mapping_path, table_dict))
            if not str(table_dict.get("reference_model_match") or "").strip():
                # Not a bug: import-tmdl leaves this blank for a human to fill in,
                # and for `skip`/`new_class` it stays blank by definition.
                unfilled += 1
            action = str(table_dict.get("action") or "").strip()
            if action not in CONCEPT_MAPPING_ACTIONS:
                # No decision recorded yet. An unrecognised value counts as untriaged
                # too: it is none of the four the worksheet template offers, so no
                # downstream consumer can act on it either.
                untriaged += 1
    return ConceptMappingScan(
        tables=tuple(tables),
        errors=tuple(errors),
        tables_total=len(tables),
        tables_unfilled=unfilled,
        directories_found=directories_found,
        tables_untriaged=untriaged,
    )

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
