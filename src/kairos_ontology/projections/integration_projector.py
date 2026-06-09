# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Integration mapping projector — generates target-agnostic mapping JSON.

Produces per source×entity mapping JSON files from SKOS mappings + bronze
vocabulary + silver extension annotations. These files are consumable by any
integration runtime: Dapr, n8n, Logic Apps, Data Factory, Azure Functions.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rdflib import Graph, RDFS, XSD
from rdflib.namespace import OWL, RDF

from .mapping_parser import parse_skos_mappings, KAIROS_BRONZE
from .uri_utils import extract_local_name, camel_to_snake
from .shared import KAIROS_EXT, KAIROS_INT, merge_ext_graph, str_val, int_val

logger = logging.getLogger(__name__)


def _xsd_to_simple_type(xsd_type: str) -> str:
    """Map XSD type URI to simple type name."""
    mapping = {
        str(XSD.string): "string",
        str(XSD.integer): "integer",
        str(XSD.int): "integer",
        str(XSD.long): "long",
        str(XSD.decimal): "decimal",
        str(XSD.float): "float",
        str(XSD.double): "double",
        str(XSD.boolean): "boolean",
        str(XSD.date): "date",
        str(XSD.dateTime): "dateTime",
        str(XSD.time): "time",
    }
    return mapping.get(xsd_type, "string")


def _extract_properties(graph: Graph, class_uri: str) -> list[dict[str, Any]]:
    """Extract all properties with rdfs:domain pointing to this class."""
    props = []
    from rdflib import URIRef
    for prop_uri in graph.subjects(RDFS.domain, URIRef(class_uri)):
        name = extract_local_name(str(prop_uri))
        label = str(graph.value(prop_uri, RDFS.label) or name)
        range_val = graph.value(prop_uri, RDFS.range)
        prop_type = _xsd_to_simple_type(str(range_val)) if range_val else "string"
        is_object = (prop_uri, RDF.type, OWL.ObjectProperty) in graph
        props.append({
            "name": name,
            "label": label,
            "type": prop_type,
            "is_object_property": is_object,
            "uri": str(prop_uri),
        })
    return props


def _extract_silver_metadata(
    graph: Graph, class_uri: str,
) -> dict[str, Any]:
    """Extract silver-ext annotations for a class (natural key, SCD type)."""
    from rdflib import URIRef
    cls = URIRef(class_uri)
    natural_key_raw = str_val(graph, cls, KAIROS_EXT.naturalKey)
    natural_key = natural_key_raw.split() if natural_key_raw else []
    scd_type = str_val(graph, cls, KAIROS_EXT.scdType) or "SCD1"
    return {
        "natural_key": natural_key,
        "scd_type": scd_type,
    }


def _extract_integration_metadata(
    graph: Graph, class_uri: str, ontology_uri: str | None,
) -> dict[str, Any]:
    """Extract kairos-int: annotations for a class + ontology-level defaults."""
    from rdflib import URIRef
    cls = URIRef(class_uri)

    # Ontology-level defaults
    ont_defaults: dict[str, Any] = {}
    if ontology_uri:
        ont = URIRef(ontology_uri)
        ont_defaults = {
            "default_batch_size": int_val(graph, ont, KAIROS_INT.defaultBatchSize, 1000),
            "default_error_strategy": str_val(
                graph, ont, KAIROS_INT.defaultErrorStrategy) or "skip-row",
            "default_retry_policy": str_val(
                graph, ont, KAIROS_INT.defaultRetryPolicy) or None,
            "default_schedule": str_val(
                graph, ont, KAIROS_INT.defaultSchedule) or None,
        }

    # Class-level (override ontology defaults where present)
    load_strategy = str_val(graph, cls, KAIROS_INT.loadStrategy) or "full"
    batch_raw = int_val(graph, cls, KAIROS_INT.batchSize, 0)
    error_raw = str_val(graph, cls, KAIROS_INT.errorStrategy)
    retry_raw = str_val(graph, cls, KAIROS_INT.retryPolicy)
    schedule_raw = str_val(graph, cls, KAIROS_INT.schedule)

    result: dict[str, Any] = {
        "load_strategy": load_strategy,
        "batch_size": batch_raw or ont_defaults.get("default_batch_size", 1000),
        "error_strategy": error_raw or ont_defaults.get("default_error_strategy", "skip-row"),
        "retry_policy": retry_raw or ont_defaults.get("default_retry_policy"),
        "schedule": schedule_raw or ont_defaults.get("default_schedule"),
        "priority": int_val(graph, cls, KAIROS_INT.priority, 100),
        "validation_mode": str_val(graph, cls, KAIROS_INT.validationMode) or "lenient",
    }

    watermark = str_val(graph, cls, KAIROS_INT.incrementalWatermark)
    if watermark:
        result["incremental_watermark"] = watermark

    pre_hook = str_val(graph, cls, KAIROS_INT.preLoadHook)
    if pre_hook:
        result["pre_load_hook"] = pre_hook

    post_hook = str_val(graph, cls, KAIROS_INT.postLoadHook)
    if post_hook:
        result["post_load_hook"] = post_hook

    dlt = str_val(graph, cls, KAIROS_INT.deadLetterTopic)
    if dlt:
        result["dead_letter_topic"] = dlt

    # Strip None values for cleaner JSON
    return {k: v for k, v in result.items() if v is not None}


def _extract_property_integration(
    graph: Graph, prop_uri: str,
) -> dict[str, Any]:
    """Extract kairos-int: property-level annotations."""
    from rdflib import URIRef
    prop = URIRef(prop_uri)
    result: dict[str, Any] = {}

    val_rule = str_val(graph, prop, KAIROS_INT.validationRule)
    if val_rule:
        result["validation_rule"] = val_rule

    val_action = str_val(graph, prop, KAIROS_INT.validationAction)
    if val_action:
        result["validation_action"] = val_action

    if str_val(graph, prop, KAIROS_INT.sensitiveData).lower() in ("true", "1", "yes"):
        result["sensitive_data"] = True

    lookup_entity = str_val(graph, prop, KAIROS_INT.lookupEntity)
    if lookup_entity:
        result["lookup_entity"] = lookup_entity

    lookup_key = str_val(graph, prop, KAIROS_INT.lookupKey)
    if lookup_key:
        result["lookup_key"] = lookup_key

    coercion = str_val(graph, prop, KAIROS_INT.coercionRule)
    if coercion:
        result["coercion_rule"] = coercion

    return result


def generate_integration_artifacts(
    classes: list,
    graph: Graph,
    template_dir,
    namespace: str,
    ontology_name: str = None,
    ontology_metadata: dict = None,
    sources_dir: Path = None,
    mappings_dir: Path = None,
    silver_ext_path: Path = None,
    integration_ext_path: Path = None,
    **kwargs,
) -> dict[str, str]:
    """Generate integration mapping JSON artifacts.

    Args:
        classes: List of class dicts with uri, name, label, comment.
        graph: RDFLib graph with the domain ontology.
        template_dir: Path to Jinja2 templates (unused — inline JSON generation).
        namespace: Base namespace for class filtering.
        ontology_name: Domain name (e.g., party, client).
        ontology_metadata: Provenance metadata dict.
        sources_dir: Path to integration/sources/ directory.
        mappings_dir: Path to mappings/ directory with SKOS mapping TTLs.
        silver_ext_path: Path to *-silver-ext.ttl.
        integration_ext_path: Path to *-integration-ext.ttl.

    Returns:
        Dictionary of {file_path: content} for all generated artifacts.
    """
    from kairos_ontology import __version__ as toolkit_version

    domain = ontology_name or "domain"
    artifacts: dict[str, str] = {}

    # Merge silver-ext if available
    working_graph = Graph()
    for triple in graph:
        working_graph.add(triple)
    if silver_ext_path and silver_ext_path.exists():
        working_graph = merge_ext_graph(working_graph, silver_ext_path)

    # Merge integration-ext if available
    if integration_ext_path and integration_ext_path.exists():
        working_graph = merge_ext_graph(working_graph, integration_ext_path)

    # Detect ontology URI for ontology-level defaults
    from rdflib import URIRef
    from rdflib.namespace import OWL as _OWL
    ontology_uri = None
    for s in working_graph.subjects(_RDF_TYPE := RDF.type, _OWL.Ontology):
        ns_str = str(s)
        if namespace and ns_str.startswith(namespace.rstrip("#/")):
            ontology_uri = ns_str
            break
    if not ontology_uri:
        for s in working_graph.subjects(RDF.type, _OWL.Ontology):
            ontology_uri = str(s)
            break

    # Parse SKOS mappings
    mappings, ns_bindings = parse_skos_mappings(mappings_dir)
    table_maps = mappings.get("table_maps", {})
    column_maps = mappings.get("column_maps", {})

    # Parse source vocabularies
    source_tables = _parse_all_source_vocabs(sources_dir) if sources_dir else {}

    # Build mappings per class
    manifest_entries = []

    for cls in classes:
        cls_uri = cls["uri"]
        cls_name = cls["name"]
        cls_label = cls.get("label", cls_name)

        # Find table→class mappings targeting this class
        matched_sources = []
        for src_table_uri, tmaps in table_maps.items():
            for tmap in tmaps:
                if tmap["target_uri"] == cls_uri:
                    matched_sources.append({
                        "source_uri": src_table_uri,
                        "mapping_type": tmap.get("mapping_type", "direct"),
                        "filter_condition": tmap.get("filter_condition"),
                        "dedup_key": tmap.get("dedup_key"),
                        "dedup_order": tmap.get("dedup_order"),
                    })

        if not matched_sources:
            continue

        # Get target properties
        target_props = _extract_properties(working_graph, cls_uri)
        target_prop_map = {p["uri"]: p for p in target_props}

        # Silver metadata
        silver = _extract_silver_metadata(working_graph, cls_uri)
        silver_table = f"silver_{domain}.{camel_to_snake(cls_name)}"

        # Integration metadata (kairos-int: annotations)
        integration = _extract_integration_metadata(
            working_graph, cls_uri, ontology_uri
        )

        for src_info in matched_sources:
            src_uri = src_info["source_uri"]
            src_name = extract_local_name(src_uri)
            system = _extract_system_name(src_uri, source_tables)

            # Build column mappings
            col_mappings = []
            mapped_source_cols = set()
            mapped_target_props = set()

            for src_col_uri, cmaps in column_maps.items():
                # Check if this source column belongs to this source table
                src_col_name = extract_local_name(src_col_uri)
                if not _column_belongs_to_table(
                    src_col_uri, src_uri, source_tables
                ):
                    continue

                for cmap in cmaps:
                    target_prop = target_prop_map.get(cmap["target_uri"])
                    if not target_prop:
                        continue
                    col_entry: dict[str, Any] = {
                        "source_column": src_col_name,
                        "target_property": target_prop["name"],
                        "target_type": target_prop["type"],
                        "match_type": cmap["match_type"],
                        "transform": cmap.get("transform"),
                        "source_columns": cmap.get("source_columns"),
                        "default_value": cmap.get("default_value"),
                    }
                    # Property-level integration annotations
                    prop_int = _extract_property_integration(
                        working_graph, target_prop["uri"]
                    )
                    if prop_int:
                        col_entry["integration"] = prop_int
                    col_mappings.append(col_entry)
                    mapped_source_cols.add(src_col_name)
                    mapped_target_props.add(target_prop["name"])

            # Unmapped columns
            all_source_cols = _get_source_columns(src_uri, source_tables)
            unmapped_source = [c for c in all_source_cols if c not in mapped_source_cols]
            unmapped_target = [
                p["name"] for p in target_props
                if p["name"] not in mapped_target_props and not p["is_object_property"]
            ]

            mapping_doc = {
                "$schema": "https://kairos.cnext.eu/schemas/integration-mapping/v2",
                "metadata": {
                    "domain": domain,
                    "entity": cls_name,
                    "entity_label": cls_label,
                    "ontology_iri": cls_uri,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "toolkit_version": toolkit_version,
                },
                "source": {
                    "system": system,
                    "table": src_name,
                    "uri": src_uri,
                    "mapping_type": src_info.get("mapping_type", "direct"),
                    "filter_condition": src_info.get("filter_condition"),
                    "dedup_key": src_info.get("dedup_key"),
                    "dedup_order": src_info.get("dedup_order"),
                },
                "target": {
                    "silver_table": silver_table,
                    "natural_key": silver["natural_key"],
                    "scd_type": silver["scd_type"],
                },
                "integration": integration,
                "column_mappings": col_mappings,
                "unmapped_source_columns": unmapped_source,
                "unmapped_target_properties": unmapped_target,
            }

            file_key = f"{domain}/{system}-{camel_to_snake(cls_name)}-mapping.json"
            artifacts[file_key] = json.dumps(mapping_doc, indent=2, ensure_ascii=False)

            manifest_entries.append({
                "entity": cls_name,
                "system": system,
                "table": src_name,
                "file": file_key,
                "columns_mapped": len(col_mappings),
                "columns_unmapped": len(unmapped_source),
            })

    # Generate manifest
    if manifest_entries:
        manifest = {
            "$schema": "https://kairos.cnext.eu/schemas/integration-manifest/v1",
            "domain": domain,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "toolkit_version": toolkit_version,
            "mappings": manifest_entries,
            "summary": {
                "total_entities": len({e["entity"] for e in manifest_entries}),
                "total_sources": len({e["system"] for e in manifest_entries}),
                "total_columns_mapped": sum(e["columns_mapped"] for e in manifest_entries),
                "total_columns_unmapped": sum(
                    e["columns_unmapped"] for e in manifest_entries
                ),
            },
        }
        artifacts[f"{domain}/manifest.json"] = json.dumps(
            manifest, indent=2, ensure_ascii=False
        )

    return artifacts


# ---------------------------------------------------------------------------
# Source vocabulary helpers
# ---------------------------------------------------------------------------


def _parse_all_source_vocabs(
    sources_dir: Path,
) -> dict[str, dict[str, list[str]]]:
    """Parse all source vocabulary TTLs into a lookup.

    Returns: {system_name: {table_uri: [column_names]}}
    """
    result: dict[str, dict[str, list[str]]] = {}
    if not sources_dir or not sources_dir.is_dir():
        return result

    for vocab_file in sources_dir.rglob("*.vocabulary.ttl"):
        sys_name = vocab_file.stem.replace(".vocabulary", "")
        g = Graph()
        try:
            g.parse(vocab_file, format="turtle")
        except Exception:
            continue

        tables: dict[str, list[str]] = {}
        for tbl_uri in g.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
            cols = []
            col_uris = set(g.subjects(KAIROS_BRONZE.belongsToTable, tbl_uri))
            col_uris.update(g.subjects(KAIROS_BRONZE.sourceTable, tbl_uri))
            for col_uri in col_uris:
                col_name = str(
                    g.value(col_uri, KAIROS_BRONZE.columnName)
                    or extract_local_name(str(col_uri))
                )
                cols.append(col_name)
            tables[str(tbl_uri)] = sorted(cols)

        result[sys_name] = tables
    return result


def _extract_system_name(
    source_uri: str, source_tables: dict,
) -> str:
    """Extract system name from source URI or source_tables lookup."""
    for sys_name, tables in source_tables.items():
        if source_uri in tables:
            return sys_name
    # Fallback: extract from URI
    local = extract_local_name(source_uri)
    return local.split("_")[0] if "_" in local else "source"


def _column_belongs_to_table(
    col_uri: str, table_uri: str, source_tables: dict,
) -> bool:
    """Check if a source column URI belongs to a source table.

    Uses namespace matching: column URIs in the same namespace as the table.
    """
    col_ns = col_uri.rsplit("#", 1)[0] if "#" in col_uri else col_uri.rsplit("/", 1)[0]
    tbl_ns = table_uri.rsplit("#", 1)[0] if "#" in table_uri else table_uri.rsplit("/", 1)[0]
    return col_ns == tbl_ns


def _get_source_columns(
    table_uri: str, source_tables: dict,
) -> list[str]:
    """Get column names for a source table from the vocabulary lookup."""
    for tables in source_tables.values():
        if table_uri in tables:
            return tables[table_uri]
    return []
