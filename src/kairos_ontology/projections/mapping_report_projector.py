# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Mapping Report Projector — generate HTML reports showing functional mappings.

Produces per-source-system HTML reports for business analysts showing how source
system concepts map to the domain ontology via SKOS match types.  Focuses on
semantic/business-level alignment — no dbt transforms or SQL details.
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

    Only extracts SKOS match type — ignores ``kairos-map:`` transform details
    since this report is for business-level review.

    Returns::

        {
            "table_maps": {source_table_uri: {
                "target_uri": str,
                "match_type": str,
            }},
            "column_maps": {source_col_uri: {
                "target_uri": str,
                "match_type": str,
            }}
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
                    result["table_maps"][subj_str] = {
                        "target_uri": obj_str,
                        "match_type": match_name,
                    }
                else:
                    result["column_maps"][subj_str] = {
                        "target_uri": obj_str,
                        "match_type": match_name,
                    }

    return result


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

    for table in system["tables"]:
        tbl_uri = table["uri"]
        tbl_map = mappings["table_maps"].get(tbl_uri)

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
            col_map = mappings["column_maps"].get(col_uri)
            total_columns += 1

            if col_map:
                mapped_count += 1
                total_mapped += 1
                target_prop_uri = col_map["target_uri"]
                all_mapped_properties.add(target_prop_uri)

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
            "columns": col_reports,
            "column_count": col_count,
            "mapped_count": mapped_count,
            "coverage_pct": coverage_pct,
        })

    # Reverse coverage: domain properties not covered by this source
    uncovered_properties: list[dict] = []
    for cls_uri, cls_info in ontology_classes.items():
        for prop_uri, prop_info in cls_info["properties"].items():
            if prop_uri not in all_mapped_properties:
                uncovered_properties.append({
                    "entity": cls_info["name"],
                    "property": prop_info["name"],
                    "label": prop_info["label"],
                })

    overall_pct = round(total_mapped / total_columns * 100) if total_columns > 0 else 0

    # Sort action items: errors first, then warnings, then info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    action_items.sort(key=lambda a: (severity_order.get(a["severity"], 9), a["table"]))

    return {
        "system": system,
        "tables": table_reports,
        "total_columns": total_columns,
        "total_mapped": total_mapped,
        "overall_coverage_pct": overall_pct,
        "uncovered_properties": uncovered_properties,
        "action_items": action_items,
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
