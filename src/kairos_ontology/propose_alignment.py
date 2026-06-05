# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""LLM-powered source-column → reference-model-property alignment.

Pre-modeling step that produces per-domain alignment proposals showing how
source columns map to reference model classes and properties. Consumes
affinity reports from ``analyse-sources`` and produces machine-readable YAML
that the modeling skill uses to pre-populate the Source Evidence Table.

Requires an AI provider configuration (GITHUB_TOKEN or AZURE_AI_ENDPOINT).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .analyse_sources import (
    DEFAULT_MODEL,
    parse_source_vocabulary,
    parse_reference_model,
)
from .ai_provider import get_ai_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_COLUMNS_PER_PROMPT = 80
MAX_REF_PROPERTIES_PER_PROMPT = 60

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ColumnAlignment:
    """Alignment result for a single source column."""
    column: str
    data_type: str
    ref_class: str
    ref_property: str
    alignment: str  # exact | semantic | partial | custom
    confidence: float
    rationale: str = ""


@dataclass
class TableAlignment:
    """Alignment result for a single source table."""
    system: str
    table: str
    ref_class: str
    ref_class_confidence: float
    columns: list[ColumnAlignment] = field(default_factory=list)
    custom_columns: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DomainAlignment:
    """Complete alignment result for one data domain."""
    domain: str
    domain_uris: list[str]
    generated_at: str
    model_used: str
    tables: list[TableAlignment] = field(default_factory=list)
    reference_rollup: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Affinity report reading
# ---------------------------------------------------------------------------


def load_affinity_reports(
    analysis_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Load affinity reports and group tables by primary domain.

    Returns dict: domain_id → list of table dicts (each with system, table,
    columns count, likely_entity, indicative_columns, domain_uris).
    """
    domain_tables: dict[str, list[dict[str, Any]]] = {}

    for affinity_file in sorted(analysis_dir.glob("*-affinity.yaml")):
        try:
            with open(affinity_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.warning("Could not read affinity file %s: %s", affinity_file, e)
            continue

        if not isinstance(data, dict) or data.get("schema_version") != 2:
            logger.debug("Skipping %s (not schema_version 2)", affinity_file.name)
            continue

        system = data.get("system", affinity_file.stem.replace("-affinity", ""))
        for tbl in data.get("tables", []):
            domain = tbl.get("domain", "")
            if not domain:
                continue
            domain_tables.setdefault(domain, []).append({
                "system": system,
                "table": tbl["table"],
                "total_columns": tbl.get("total_columns", 0),
                "likely_entity": tbl.get("likely_entity", ""),
                "indicative_columns": tbl.get("indicative_columns", []),
                "domain_uris": tbl.get("domain_uris", []),
            })

    return domain_tables


# ---------------------------------------------------------------------------
# Reference model property extraction (richer than _resolve_module_classes)
# ---------------------------------------------------------------------------


def extract_ref_model_inventory(
    domain_uris: list[str],
    catalog_path: Path | None,
) -> list[dict[str, Any]]:
    """Resolve domain URIs and extract full class+property inventory.

    Returns list of class dicts with:
    {name, uri, label, comment, properties: [{name, uri, label, range, range_label,
     prop_type, comment}]}
    """
    if not catalog_path or not catalog_path.exists():
        return []

    try:
        from kairos_ontology.catalog_utils import CatalogResolver
        resolver = CatalogResolver(catalog_path)
    except Exception as e:
        logger.warning("Catalog load failed (%s); skipping ref-model extraction", e)
        return []

    all_classes: list[dict[str, Any]] = []
    seen_classes: set[str] = set()

    for uri in domain_uris:
        try:
            path = resolver.resolve(uri)
        except Exception:
            continue
        if not path or not Path(path).exists():
            continue

        ref = parse_reference_model(Path(path))
        for cls in ref.get("classes", []):
            cls_name = cls.get("name", "")
            if cls_name in seen_classes:
                continue
            seen_classes.add(cls_name)

            # Enrich properties with full metadata from the parsed graph
            props = []
            for p in cls.get("properties", []):
                props.append({
                    "name": p.get("name", ""),
                    "label": p.get("label", ""),
                    "range": p.get("range", ""),
                    "comment": "",
                })

            all_classes.append({
                "name": cls_name,
                "label": cls.get("label", cls_name),
                "comment": cls.get("comment", ""),
                "properties": props,
            })

    return all_classes


# ---------------------------------------------------------------------------
# LLM prompt and alignment
# ---------------------------------------------------------------------------


def _format_ref_inventory(ref_classes: list[dict[str, Any]]) -> str:
    """Format reference model inventory for the LLM prompt."""
    lines = []
    for cls in ref_classes:
        props = cls.get("properties", [])
        prop_lines = []
        for p in props[:MAX_REF_PROPERTIES_PER_PROMPT]:
            range_str = f" ({p['range']})" if p.get("range") else ""
            prop_lines.append(f"    - {p['name']} [{p['label']}]{range_str}")
        lines.append(f"  CLASS: {cls['name']} ({cls['label']})")
        if cls.get("comment"):
            lines.append(f"    Description: {cls['comment']}")
        if prop_lines:
            lines.append("    Properties:")
            lines.extend(prop_lines)
        else:
            lines.append("    Properties: (none declared)")
    return "\n".join(lines)


def _format_source_columns(columns: list[dict[str, Any]]) -> str:
    """Format source columns for the LLM prompt."""
    lines = []
    for col in columns[:MAX_COLUMNS_PER_PROMPT]:
        samples_str = ", ".join(col.get("samples", [])[:3])
        samples_part = f" | samples: {samples_str}" if samples_str else ""
        lines.append(f"  - {col['name']} ({col.get('data_type', 'unknown')}){samples_part}")
    return "\n".join(lines)


def build_alignment_prompt(
    table_name: str,
    columns: list[dict[str, Any]],
    ref_classes: list[dict[str, Any]],
    likely_entity: str = "",
) -> str:
    """Build the alignment prompt for one source table.

    Two-stage in a single call:
    1. Which reference class does this table best align to?
    2. For each column, which reference property is the best match?
    """
    entity_hint = ""
    if likely_entity:
        entity_hint = (
            f"\nHINT: Prior analysis suggests this table represents "
            f"a '{likely_entity}' entity.\n"
        )

    ref_inventory = _format_ref_inventory(ref_classes)
    source_cols = _format_source_columns(columns)

    class_names = ", ".join(c["name"] for c in ref_classes)

    return f"""Align this source database table to the reference model.

STEP 1: Determine which reference model class this table best represents.
STEP 2: For each source column, find the best matching reference model property.
{entity_hint}
SOURCE TABLE: {table_name}
COLUMNS:
{source_cols}

REFERENCE MODEL CLASSES AND PROPERTIES:
{ref_inventory}

Instructions:
- For ref_class, choose the ONE class from the reference model that best represents
  this table. Must be one of: {class_names}
- For each column, find the best matching property from ANY reference class
  (not limited to the table's primary class).
- alignment values: "exact" (same concept and name), "semantic" (same concept,
  different name), "partial" (related but not equivalent), "custom" (no match).
- Columns with no reference model match should have alignment "custom" and
  ref_property set to a suggested camelCase property name.
- ref_class_confidence: 0.0-1.0 for the table→class match.

Respond with JSON only:
{{
  "ref_class": "<class name>",
  "ref_class_confidence": 0.0-1.0,
  "column_alignments": [
    {{
      "column": "<source column name>",
      "ref_class": "<class name that owns this property>",
      "ref_property": "<property name or suggested name>",
      "alignment": "exact|semantic|partial|custom",
      "confidence": 0.0-1.0,
      "rationale": "brief explanation"
    }}
  ]
}}"""


def align_table(
    client,
    model: str,
    table_name: str,
    columns: list[dict[str, Any]],
    ref_classes: list[dict[str, Any]],
    likely_entity: str = "",
) -> dict[str, Any]:
    """Run LLM alignment for one source table against reference model classes.

    Returns normalized dict with ref_class, ref_class_confidence, column_alignments.
    """
    if not ref_classes:
        return {
            "ref_class": "",
            "ref_class_confidence": 0.0,
            "column_alignments": [],
        }

    prompt = build_alignment_prompt(table_name, columns, ref_classes, likely_entity)
    valid_classes = {c["name"] for c in ref_classes}

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "You are an expert ontologist. You align source database columns "
                    "to reference model classes and properties based on semantic "
                    "meaning, not just name similarity. Always respond with valid JSON."
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.warning("LLM alignment failed for table %s: %s", table_name, e)
        result = {}

    if not isinstance(result, dict):
        result = {}

    # Validate ref_class
    ref_class = str(result.get("ref_class", "") or "")
    if ref_class not in valid_classes:
        ref_class = ""
    ref_class_confidence = _clamp_confidence(result.get("ref_class_confidence", 0.0))

    # Validate column alignments
    alignments = []
    raw_alignments = result.get("column_alignments", [])
    if not isinstance(raw_alignments, list):
        raw_alignments = []

    source_col_names = {c["name"] for c in columns}
    valid_alignments = {"exact", "semantic", "partial", "custom"}

    for ca in raw_alignments:
        if not isinstance(ca, dict):
            continue
        col_name = str(ca.get("column", "") or "")
        if col_name not in source_col_names:
            continue
        alignment = str(ca.get("alignment", "custom") or "custom")
        if alignment not in valid_alignments:
            alignment = "custom"
        alignments.append({
            "column": col_name,
            "ref_class": str(ca.get("ref_class", ref_class) or ref_class),
            "ref_property": str(ca.get("ref_property", "") or ""),
            "alignment": alignment,
            "confidence": _clamp_confidence(ca.get("confidence", 0.0)),
            "rationale": str(ca.get("rationale", "") or ""),
        })

    return {
        "ref_class": ref_class,
        "ref_class_confidence": ref_class_confidence,
        "column_alignments": alignments,
    }


def _clamp_confidence(val: Any) -> float:
    """Clamp a value to [0.0, 1.0] float."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_propose_alignment(
    analysis_dir: Path,
    sources_dir: Path,
    catalog_path: Path | None,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    domains_filter: list[str] | None = None,
    report=None,
) -> list[Path]:
    """Run alignment for all domains found in affinity reports.

    Args:
        analysis_dir: Directory containing *-affinity.yaml files.
        sources_dir: Directory containing source system subdirs with *.vocabulary.ttl.
        catalog_path: Path to the hub's catalog-v001.xml.
        output_dir: Where to write *-alignment.yaml files.
        model: LLM model name.
        domains_filter: Optional list of domain ids to include.
        report: Progress reporter callable.

    Returns list of written output file paths.
    """
    if report is None:
        report = lambda msg, **kw: None  # noqa: E731

    # Load and group by domain
    domain_tables = load_affinity_reports(analysis_dir)
    if not domain_tables:
        raise ValueError(
            f"No affinity reports found in {analysis_dir}. "
            "Run 'kairos-ontology analyse-sources' first."
        )

    # Apply domain filter
    if domains_filter:
        lower_filter = [d.lower() for d in domains_filter]
        domain_tables = {
            k: v for k, v in domain_tables.items()
            if any(f in k.lower() for f in lower_filter)
        }
        if not domain_tables:
            raise ValueError(
                f"No domains matched filter: {domains_filter}. "
                f"Available: {list(load_affinity_reports(analysis_dir).keys())}"
            )

    # Build source vocab cache: system → vocab_path
    vocab_cache: dict[str, Path] = {}
    if sources_dir.is_dir():
        for vocab_file in sources_dir.rglob("*.vocabulary.ttl"):
            sys_name = vocab_file.stem.replace(".vocabulary", "")
            vocab_cache[sys_name] = vocab_file

    # Parse source vocabularies (cached)
    parsed_vocabs: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def get_columns(system: str, table: str) -> list[dict[str, Any]]:
        if system not in parsed_vocabs:
            vocab_path = vocab_cache.get(system)
            if vocab_path and vocab_path.exists():
                parsed_vocabs[system] = parse_source_vocabulary(vocab_path)
            else:
                parsed_vocabs[system] = {}
        return parsed_vocabs[system].get(table, [])

    # Create LLM client lazily (after validation)
    client = get_ai_client()

    output_files: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for domain_id, tables in sorted(domain_tables.items()):
        report(f"  📐 Domain: {domain_id} ({len(tables)} table(s))")

        # Get domain URIs from first table entry
        domain_uris = tables[0].get("domain_uris", []) if tables else []

        # Resolve reference model inventory
        ref_classes = extract_ref_model_inventory(domain_uris, catalog_path)
        if ref_classes:
            report(
                f"     Ref model: {len(ref_classes)} class(es), "
                f"{sum(len(c.get('properties', [])) for c in ref_classes)} properties"
            )
        else:
            report(f"     ⚠ No reference model resolved for {domain_uris}")

        alignment = DomainAlignment(
            domain=domain_id,
            domain_uris=domain_uris,
            generated_at=datetime.now(timezone.utc).isoformat(),
            model_used=model,
        )

        for tbl_info in tables:
            system = tbl_info["system"]
            table = tbl_info["table"]
            columns = get_columns(system, table)
            if not columns:
                report(f"     ⚠ No columns found for {system}.{table}", level="verbose")
                continue

            result = align_table(
                client, model, table, columns, ref_classes,
                likely_entity=tbl_info.get("likely_entity", ""),
            )

            # Build TableAlignment
            col_alignments = []
            custom_cols = []
            for ca in result.get("column_alignments", []):
                col_data_type = next(
                    (c["data_type"] for c in columns if c["name"] == ca["column"]),
                    "unknown",
                )
                if ca["alignment"] == "custom":
                    custom_cols.append({
                        "column": ca["column"],
                        "data_type": col_data_type,
                        "suggested_property": ca["ref_property"],
                        "rationale": ca.get("rationale", ""),
                    })
                else:
                    col_alignments.append(ColumnAlignment(
                        column=ca["column"],
                        data_type=col_data_type,
                        ref_class=ca.get("ref_class", result.get("ref_class", "")),
                        ref_property=ca["ref_property"],
                        alignment=ca["alignment"],
                        confidence=ca["confidence"],
                        rationale=ca.get("rationale", ""),
                    ))

            ta = TableAlignment(
                system=system,
                table=table,
                ref_class=result.get("ref_class", ""),
                ref_class_confidence=result.get("ref_class_confidence", 0.0),
                columns=col_alignments,
                custom_columns=custom_cols,
            )
            alignment.tables.append(ta)

            matched = len(col_alignments)
            custom = len(custom_cols)
            report(
                f"     ├─ {system}.{table} → {ta.ref_class} "
                f"({matched} matched, {custom} custom)",
                level="verbose",
            )

        # Build reference rollup
        alignment.reference_rollup = _build_reference_rollup(alignment, ref_classes)

        # Write output
        out_path = write_alignment_output(alignment, output_dir)
        output_files.append(out_path)
        report(f"     ✓ Written: {out_path.name}")

    return output_files


# ---------------------------------------------------------------------------
# Reference rollup builder
# ---------------------------------------------------------------------------


def _build_reference_rollup(
    alignment: DomainAlignment,
    ref_classes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a reference-class-centric rollup from table-centric alignments."""
    class_data: dict[str, dict[str, Any]] = {}

    # Initialize from reference model
    for cls in ref_classes:
        cls_name = cls["name"]
        ref_props = {p["name"] for p in cls.get("properties", [])}
        class_data[cls_name] = {
            "ref_class": cls_name,
            "ref_label": cls.get("label", cls_name),
            "ref_properties_total": len(ref_props),
            "matched_properties": set(),
            "source_tables": [],
            "custom_extensions": [],
        }

    # Populate from alignments
    for ta in alignment.tables:
        # Track which tables feed each class
        primary_cls = ta.ref_class
        if primary_cls and primary_cls in class_data:
            class_data[primary_cls]["source_tables"].append(
                f"{ta.system}.{ta.table}"
            )

        for ca in ta.columns:
            cls_name = ca.ref_class or primary_cls
            if cls_name in class_data:
                class_data[cls_name]["matched_properties"].add(ca.ref_property)

        for cc in ta.custom_columns:
            if primary_cls and primary_cls in class_data:
                class_data[primary_cls]["custom_extensions"].append({
                    "column": cc["column"],
                    "suggested_property": cc.get("suggested_property", ""),
                    "source": f"{ta.system}.{ta.table}",
                })

    # Convert to serializable list
    rollup = []
    for cls_name, data in class_data.items():
        matched = data["matched_properties"]
        total = data["ref_properties_total"]
        coverage = round(len(matched) / total * 100, 1) if total else 0.0
        rollup.append({
            "ref_class": cls_name,
            "ref_label": data["ref_label"],
            "ref_properties_total": total,
            "matched_properties": len(matched),
            "coverage_pct": coverage,
            "source_tables": data["source_tables"],
            "custom_extensions_count": len(data["custom_extensions"]),
        })

    return sorted(rollup, key=lambda r: r["coverage_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def write_alignment_output(alignment: DomainAlignment, output_dir: Path) -> Path:
    """Write domain alignment results to YAML."""
    output_dir.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "schema_version": 1,
        "domain": alignment.domain,
        "domain_uris": alignment.domain_uris,
        "generated_at": alignment.generated_at,
        "model_used": alignment.model_used,
        "tables": [],
        "reference_rollup": alignment.reference_rollup,
    }

    for ta in alignment.tables:
        table_dict: dict[str, Any] = {
            "system": ta.system,
            "table": ta.table,
            "ref_class": ta.ref_class,
            "ref_class_confidence": ta.ref_class_confidence,
            "columns": [],
            "custom_columns": ta.custom_columns,
        }
        for ca in ta.columns:
            table_dict["columns"].append({
                "column": ca.column,
                "data_type": ca.data_type,
                "ref_class": ca.ref_class,
                "ref_property": ca.ref_property,
                "alignment": ca.alignment,
                "confidence": ca.confidence,
                "rationale": ca.rationale,
            })
        data["tables"].append(table_dict)

    output_file = output_dir / f"{alignment.domain}-alignment.yaml"
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return output_file
