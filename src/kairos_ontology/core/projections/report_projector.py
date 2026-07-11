# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Report Projector — generate BA-friendly reports for ontology and mapping review.

Produces:
- Per-source-system HTML/MD mapping reports
- Domain model overview report (classes, properties, relationships)
- Source system landscape report (inventory, coverage heatmap)
- Mapping progress dashboard (cross-source progress tracking)
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
        except (SyntaxError, ValueError) as exc:
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
        except (SyntaxError, ValueError) as exc:
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


def _calculate_coverage(
    ontology_classes: dict,
    all_mapped_properties: set[str],
    total_columns: int,
    total_mapped: int,
) -> dict:
    """Calculate reverse coverage metrics for domain properties.

    Returns a dict with uncovered_properties list, domain_coverage_pct,
    total_domain_properties, covered_domain_properties, and overall_pct.
    """
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

    return {
        "uncovered_properties": uncovered_properties,
        "domain_coverage_pct": domain_coverage_pct,
        "total_domain_properties": total_domain_properties,
        "covered_domain_properties": total_domain_properties - len(uncovered_properties),
        "overall_pct": overall_pct,
    }


def _generate_action_items(action_items: list[dict]) -> list[dict]:
    """Sort action items by severity (error > warning > info), then by table name.

    Returns a new sorted list (mutates in-place for consistency with original).
    """
    severity_order = {"error": 0, "warning": 1, "info": 2}
    action_items.sort(key=lambda a: (severity_order.get(a["severity"], 9), a["table"]))
    return action_items


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

    coverage = _calculate_coverage(
        ontology_classes, all_mapped_properties, total_columns, total_mapped
    )

    action_items = _generate_action_items(action_items)

    # Entity-centric view
    entity_view = _build_entity_view(system, mappings, ontology_classes)

    # Decisions made (tables with confirmed mappings)
    decisions: list[dict] = []
    for tbl in table_reports:
        if tbl["target_entity"]:
            decisions.append({
                "table": tbl["source_table"],
                "target": tbl["target_entity"],
                "match_label": tbl["table_match_label"],
                "mapping_type": tbl.get("table_mapping_type"),
                "filter": tbl.get("table_filter"),
            })

    # Open questions (unmapped tables/columns that need BA input)
    open_questions: list[dict] = []
    for tbl in table_reports:
        if not tbl["target_entity"]:
            open_questions.append({
                "category": "🗂️ Table",
                "question": f"Which domain entity should `{tbl['source_table']}` map to?",
                "context": f"{tbl['column_count']} columns, currently unmapped",
            })
    for tbl in table_reports:
        if tbl["target_entity"]:
            unmapped_cols = [c for c in tbl["columns"] if not c["mapped"]]
            if unmapped_cols and len(unmapped_cols) <= 10:
                for col in unmapped_cols:
                    open_questions.append({
                        "category": "📋 Column",
                        "question": (
                            f"Should `{tbl['source_table']}.{col['source_name']}` "
                            f"map to a domain property?"
                        ),
                        "context": f"Type: {col['source_type']}, table maps to {tbl['target_entity']}",
                    })
            elif unmapped_cols:
                open_questions.append({
                    "category": "📋 Columns",
                    "question": (
                        f"`{tbl['source_table']}` has {len(unmapped_cols)} unmapped columns "
                        f"— review needed"
                    ),
                    "context": f"Table maps to {tbl['target_entity']} ({tbl['coverage_pct']}% covered)",
                })

    # Suggested next actions
    next_actions: list[dict] = []
    unmapped_tables = [t for t in table_reports if not t["target_entity"]]
    if unmapped_tables:
        next_actions.append({
            "title": "Define table-level mappings",
            "description": (
                f"{len(unmapped_tables)} table(s) have no domain entity assignment. "
                f"Create SKOS mappings to assign each to a domain class."
            ),
        })
    partially_mapped = [
        t for t in table_reports
        if t["target_entity"] and t["coverage_pct"] < 80
    ]
    if partially_mapped:
        next_actions.append({
            "title": "Complete column-level mappings",
            "description": (
                f"{len(partially_mapped)} table(s) have <80% column coverage. "
                f"Review unmapped columns and add SKOS column mappings."
            ),
        })
    non_exact = [
        a for a in action_items
        if a["type"] == "review_match" and a["severity"] == "error"
    ]
    if non_exact:
        next_actions.append({
            "title": "Review non-exact matches",
            "description": (
                f"{len(non_exact)} column(s) have narrow/broad/related matches. "
                f"Confirm alignment or refine the mapping."
            ),
        })

    return {
        "system": system,
        "tables": table_reports,
        "total_columns": total_columns,
        "total_mapped": total_mapped,
        "overall_coverage_pct": coverage["overall_pct"],
        "domain_coverage_pct": coverage["domain_coverage_pct"],
        "total_domain_properties": coverage["total_domain_properties"],
        "covered_domain_properties": coverage["covered_domain_properties"],
        "match_distribution": match_distribution,
        "uncovered_properties": coverage["uncovered_properties"],
        "out_of_scope_tables": out_of_scope_tables,
        "entity_view": entity_view,
        "action_items": action_items,
        "error_count": sum(1 for a in action_items if a["severity"] == "error"),
        "warning_count": sum(1 for a in action_items if a["severity"] == "warning"),
        "info_count": sum(1 for a in action_items if a["severity"] == "info"),
        "decisions": decisions,
        "open_questions": open_questions,
        "next_actions": next_actions,
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

    env_html = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=True,
    )
    env_md = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,
    )
    html_template = env_html.get_template("report/mapping-report.html.jinja2")
    md_template = env_md.get_template("report/mapping-report.md.jinja2")

    artifacts: dict[str, str] = {}
    for system in systems:
        # Sanitize label for use as filename — strip path separators and dotdot
        slug = system["system_label"].lower().replace(" ", "-")
        slug = Path(slug).name  # robust sanitization: strip any path components
        slug = slug or "unknown-system"
        report_data = _build_report_data(system, mappings, ontology_classes or {})
        html = html_template.render(**report_data)
        artifacts[f"{slug}-mapping-report.html"] = html
        md = md_template.render(**report_data)
        artifacts[f"{slug}-mapping-report.md"] = md

    return artifacts


# =============================================================================
# Domain Model Overview Report
# =============================================================================


_REFERENCE_MODEL_LABELS = {
    "kairosflow.ai/ont/dcsa": "DCSA",
    "kairosflow.ai/ont/mmt": "MMT",
    "kairosflow.ai/ont/bsp": "BSP",
    "kairosflow.ai/ont/imo": "IMO",
    "kairosflow.ai/ont/wco": "WCO",
    "kairosflow.ai/ont/tic": "TIC",
}


def _detect_standard(uri: str) -> str:
    """Detect which reference standard a URI belongs to."""
    for pattern, label in _REFERENCE_MODEL_LABELS.items():
        if pattern in uri:
            return label
    return "Custom"


def _range_short(range_uri: str) -> str:
    """Shorten XSD/OWL range URIs to readable type names."""
    local = _extract_local_name(range_uri)
    return local if local else "string"


def generate_domain_overview_report(
    ontology_dir: Path,
    template_dir: Path,
) -> dict[str, str]:
    """Generate a domain model overview report for business analysts.

    Reads all domain ontology TTL files, extracts classes, properties,
    and relationships, then renders to Markdown with Mermaid diagrams.

    Returns:
        Dictionary of ``{filename: md_content}``.
    """
    if not ontology_dir or not ontology_dir.is_dir():
        logger.info("No ontology directory found — skipping domain overview")
        return {}

    domains: list[dict] = []
    all_glossary: list[dict] = []
    cross_domain_rels: list[dict] = []
    intra_domain_rels: list[dict] = []
    total_classes = 0
    total_data_props = 0
    total_obj_props = 0
    reference_models: set[str] = set()

    for ttl in sorted(ontology_dir.rglob("*.ttl")):
        if ttl.name.startswith("_"):
            continue

        g = Graph()
        try:
            g.parse(ttl, format="turtle")
        except (SyntaxError, ValueError) as exc:
            logger.warning("Could not parse %s: %s", ttl.name, exc)
            continue

        # Get ontology metadata
        ont_uri = None
        ont_label = ttl.parent.name.capitalize()
        ont_comment = ""
        ont_version = "0.1.0"
        imports: list[dict] = []

        for s in g.subjects(RDF.type, OWL.Ontology):
            ont_uri = str(s)
            ont_label = str(g.value(s, RDFS.label) or ont_label)
            ont_comment = str(g.value(s, RDFS.comment) or "")
            ont_version = str(g.value(s, OWL.versionInfo) or ont_version)
            for imp in g.objects(s, OWL.imports):
                imp_str = str(imp)
                standard = _detect_standard(imp_str)
                reference_models.add(standard)
                imports.append({
                    "uri": imp_str,
                    "local_name": _extract_local_name(imp_str),
                    "standard": standard,
                })
            break

        domain_ns = ont_uri + "#" if ont_uri and "#" not in ont_uri else (ont_uri or "")

        # Extract classes
        classes: list[dict] = []
        for cls_uri in g.subjects(RDF.type, OWL.Class):
            uri_str = str(cls_uri)
            if domain_ns and not uri_str.startswith(domain_ns):
                continue
            name = _extract_local_name(uri_str)
            label = str(g.value(cls_uri, RDFS.label) or name)
            comment = str(g.value(cls_uri, RDFS.comment) or "")
            # Trim multi-line comments for table display
            comment_short = comment.split("\n")[0][:120] if comment else ""

            parent = None
            for sc in g.objects(cls_uri, RDFS.subClassOf):
                parent = _extract_local_name(str(sc))
                break

            # Collect data properties for this class
            cls_data_props: list[dict] = []
            for prop_uri in g.subjects(RDFS.domain, cls_uri):
                if (prop_uri, RDF.type, OWL.DatatypeProperty) not in g:
                    continue
                pname = _extract_local_name(str(prop_uri))
                plabel = str(g.value(prop_uri, RDFS.label) or pname)
                pcomment = str(g.value(prop_uri, RDFS.comment) or "")
                pcomment_short = pcomment.split("\n")[0][:100] if pcomment else ""
                prange = str(g.value(prop_uri, RDFS.range) or "xsd:string")
                cls_data_props.append({
                    "name": pname,
                    "label": plabel,
                    "comment": pcomment_short,
                    "range": prange,
                    "range_short": _range_short(prange),
                })

            classes.append({
                "uri": uri_str,
                "name": name,
                "label": label,
                "comment": comment_short,
                "parent": parent,
                "data_properties": sorted(cls_data_props, key=lambda p: p["name"]),
            })

            all_glossary.append({
                "label": label,
                "domain": ont_label,
                "type": "Class",
                "comment": comment_short,
            })

        # Extract object properties
        domain_obj_props: list[dict] = []
        for prop_uri in g.subjects(RDF.type, OWL.ObjectProperty):
            uri_str = str(prop_uri)
            if domain_ns and not uri_str.startswith(domain_ns):
                continue
            pname = _extract_local_name(uri_str)
            domain_cls = g.value(prop_uri, RDFS.domain)
            range_cls = g.value(prop_uri, RDFS.range)
            if domain_cls and range_cls:
                domain_name = _extract_local_name(str(domain_cls))
                range_name = _extract_local_name(str(range_cls))
                rel = {
                    "name": pname,
                    "domain_class": domain_name,
                    "range_class": range_name,
                    "from_class": domain_name,
                    "to_class": range_name,
                    "property_name": pname,
                }
                domain_obj_props.append(rel)

                # Determine if cross-domain
                range_str = str(range_cls)
                if domain_ns and not range_str.startswith(domain_ns):
                    cross_domain_rels.append(rel)
                else:
                    intra_domain_rels.append(rel)

        total_classes += len(classes)
        data_prop_count = sum(len(c["data_properties"]) for c in classes)
        total_data_props += data_prop_count
        total_obj_props += len(domain_obj_props)

        domains.append({
            "uri": ont_uri,
            "label": ont_label,
            "comment": ont_comment.split("\n")[0][:200] if ont_comment else "",
            "version": ont_version,
            "imports": imports,
            "classes": sorted(classes, key=lambda c: c["name"]),
            "object_properties": domain_obj_props,
            "data_properties_count": data_prop_count,
            "object_properties_count": len(domain_obj_props),
        })

    if not domains:
        return {}

    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)
    template = env.get_template("report/domain-overview.md.jinja2")

    glossary = sorted(all_glossary, key=lambda e: e["label"])
    md = template.render(
        domains=sorted(domains, key=lambda d: d["label"]),
        total_classes=total_classes,
        total_data_properties=total_data_props,
        total_object_properties=total_obj_props,
        reference_models=list(reference_models),
        cross_domain_relationships=cross_domain_rels,
        intra_domain_relationships=intra_domain_rels,
        glossary=glossary,
    )

    return {"domain-overview.md": md}


# =============================================================================
# Source System Landscape Report
# =============================================================================


def generate_source_landscape_report(
    sources_dir: Path,
    mappings_dir: Path,
    ontology_dir: Path,
    template_dir: Path,
) -> dict[str, str]:
    """Generate a source system landscape report for business analysts.

    Reads all bronze vocabularies and summarizes the source ecosystem with
    a coverage heatmap showing which sources map to which domain.

    Returns:
        Dictionary of ``{filename: md_content}``.
    """
    if not sources_dir or not sources_dir.is_dir():
        logger.info("No sources directory found — skipping landscape report")
        return {}

    # Parse all source vocabularies
    sources: list[dict] = []
    total_tables = 0
    total_columns = 0

    all_source_g = Graph()
    for ttl in sorted(sources_dir.rglob("*.ttl")):
        try:
            all_source_g.parse(ttl, format="turtle")
        except (SyntaxError, ValueError):
            continue

    for sys_uri in all_source_g.subjects(RDF.type, KAIROS_BRONZE.SourceSystem):
        label = str(
            all_source_g.value(sys_uri, RDFS.label)
            or _extract_local_name(str(sys_uri))
        )
        db = str(all_source_g.value(sys_uri, KAIROS_BRONZE.database) or "")
        schema = str(all_source_g.value(sys_uri, KAIROS_BRONZE.schema) or "")
        conn = str(all_source_g.value(sys_uri, KAIROS_BRONZE.connectionType) or "")

        tables: list[dict] = []
        col_count = 0
        for tbl_uri in all_source_g.subjects(KAIROS_BRONZE.sourceSystem, sys_uri):
            if (tbl_uri, RDF.type, KAIROS_BRONZE.SourceTable) not in all_source_g:
                continue
            tbl_name = str(
                all_source_g.value(tbl_uri, KAIROS_BRONZE.tableName)
                or _extract_local_name(str(tbl_uri))
            )
            tbl_cols = list(
                all_source_g.subjects(KAIROS_BRONZE.sourceTable, tbl_uri)
            )
            tbl_col_count = sum(
                1 for c in tbl_cols
                if (c, RDF.type, KAIROS_BRONZE.SourceColumn) in all_source_g
            )
            col_count += tbl_col_count
            tables.append({
                "uri": str(tbl_uri),
                "name": tbl_name,
                "column_count": tbl_col_count,
                "mapped_to": None,
            })

        table_count = len(tables)
        total_tables += table_count
        total_columns += col_count

        # Complexity rating
        if col_count > 500:
            complexity = "🔴 High"
        elif col_count > 100:
            complexity = "🟡 Medium"
        else:
            complexity = "🟢 Low"

        slug = label.lower().replace(" ", "_").replace("-", "_")
        slug = "".join(c for c in slug if c.isalnum() or c == "_")

        sources.append({
            "system_uri": str(sys_uri),
            "label": label,
            "slug": slug,
            "database": db,
            "schema": schema,
            "connection_type": conn or "—",
            "table_count": table_count,
            "column_count": col_count,
            "tables": sorted(tables, key=lambda t: t["name"]),
            "complexity": complexity,
            "mapped_tables": 0,
            "mapped_columns": 0,
            "domain_coverage": {},
        })

    # Parse mappings to determine coverage
    mappings = _parse_mappings(mappings_dir) if mappings_dir else {"table_maps": {}, "column_maps": {}}

    # Get domain list
    domains: list[dict] = []
    if ontology_dir and ontology_dir.is_dir():
        for ttl in sorted(ontology_dir.rglob("*.ttl")):
            if ttl.name.startswith("_"):
                continue
            g = Graph()
            try:
                g.parse(ttl, format="turtle")
            except (SyntaxError, ValueError):
                continue
            for s in g.subjects(RDF.type, OWL.Ontology):
                label = str(g.value(s, RDFS.label) or ttl.parent.name.capitalize())
                slug = ttl.parent.name
                domains.append({"label": label, "slug": slug})
                break

    # Determine per-source domain coverage
    sources_with_table = 0
    sources_with_col = 0
    for src in sources:
        has_table_map = False
        for tbl in src["tables"]:
            tbl_maps = mappings["table_maps"].get(tbl["uri"], [])
            if tbl_maps:
                has_table_map = True
                tbl["mapped_to"] = _extract_local_name(tbl_maps[0]["target_uri"])
                src["mapped_tables"] += 1
        if has_table_map:
            sources_with_table += 1
        # Column mapping check
        for tbl in src["tables"]:
            for col_uri in all_source_g.subjects(KAIROS_BRONZE.sourceTable,
                                                  all_source_g.value(
                                                      predicate=KAIROS_BRONZE.tableName,
                                                      object=None)):
                pass  # simplified - count from mappings dict
        col_mapped = sum(
            1 for tbl in src["tables"]
            for col_uri in [str(c) for c in all_source_g.subjects(
                KAIROS_BRONZE.sourceTable,
                next((t for t in all_source_g.subjects(
                    KAIROS_BRONZE.tableName, None) if str(t) == tbl["uri"]), None)
            ) if (c, RDF.type, KAIROS_BRONZE.SourceColumn) in all_source_g]
            if col_uri in mappings["column_maps"]
        )
        if col_mapped:
            sources_with_col += 1
        src["mapped_columns"] = col_mapped

    sources_sorted = sorted(sources, key=lambda s: s["label"])

    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)
    template = env.get_template("report/source-landscape.md.jinja2")

    md = template.render(
        sources=sources_sorted,
        domains=sorted(domains, key=lambda d: d["label"]),
        total_tables=total_tables,
        total_columns=total_columns,
        sources_with_table_mappings=sources_with_table,
        sources_with_column_mappings=sources_with_col,
    )

    return {"source-landscape.md": md}


# =============================================================================
# Mapping Progress Dashboard
# =============================================================================


def generate_mapping_progress_report(
    sources_dir: Path,
    mappings_dir: Path,
    ontology_dir: Path,
    template_dir: Path,
) -> dict[str, str]:
    """Generate a mapping progress dashboard for project tracking.

    Aggregates mapping statistics across all sources and shows progress
    per source, per domain, and overall.

    Returns:
        Dictionary of ``{filename: md_content}``.
    """
    if not sources_dir or not sources_dir.is_dir():
        logger.info("No sources directory found — skipping progress report")
        return {}

    # Reuse landscape data
    all_source_g = Graph()
    for ttl in sorted(sources_dir.rglob("*.ttl")):
        try:
            all_source_g.parse(ttl, format="turtle")
        except (SyntaxError, ValueError):
            continue

    mappings = _parse_mappings(mappings_dir) if mappings_dir else {"table_maps": {}, "column_maps": {}}

    sources: list[dict] = []
    total_columns = 0
    mapped_columns = 0

    for sys_uri in all_source_g.subjects(RDF.type, KAIROS_BRONZE.SourceSystem):
        label = str(
            all_source_g.value(sys_uri, RDFS.label)
            or _extract_local_name(str(sys_uri))
        )

        tables: list[str] = []
        col_count = 0
        tbl_mapped = 0
        col_mapped = 0

        for tbl_uri in all_source_g.subjects(KAIROS_BRONZE.sourceSystem, sys_uri):
            if (tbl_uri, RDF.type, KAIROS_BRONZE.SourceTable) not in all_source_g:
                continue
            tables.append(str(tbl_uri))
            tbl_uri_str = str(tbl_uri)

            if tbl_uri_str in mappings["table_maps"]:
                tbl_mapped += 1

            for col_uri in all_source_g.subjects(KAIROS_BRONZE.sourceTable, tbl_uri):
                if (col_uri, RDF.type, KAIROS_BRONZE.SourceColumn) not in all_source_g:
                    continue
                col_count += 1
                if str(col_uri) in mappings["column_maps"]:
                    col_mapped += 1

        total_columns += col_count
        mapped_columns += col_mapped

        table_count = len(tables)
        tbl_pct = round(tbl_mapped / table_count * 100) if table_count else None
        col_pct = round(col_mapped / col_count * 100) if col_count else None

        if col_pct and col_pct >= 80:
            status = "Complete"
            status_emoji = "✅"
        elif tbl_mapped > 0 or col_mapped > 0:
            status = "In Progress"
            status_emoji = "🟡"
        else:
            status = "Not Started"
            status_emoji = "⬜"

        sources.append({
            "label": label,
            "table_count": table_count,
            "column_count": col_count,
            "table_mapping_pct": tbl_pct,
            "column_mapping_pct": col_pct,
            "status": status,
            "status_emoji": status_emoji,
        })

    sources_sorted = sorted(sources, key=lambda s: s["label"])
    unmapped = total_columns - mapped_columns
    sources_with_table = sum(1 for s in sources if s["table_mapping_pct"])
    sources_with_col = sum(1 for s in sources if s["column_mapping_pct"])

    # Domain progress
    domains: list[dict] = []
    if ontology_dir and ontology_dir.is_dir():
        for ttl in sorted(ontology_dir.rglob("*.ttl")):
            if ttl.name.startswith("_"):
                continue
            g = Graph()
            try:
                g.parse(ttl, format="turtle")
            except (SyntaxError, ValueError):
                continue
            for s in g.subjects(RDF.type, OWL.Ontology):
                dlabel = str(g.value(s, RDFS.label) or ttl.parent.name.capitalize())
                slug = ttl.parent.name
                # Count properties
                props = list(g.subjects(RDF.type, OWL.DatatypeProperty)) + \
                        list(g.subjects(RDF.type, OWL.ObjectProperty))
                domains.append({
                    "label": dlabel,
                    "slug": slug,
                    "total_properties": len(props),
                    "properties_covered": 0,
                    "sources_mapped": 0,
                    "sources_total": len(sources),
                    "coverage_pct": 0,
                })
                break

    # Priority list (sorted by column count desc — biggest systems first)
    priority_list: list[dict] = []
    for src in sorted(sources, key=lambda s: s["column_count"], reverse=True):
        if src["column_count"] > 500:
            bv = "🔴 High"
            complexity = "High"
            rec = "Break into phases; start with core tables"
        elif src["column_count"] > 100:
            bv = "🟡 Medium"
            complexity = "Medium"
            rec = "Map in one iteration"
        else:
            bv = "🟢 Low"
            complexity = "Low"
            rec = "Quick win — map all at once"
        priority_list.append({
            "label": src["label"],
            "column_count": src["column_count"],
            "business_value": bv,
            "complexity": complexity,
            "recommendation": rec,
        })

    # Suggested next actions
    not_started = [s for s in sources_sorted if s["status"] == "Not Started"]
    next_actions: list[dict] = []
    if not_started:
        # Suggest smallest not-started source first (quick win)
        smallest = min(not_started, key=lambda s: s["column_count"])
        next_actions.append({
            "title": f"Map {smallest['label']}",
            "description": f"Quick win — only {smallest['column_count']} columns. "
                           f"Start with table-level mappings.",
        })
    if len(not_started) > 1:
        largest = max(not_started, key=lambda s: s["column_count"])
        next_actions.append({
            "title": f"Plan {largest['label']} mapping",
            "description": f"Largest unmapped source ({largest['column_count']} columns). "
                           f"Identify core tables for phase 1.",
        })
    if not next_actions:
        next_actions.append({
            "title": "All sources mapped!",
            "description": "Review mapping quality and fill column-level gaps.",
        })

    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)
    template = env.get_template("report/mapping-progress.md.jinja2")

    md = template.render(
        sources=sources_sorted,
        domains=sorted(domains, key=lambda d: d["label"]),
        total_columns=total_columns,
        mapped_columns=mapped_columns,
        unmapped_columns=unmapped,
        overall_coverage_pct=round(mapped_columns / total_columns * 100) if total_columns else 0,
        sources_with_table_mappings=sources_with_table,
        sources_with_column_mappings=sources_with_col,
        table_mapping_pct=round(sources_with_table / len(sources) * 100) if sources else 0,
        column_mapping_pct=round(sources_with_col / len(sources) * 100) if sources else 0,
        priority_list=priority_list[:10],
        next_actions=next_actions,
    )

    return {"mapping-progress.md": md}

