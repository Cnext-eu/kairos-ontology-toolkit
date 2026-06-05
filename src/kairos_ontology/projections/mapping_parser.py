# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared SKOS + kairos-map: mapping parser.

Extracts table-level and column-level mappings from SKOS mapping TTL files,
including ``kairos-map:`` technical annotations (transforms, filters,
deduplication keys, split/merge patterns).

Used by the dbt projector, integration projector, Dapr projector, and
n8n projector.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from rdflib import Graph, Namespace, SKOS

logger = logging.getLogger(__name__)

KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")
KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")


def parse_split_annotations(mappings_dir: Path) -> dict[tuple[str, str], dict]:
    """Pre-parse mapping TTL files by statement block to resolve split ambiguity.

    Standard RDF parsing merges all triples for the same subject, making it
    impossible to correlate which ``kairos-map:filterCondition`` belongs to which
    ``skos:exactMatch`` target when multiple split entries share a subject.

    This function parses the raw Turtle text by statement block (terminated by
    ``'.'``) so each block's annotations stay isolated.

    Returns a dict keyed by ``(subject_uri, target_uri)`` with per-entry
    annotations::

        {("bronze:tblX", "ex:ClassA"): {"filter_condition": "...", ...}, ...}
    """
    result: dict[tuple[str, str], dict] = {}
    if not mappings_dir or not mappings_dir.is_dir():
        return result

    skos_match_uris = {
        str(SKOS.exactMatch), str(SKOS.closeMatch), str(SKOS.narrowMatch),
        str(SKOS.broadMatch), str(SKOS.relatedMatch),
    }

    for ttl_path in sorted(mappings_dir.rglob("*.ttl")):
        try:
            content = ttl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Could not read mapping file %s: %s", ttl_path.name, exc)
            continue

        lines = content.split("\n")
        prefix_lines: list[str] = []
        body_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("@prefix") or stripped.startswith("@base"):
                prefix_lines.append(line)
            else:
                body_lines.append(line)

        prefix_block = "\n".join(prefix_lines) + "\n"
        body = "\n".join(body_lines)
        statements = re.split(r"\.\s*(?=\n|$)", body)

        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                block_g = Graph()
                block_g.parse(data=prefix_block + stmt + " .", format="turtle")
            except Exception as exc:
                logger.debug("Skipping unparseable mapping block in %s: %s",
                             ttl_path.name, exc)
                continue

            for subj, pred, obj in block_g:
                pred_str = str(pred)
                if pred_str not in skos_match_uris:
                    continue
                mapping_type = block_g.value(subj, KAIROS_MAP.mappingType)
                if mapping_type is None:
                    continue
                filt = block_g.value(subj, KAIROS_MAP.filterCondition)
                dedup_key = block_g.value(subj, KAIROS_MAP.deduplicationKey)
                dedup_order = block_g.value(subj, KAIROS_MAP.deduplicationOrder)
                result[(str(subj), str(obj))] = {
                    "filter_condition": str(filt) if filt else None,
                    "dedup_key": str(dedup_key) if dedup_key else None,
                    "dedup_order": str(dedup_order) if dedup_order else None,
                }

    return result


def parse_skos_mappings(mappings_dir: Path) -> tuple[dict, dict[str, str]]:
    """Parse SKOS + kairos-map: mappings and return structured mapping data.

    Returns a tuple of (mappings_dict, ns_bindings):

    mappings_dict::

        {
            "table_maps": {bronze_table_uri: [{
                "target_uri": silver_class_uri,
                "mapping_type": "direct" | "split" | "merge",
                "filter_condition": str | None,
                "dedup_key": str | None,
                "dedup_order": str | None,
            }, ...]},
            "column_maps": {bronze_col_uri: [{
                "target_uri": silver_property_uri,
                "match_type": "exactMatch" | "closeMatch" | "narrowMatch" | ...,
                "transform": str | None,
                "source_columns": [str] | None,
                "default_value": str | None,
            }, ...]}
        }

    ns_bindings: dict mapping prefix → namespace URI from the mapping files.
    """
    result: dict = {"table_maps": {}, "column_maps": {}}
    ns_bindings: dict[str, str] = {}
    if not mappings_dir or not mappings_dir.is_dir():
        return result, ns_bindings

    split_annotations = parse_split_annotations(mappings_dir)

    g = Graph()
    for ttl in sorted(mappings_dir.rglob("*.ttl")):
        try:
            g.parse(ttl, format="turtle")
        except Exception as exc:
            logger.warning("Could not parse mapping file %s: %s", ttl.name, exc)

    match_props = [
        (SKOS.exactMatch, "exactMatch"),
        (SKOS.closeMatch, "closeMatch"),
        (SKOS.narrowMatch, "narrowMatch"),
        (SKOS.broadMatch, "broadMatch"),
        (SKOS.relatedMatch, "relatedMatch"),
    ]

    for subj in set(g.subjects()):
        for skos_prop, match_name in match_props:
            for obj in g.objects(subj, skos_prop):
                subj_str = str(subj)
                obj_str = str(obj)

                mapping_type = g.value(subj, KAIROS_MAP.mappingType)
                transform = g.value(subj, KAIROS_MAP.transform)

                if mapping_type is not None:
                    annotations = split_annotations.get((subj_str, obj_str), {})
                    filt = annotations.get("filter_condition")
                    dedup_key = annotations.get("dedup_key")
                    dedup_order = annotations.get("dedup_order")

                    if filt is None:
                        v = g.value(subj, KAIROS_MAP.filterCondition)
                        filt = str(v) if v else None
                    if dedup_key is None:
                        v = g.value(subj, KAIROS_MAP.deduplicationKey)
                        dedup_key = str(v) if v else None
                    if dedup_order is None:
                        v = g.value(subj, KAIROS_MAP.deduplicationOrder)
                        dedup_order = str(v) if v else None

                    result["table_maps"].setdefault(subj_str, []).append({
                        "target_uri": obj_str,
                        "mapping_type": str(mapping_type),
                        "filter_condition": filt,
                        "dedup_key": dedup_key,
                        "dedup_order": dedup_order,
                    })
                else:
                    src_cols = g.value(subj, KAIROS_MAP.sourceColumns)
                    default = g.value(subj, KAIROS_MAP.defaultValue)
                    result["column_maps"].setdefault(subj_str, []).append({
                        "target_uri": obj_str,
                        "match_type": match_name,
                        "transform": str(transform) if transform else None,
                        "source_columns": str(src_cols).split() if src_cols else None,
                        "default_value": str(default) if default else None,
                    })

    for prefix, ns_uri in g.namespaces():
        if prefix:
            ns_bindings[prefix] = str(ns_uri)

    return result, ns_bindings
