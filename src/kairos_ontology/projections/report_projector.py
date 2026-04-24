# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Mapping Report Projector — generate HTML reports showing functional mappings.

Produces per-source-system HTML reports for business analysts showing how source
system concepts map to the domain ontology via SKOS match types.  Combines a
source-centric view (table-by-table coverage) with a target-entity-centric view
(organized by domain class) and includes ``kairos-map:`` transform annotations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader
from rdflib import Graph, Namespace, RDF, RDFS, OWL

logger = logging.getLogger(__name__)

SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")

MATCH_TYPES = [
    (SKOS.exactMatch, "exactMatch"),
    (SKOS.closeMatch, "closeMatch"),
    (SKOS.narrowMatch, "narrowMatch"),
    (SKOS.broadMatch, "broadMatch"),
    (SKOS.relatedMatch, "relatedMatch"),
]

MATCH_COLORS = {
    "exactMatch": "#22c55e",
    "closeMatch": "#eab308",
    "narrowMatch": "#f97316",
    "broadMatch": "#f97316",
    "relatedMatch": "#ef4444",
}

MATCH_LABELS = {
    "exactMatch": "Exact",
    "closeMatch": "Close",
    "narrowMatch": "Narrow",
    "broadMatch": "Broad",
    "relatedMatch": "Related",
}


def _extract_local_name(uri: str) -> str:
    """Extract the fragment or last path segment from a URI."""
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rsplit("/", 1)[-1]


def _extract_domain_prefix(uri: str) -> str:
    """Extract a short domain prefix from a namespace URI.

    E.g. ``https://example.com/ont/client#prop`` → ``client``.
    """
    base = uri.rsplit("#", 1)[0] if "#" in uri else uri.rsplit("/", 1)[0]
    return base.rsplit("/", 1)[-1] if "/" in base else base


def _parse_source_systems(sources_dir: Path) -> list[dict]:
    """Parse source vocabulary TTL files and return source system metadata.

    Reuses the same ``kairos-bronze:`` scanning logic as the dbt projector.
    """
    if not sources_dir or not sources_dir.is_dir():
        return []

    g = Graph()
    for ttl in sorted(sources_dir.rglob("*.ttl")):
        try:
            g.parse(ttl, format="turtle")
        except Exception as exc:
            logger.warning("Could not parse vocabulary file %s: %s", ttl.name, exc)

    systems: list[dict] = []
    for sys_uri in g.subjects(RDF.type, KAIROS_BRONZE.SourceSystem):
        label = str(g.value(sys_uri, RDFS.label) or _extract_local_name(str(sys_uri)))
        db = str(g.value(sys_uri, KAIROS_BRONZE.database) or "")
        schema = str(g.value(sys_uri, KAIROS_BRONZE.schema) or "")
        conn = str(g.value(sys_uri, KAIROS_BRONZE.connectionType) or "")

        tables: list[dict] = []
        for tbl_uri in g.subjects(KAIROS_BRONZE.sourceSystem, sys_uri):
            if (tbl_uri, RDF.type, KAIROS_BRONZE.SourceTable) not in g:
                continue
            tbl_name = str(
                g.value(tbl_uri, KAIROS_BRONZE.tableName)
                or _extract_local_name(str(tbl_uri))
            )
            tbl_label = str(g.value(tbl_uri, RDFS.label) or tbl_name)

            columns: list[dict] = []
            for col_uri in g.subjects(KAIROS_BRONZE.sourceTable, tbl_uri):
                if (col_uri, RDF.type, KAIROS_BRONZE.SourceColumn) not in g:
                    continue
                col_name = str(
                    g.value(col_uri, KAIROS_BRONZE.columnName)
                    or _extract_local_name(str(col_uri))
                )
                col_type = str(g.value(col_uri, KAIROS_BRONZE.dataType) or "")

                columns.append({
                    "uri": str(col_uri),
                    "name": col_name,
                    "data_type": col_type,
                })

            tables.append({
                "uri": str(tbl_uri),
                "name": tbl_name,
                "label": tbl_label,
                "columns": columns,
            })

        systems.append({
            "system_uri": str(sys_uri),
            "system_label": label,
            "database": db,
            "schema": schema,
            "connection_type": conn,
            "tables": tables,
        })

    return systems


def _parse_mappings(mappings_dir: Path) -> dict:
    """Parse SKOS mappings and return functional mapping data.

    Extracts SKOS match types together with ``kairos-map:`` technical annotations
    (transform expressions, filter conditions, mapping types, etc.).

    A single source URI may map to **multiple** targets (e.g. a source table that
    splits into several domain entities).  Both ``table_maps`` and ``column_maps``
    therefore store *lists* of mapping entries per source URI.

    Returns::

        {
            "table_maps": {source_table_uri: [{
                "target_uri": str,
                "match_type": str,
                "mapping_type": str | None,
                "filter_condition": str | None,
                "dedup_key": str | None,
                "dedup_order": str | None,
            }]},
            "column_maps": {source_col_uri: [{
                "target_uri": str,
                "match_type": str,
                "transform": str | None,
                "filter_condition": str | None,
                "source_columns": str | None,
                "default_value": str | None,
            }]}
        }
    """
    result: dict = {"table_maps": {}, "column_maps": {}}
    if not mappings_dir or not mappings_dir.is_dir():
        return result

    g = Graph()
    for ttl in sorted(mappings_dir.rglob("*.ttl")):
        try:
            g.parse(ttl, format="turtle")
        except Exception as exc:
            logger.warning("Could not parse mapping file %s: %s", ttl.name, exc)

    for subj in set(g.subjects()):
        for skos_prop, match_name in MATCH_TYPES:
            for obj in g.objects(subj, skos_prop):
                subj_str = str(subj)
                obj_str = str(obj)

                mapping_type = g.value(subj, KAIROS_MAP.mappingType)
                if mapping_type is not None:
                    entry = {
                        "target_uri": obj_str,
                        "match_type": match_name,
                        "mapping_type": str(mapping_type),
                        "filter_condition": _opt_str(
                            g.value(subj, KAIROS_MAP.filterCondition)
                        ),
                        "dedup_key": _opt_str(
                            g.value(subj, KAIROS_MAP.deduplicationKey)
                        ),
                        "dedup_order": _opt_str(
                            g.value(subj, KAIROS_MAP.deduplicationOrder)
                        ),
                    }
                    result["table_maps"].setdefault(subj_str, []).append(entry)
                else:
                    entry = {
                        "target_uri": obj_str,
                        "match_type": match_name,
                        "transform": _opt_str(
                            g.value(subj, KAIROS_MAP.transform)
                        ),
                        "filter_condition": _opt_str(
                            g.value(subj, KAIROS_MAP.filterCondition)
                        ),
                        "source_columns": _opt_str(
                            g.value(subj, KAIROS_MAP.sourceColumns)
                        ),
                        "default_value": _opt_str(
                            g.value(subj, KAIROS_MAP.defaultValue)
                        ),
                    }
                    result["column_maps"].setdefault(subj_str, []).append(entry)

    return result


def _opt_str(val) -> str | None:
    """Convert an rdflib Literal/URIRef to str, or return None."""
    return str(val) if val is not None else None


def _extract_ontology_properties(graph: Graph, namespace: Optional[str]) -> dict:
    """Extract domain ontology classes and their properties.

    Returns::

        {
            class_uri: {
                "name": str,
                "label": str,
                "comment": str,
                "properties": {
                    prop_uri: {"name": str, "label": str, "comment": str}
                }
            }
        }
    """
    classes: dict = {}

    for cls_uri in graph.subjects(RDF.type, OWL.Class):
        uri_str = str(cls_uri)
        if namespace and not uri_str.startswith(namespace):
            continue

        name = _extract_local_name(uri_str)
        label = str(graph.value(cls_uri, RDFS.label) or name)
        comment = str(graph.value(cls_uri, RDFS.comment) or "")

        props: dict = {}
        for prop_uri in graph.subjects(RDFS.domain, cls_uri):
            prop_name = _extract_local_name(str(prop_uri))
            prop_label = str(graph.value(prop_uri, RDFS.label) or prop_name)
            prop_comment = str(graph.value(prop_uri, RDFS.comment) or "")
            props[str(prop_uri)] = {
                "name": prop_name,
                "label": prop_label,
                "comment": prop_comment,
            }

        classes[uri_str] = {
            "name": name,
            "label": label,
            "comment": comment,
            "properties": props,
        }

    return classes


def _build_entity_view(
    system: dict,
    mappings: dict,
    ontology_classes: dict,
) -> list[dict]:
    """Build a target-entity-centric view of the mappings.

    Groups all source table/column mappings by their **target** domain entity so
    the report can show an entity-organized view alongside the source-table view.

    Returns a list of entity dicts sorted by entity name.
    """
    entity_map: dict[str, dict] = {}

    for table in system["tables"]:
        tbl_uri = table["uri"]
        tbl_maps = mappings["table_maps"].get(tbl_uri, [])

        for tbl_map in tbl_maps:
            target_uri = tbl_map["target_uri"]
            entity = entity_map.setdefault(target_uri, {
                "uri": target_uri,
                "name": _extract_local_name(target_uri),
                "label": "",
                "comment": "",
                "domain_prefix": _extract_domain_prefix(target_uri),
                "source_tables": [],
                "column_mappings": [],
            })

            cls_info = ontology_classes.get(target_uri)
            if cls_info:
                entity["label"] = cls_info.get("label", entity["name"])
                entity["comment"] = cls_info.get("comment", "")

            entity["source_tables"].append({
                "table_name": table["name"],
                "table_label": table["label"],
                "match_type": tbl_map["match_type"],
                "match_label": MATCH_LABELS.get(tbl_map["match_type"], "?"),
                "match_color": MATCH_COLORS.get(tbl_map["match_type"], "#888"),
                "mapping_type": tbl_map.get("mapping_type"),
                "filter_condition": tbl_map.get("filter_condition"),
            })

        for col in table["columns"]:
            col_uri = col["uri"]
            col_maps = mappings["column_maps"].get(col_uri, [])

            for col_map in col_maps:
                target_prop_uri = col_map["target_uri"]
                target_entity_uri = _find_entity_for_property(
                    target_prop_uri, ontology_classes
                )
                if not target_entity_uri:
                    target_entity_uri = target_prop_uri

                entity = entity_map.setdefault(target_entity_uri, {
                    "uri": target_entity_uri,
                    "name": _extract_local_name(target_entity_uri),
                    "label": "",
                    "comment": "",
                    "domain_prefix": _extract_domain_prefix(target_entity_uri),
                    "source_tables": [],
                    "column_mappings": [],
                })

                cls_info = ontology_classes.get(target_entity_uri)
                if cls_info:
                    entity["label"] = cls_info.get("label", entity["name"])
                    entity["comment"] = cls_info.get("comment", "")

                target_prop_info = None
                if cls_info:
                    target_prop_info = cls_info["properties"].get(target_prop_uri)
                if not target_prop_info:
                    target_prop_info = {
                        "name": _extract_local_name(target_prop_uri),
                        "label": _extract_local_name(target_prop_uri),
                        "comment": "",
                    }

                entity["column_mappings"].append({
                    "source_table": table["name"],
                    "source_column": col["name"],
                    "source_type": col["data_type"],
                    "match_type": col_map["match_type"],
                    "match_label": MATCH_LABELS.get(col_map["match_type"], "?"),
                    "match_color": MATCH_COLORS.get(col_map["match_type"], "#888"),
                    "target_property": target_prop_info["name"],
                    "target_label": target_prop_info["label"],
                    "target_comment": target_prop_info["comment"],
                    "domain_prefix": _extract_domain_prefix(target_prop_uri),
                    "transform": col_map.get("transform"),
                    "filter_condition": col_map.get("filter_condition"),
                })

    entities = sorted(entity_map.values(), key=lambda e: e["name"])
    for entity in entities:
        entity["label"] = entity["label"] or entity["name"]
    return entities


def _find_entity_for_property(prop_uri: str, ontology_classes: dict) -> str | None:
    """Return the entity URI whose properties contain *prop_uri*, or None."""
    for cls_uri, cls_info in ontology_classes.items():
        if prop_uri in cls_info["properties"]:
            return cls_uri
    return None


def _build_report_data(
    system: dict,
    mappings: dict,
    ontology_classes: dict,
) -> dict:
    """Build the template context for one source system's report.

    Cross-references source tables/columns with SKOS mappings and domain
    ontology to compute coverage and action items.
    """
    table_reports: list[dict] = []
    all_mapped_properties: set[str] = set()
    total_columns = 0
    total_mapped = 0
    action_items: list[dict] = []
    match_distribution: dict[str, int] = {
        "exactMatch": 0, "closeMatch": 0, "narrowMatch": 0,
        "broadMatch": 0, "relatedMatch": 0,
    }
    out_of_scope_tables: list[dict] = []

    for table in system["tables"]:
        tbl_uri = table["uri"]
        tbl_maps = mappings["table_maps"].get(tbl_uri, [])
        tbl_map = tbl_maps[0] if tbl_maps else None

        target_class = None
        if tbl_map:
            target_uri = tbl_map["target_uri"]
            target_class = ontology_classes.get(target_uri, {
                "name": _extract_local_name(target_uri),
                "label": _extract_local_name(target_uri),
                "comment": "",
                "properties": {},
            })

        col_reports: list[dict] = []
        mapped_count = 0

        for col in table["columns"]:
            col_uri = col["uri"]
            col_maps = mappings["column_maps"].get(col_uri, [])
            col_map = col_maps[0] if col_maps else None
            total_columns += 1

            if col_map:
                mapped_count += 1
                total_mapped += 1
                target_prop_uri = col_map["target_uri"]
                all_mapped_properties.add(target_prop_uri)

                match_distribution[col_map["match_type"]] = (
                    match_distribution.get(col_map["match_type"], 0) + 1
                )

                target_prop = None
                if target_class:
                    target_prop = target_class["properties"].get(target_prop_uri)
                if not target_prop:
                    target_prop = {
                        "name": _extract_local_name(target_prop_uri),
                        "label": _extract_local_name(target_prop_uri),
                        "comment": "",
                    }

                col_reports.append({
                    "source_name": col["name"],
                    "source_type": col["data_type"],
                    "mapped": True,
                    "match_type": col_map["match_type"],
                    "match_color": MATCH_COLORS.get(col_map["match_type"], "#888"),
                    "match_label": MATCH_LABELS.get(col_map["match_type"], "?"),
                    "target_name": target_prop["name"],
                    "target_label": target_prop["label"],
                    "target_comment": target_prop["comment"],
                    "domain_prefix": _extract_domain_prefix(target_prop_uri),
                    "transform": col_map.get("transform"),
                    "filter_condition": col_map.get("filter_condition"),
                })

                if col_map["match_type"] != "exactMatch":
                    action_items.append({
                        "type": "review_match",
                        "severity": "warning" if col_map["match_type"] == "closeMatch"
                                    else "error",
                        "table": table["name"],
                        "column": col["name"],
                        "match_type": MATCH_LABELS[col_map["match_type"]],
                        "message": (
                            f"{col['name']} → {target_prop['name']}: "
                            f"{MATCH_LABELS[col_map['match_type']]} match — "
                            f"review alignment"
                        ),
                    })
            else:
                col_reports.append({
                    "source_name": col["name"],
                    "source_type": col["data_type"],
                    "mapped": False,
                    "match_type": None,
                    "match_color": "#888",
                    "match_label": "Unmapped",
                    "target_name": "",
                    "target_label": "",
                    "target_comment": "",
                    "domain_prefix": "",
                    "transform": None,
                    "filter_condition": None,
                })
                action_items.append({
                    "type": "unmapped_column",
                    "severity": "info",
                    "table": table["name"],
                    "column": col["name"],
                    "match_type": "",
                    "message": f"{table['name']}.{col['name']} — no mapping defined",
                })

        col_count = len(table["columns"])
        coverage_pct = round(mapped_count / col_count * 100) if col_count > 0 else 0

        if not tbl_map:
            has_any_col_mapping = any(
                mappings["column_maps"].get(c["uri"]) for c in table["columns"]
            )
            if not has_any_col_mapping:
                out_of_scope_tables.append({
                    "name": table["name"],
                    "label": table["label"],
                    "column_count": col_count,
                })
            action_items.append({
                "type": "unmapped_table",
                "severity": "error",
                "table": table["name"],
                "column": "",
                "match_type": "",
                "message": f"Table {table['name']} has no mapping to a domain entity",
            })

        table_reports.append({
            "source_table": table["name"],
            "source_label": table["label"],
            "target_entity": target_class["name"] if target_class else "",
            "target_label": target_class["label"] if target_class else "",
            "table_match_type": tbl_map["match_type"] if tbl_map else None,
            "table_match_color": MATCH_COLORS.get(
                tbl_map["match_type"], "#888") if tbl_map else "#888",
            "table_match_label": MATCH_LABELS.get(
                tbl_map["match_type"], "Unmapped") if tbl_map else "Unmapped",
            "table_mapping_type": tbl_map.get("mapping_type") if tbl_map else None,
            "table_filter": tbl_map.get("filter_condition") if tbl_map else None,
            "columns": col_reports,
            "column_count": col_count,
            "mapped_count": mapped_count,
            "coverage_pct": coverage_pct,
        })

    # Reverse coverage: domain properties not covered by this source
    uncovered_properties: list[dict] = []
    total_domain_properties = 0
    for cls_uri, cls_info in ontology_classes.items():
        for prop_uri, prop_info in cls_info["properties"].items():
            total_domain_properties += 1
            if prop_uri not in all_mapped_properties:
                uncovered_properties.append({
                    "entity": cls_info["name"],
                    "property": prop_info["name"],
                    "label": prop_info["label"],
                })

    domain_coverage_pct = (
        round(
            (total_domain_properties - len(uncovered_properties))
            / total_domain_properties * 100
        )
        if total_domain_properties > 0 else 0
    )

    overall_pct = round(total_mapped / total_columns * 100) if total_columns > 0 else 0

    # Sort action items: errors first, then warnings, then info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    action_items.sort(key=lambda a: (severity_order.get(a["severity"], 9), a["table"]))

    # Entity-centric view
    entity_view = _build_entity_view(system, mappings, ontology_classes)

    # Count action items by severity
    error_count = sum(1 for a in action_items if a["severity"] == "error")
    warning_count = sum(1 for a in action_items if a["severity"] == "warning")
    info_count = sum(1 for a in action_items if a["severity"] == "info")

    return {
        "system": system,
        "tables": table_reports,
        "total_columns": total_columns,
        "total_mapped": total_mapped,
        "overall_coverage_pct": overall_pct,
        "domain_coverage_pct": domain_coverage_pct,
        "total_domain_properties": total_domain_properties,
        "covered_domain_properties": total_domain_properties - len(uncovered_properties),
        "match_distribution": match_distribution,
        "uncovered_properties": uncovered_properties,
        "out_of_scope_tables": out_of_scope_tables,
        "entity_view": entity_view,
        "action_items": action_items,
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
    }


def generate_mapping_report(
    ontology_classes: dict,
    sources_dir: Path,
    mappings_dir: Path,
    template_dir: Path,
    namespace: Optional[str] = None,
    graph: Graph = None,
) -> dict[str, str]:
    """Generate HTML mapping reports for all source systems.

    Args:
        ontology_classes: Pre-extracted ontology class/property dict, or None.
        sources_dir: Path to ``integration/sources/``.
        mappings_dir: Path to ``model/mappings/``.
        template_dir: Path to templates directory (contains ``report/``).
        namespace: Ontology namespace for filtering classes.
        graph: RDFLib graph with domain ontology (used if ontology_classes empty).

    Returns:
        Dictionary of ``{filename: html_content}`` for all generated reports.
    """
    systems = _parse_source_systems(sources_dir)
    if not systems:
        logger.info("No source systems found — skipping mapping report")
        return {}

    mappings = _parse_mappings(mappings_dir)

    if not ontology_classes and graph:
        ontology_classes = _extract_ontology_properties(graph, namespace)

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=True,
    )
    template = env.get_template("report/mapping-report.html.jinja2")

    artifacts: dict[str, str] = {}
    for system in systems:
        # Sanitize label for use as filename — strip path separators and dotdot
        slug = system["system_label"].lower().replace(" ", "-")
        slug = slug.replace("/", "").replace("\\", "").replace("..", "")
        slug = slug or "unknown-system"
        report_data = _build_report_data(system, mappings, ontology_classes or {})
        html = template.render(**report_data)
        artifacts[f"{slug}-mapping-report.html"] = html

    return artifacts
