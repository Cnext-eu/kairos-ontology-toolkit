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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .alignment_coverage import (
    ALIGNMENT_HASH_SCHEMA_VERSION,
    compute_affinity_hash,
)
from .analyse_sources import (
    DEFAULT_MODEL,
    parse_source_vocabulary,
    parse_reference_model,
)
from .ai_provider import get_ai_client
from ._concurrency import call_with_backoff, map_concurrent, DEFAULT_MAX_WORKERS
from ._cache import compute_entry_hash, open_cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_COLUMNS_PER_PROMPT = 80
MAX_REF_PROPERTIES_PER_PROMPT = 60
MAX_REF_CLASSES_PER_PROMPT = 12
RETRY_MIN_CONFIDENCE = 0.6
RETRY_MIN_MAPPED_RATIO = 0.4
MAX_SAMPLE_CHARS = 48
MAX_SAMPLES_PER_COLUMN = 3

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
    # DD-045 mapping hints (only populated when include_mapping_hints=True)
    transform_hint: str | None = None
    transform_confidence: float | None = None
    requires_human_confirmation: bool | None = None
    transform_rationale: str | None = None


@dataclass
class TableAlignment:
    """Alignment result for a single source table."""
    system: str
    table: str
    ref_class: str
    ref_class_confidence: float
    columns: list[ColumnAlignment] = field(default_factory=list)
    custom_columns: list[dict[str, Any]] = field(default_factory=list)
    # DD-045 structural mapping hints (only populated when include_mapping_hints=True)
    structural_hints: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DomainAlignment:
    """Complete alignment result for one data domain."""
    domain: str
    domain_uris: list[str]
    generated_at: str
    model_used: str
    tables: list[TableAlignment] = field(default_factory=list)
    reference_rollup: list[dict[str, Any]] = field(default_factory=list)
    #: DD-061 — SHA-256 over the affinity ``(system, table)`` set this run saw,
    #: enabling the deterministic ``check-alignment`` freshness gate.
    affinity_sha256: str | None = None


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
    *,
    inventory_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Resolve domain URIs and extract full class+property inventory.

    If *inventory_dir* contains pre-generated YAML inventories (DD-044), those
    are preferred over re-parsing TTL files.

    Returns list of class dicts with:
    {name, uri, label, comment, properties: [{name, uri, label, range, range_label,
     prop_type, comment}], specializations: [...]}
    """
    # DD-044: Try cached inventories first
    if inventory_dir and inventory_dir.is_dir():
        inv_classes = _load_inventory_classes(inventory_dir)
        if inv_classes:
            return inv_classes

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

        ref = parse_reference_model(Path(path), include_specializations=True)
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

            cls_dict: dict[str, Any] = {
                "name": cls_name,
                "label": cls.get("label", cls_name),
                "comment": cls.get("comment", ""),
                "properties": props,
            }
            if "specializations" in cls:
                cls_dict["specializations"] = cls["specializations"]
            all_classes.append(cls_dict)

    return all_classes


def _load_inventory_classes(inventory_dir: Path) -> list[dict[str, Any]]:
    """Load all classes from YAML inventory files in a directory (DD-044)."""
    from .inventory import load_inventory

    all_classes: list[dict[str, Any]] = []
    seen: set[str] = set()

    for yaml_file in sorted(inventory_dir.glob("*.yaml")):
        try:
            inv = load_inventory(yaml_file)
        except Exception as e:
            logger.warning("Failed to load inventory %s: %s", yaml_file, e)
            continue
        for cls in inv.get("classes", []):
            cls_name = cls.get("name", "")
            if cls_name in seen:
                continue
            seen.add(cls_name)
            all_classes.append(cls)

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
            prop_lines.append(f"    - {p['name']} [{p.get('label', p['name'])}]{range_str}")
        lines.append(f"  CLASS: {cls['name']} ({cls.get('label', cls['name'])})")
        if cls.get("comment"):
            lines.append(f"    Description: {cls['comment']}")
        if prop_lines:
            lines.append("    Properties:")
            lines.extend(prop_lines)
        else:
            lines.append("    Properties: (none declared)")
        # DD-044: Include specialization properties as hints
        specs = cls.get("specializations", [])
        if specs:
            lines.append("    Specializations (subclass patterns):")
            for spec in specs:
                spec_props = spec.get("properties", [])
                if spec_props:
                    spec_prop_names = ", ".join(
                        p.get("name", "") for p in spec_props[:10]
                    )
                    lines.append(
                        f"      - {spec['class']}: {spec_prop_names}"
                    )
                else:
                    lines.append(f"      - {spec['class']}: (no own properties)")
    return "\n".join(lines)


def _format_source_columns(columns: list[dict[str, Any]]) -> str:
    """Format source columns for the LLM prompt."""
    lines = []
    for col in columns[:MAX_COLUMNS_PER_PROMPT]:
        prompt_samples = _compact_prompt_samples(col.get("samples", []))
        samples_str = ", ".join(prompt_samples)
        samples_part = f" | samples: {samples_str}" if samples_str else ""
        lines.append(f"  - {col['name']} ({col.get('data_type', 'unknown')}){samples_part}")
    return "\n".join(lines)


_TOKEN_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def _clip_sample_text(value: str, max_chars: int = MAX_SAMPLE_CHARS) -> str:
    """Clip sample text to a bounded size for prompt efficiency."""
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "…"


def _is_noisy_sample(value: str) -> bool:
    """Return True for high-entropy or ID-like samples with low semantic value."""
    if not value:
        return True

    text = value.strip()
    if not text:
        return True

    if _UUID_RE.match(text):
        return True

    compact = text.replace("-", "").replace("_", "")
    if (
        len(compact) >= 16
        and any(ch.isdigit() for ch in compact)
        and all(ch in "0123456789abcdefABCDEF" for ch in compact)
    ):
        return True

    if " " in text:
        return False

    has_alpha = any(ch.isalpha() for ch in text)
    has_digit = any(ch.isdigit() for ch in text)
    if has_alpha and has_digit and len(text) >= 20:
        distinct_ratio = len(set(text)) / len(text)
        if distinct_ratio >= 0.6:
            return True

    return False


def _compact_prompt_samples(samples: list[Any]) -> list[str]:
    """Keep semantically useful, bounded sample values for prompts."""
    kept: list[str] = []
    for raw in samples:
        text = str(raw).strip()
        if _is_noisy_sample(text):
            continue
        kept.append(_clip_sample_text(text))
        if len(kept) >= MAX_SAMPLES_PER_COLUMN:
            break
    return kept


def _tokenize_text(value: str) -> set[str]:
    """Tokenize identifier/text into a lowercase token set."""
    if not value:
        return set()
    value = value.replace("_", " ").replace("-", " ")
    return {t.lower() for t in _TOKEN_RE.findall(value) if t}


def _score_ref_class(
    ref_class: dict[str, Any],
    *,
    table_tokens: set[str],
    column_tokens: set[str],
    likely_entity_tokens: set[str],
    indicative_tokens: set[str],
) -> float:
    """Compute a deterministic lexical relevance score for one ref class."""
    score = 0.0

    cls_tokens = _tokenize_text(
        f"{ref_class.get('name', '')} {ref_class.get('label', '')} {ref_class.get('comment', '')}"
    )
    score += len(cls_tokens & table_tokens) * 2.0
    score += len(cls_tokens & column_tokens) * 1.5
    score += len(cls_tokens & indicative_tokens) * 1.5
    score += len(cls_tokens & likely_entity_tokens) * 2.2

    for p in ref_class.get("properties", [])[:MAX_REF_PROPERTIES_PER_PROMPT]:
        prop_tokens = _tokenize_text(f"{p.get('name', '')} {p.get('label', '')}")
        score += len(prop_tokens & column_tokens) * 1.0
        score += len(prop_tokens & indicative_tokens) * 1.2

    return score


def _select_ref_classes_for_table(
    table_name: str,
    columns: list[dict[str, Any]],
    ref_classes: list[dict[str, Any]],
    *,
    likely_entity: str = "",
    indicative_columns: list[str] | None = None,
    max_classes: int = MAX_REF_CLASSES_PER_PROMPT,
) -> list[dict[str, Any]]:
    """Select a deterministic, high-relevance ref-class subset for one table."""
    if max_classes <= 0 or len(ref_classes) <= max_classes:
        return ref_classes

    if indicative_columns is None:
        indicative_columns = []

    table_tokens = _tokenize_text(table_name)
    column_tokens: set[str] = set()
    for col in columns:
        column_tokens.update(_tokenize_text(str(col.get("name", ""))))
        for sample in col.get("samples", [])[:2]:
            column_tokens.update(_tokenize_text(str(sample)))

    likely_entity_tokens = _tokenize_text(likely_entity)
    indicative_tokens = _tokenize_text(" ".join(indicative_columns))

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for cls in ref_classes:
        score = _score_ref_class(
            cls,
            table_tokens=table_tokens,
            column_tokens=column_tokens,
            likely_entity_tokens=likely_entity_tokens,
            indicative_tokens=indicative_tokens,
        )
        scored.append((score, str(cls.get("name", "")), cls))
    scored.sort(key=lambda x: (-x[0], x[1]))
    selected = [cls for _, _, cls in scored[:max_classes]]

    # Pin likely-entity class when present to avoid dropping high-value context.
    if likely_entity:
        likely = next(
            (c for c in ref_classes if str(c.get("name", "")).lower() == likely_entity.lower()),
            None,
        )
        if likely is not None and likely not in selected:
            selected[-1] = likely

    return selected


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
    step1 = "STEP 1: Determine which reference model class this table best represents."
    likely_match = ""
    if likely_entity:
        # CR-2: when the affinity step already derived the entity and it matches a
        # candidate class, anchor STEP 1 on it instead of re-deriving from scratch.
        likely_match = next(
            (c["name"] for c in ref_classes
             if str(c["name"]).lower() == str(likely_entity).lower()),
            "",
        )
        if likely_match:
            step1 = (
                f"STEP 1: Prior analysis indicates this table represents "
                f"'{likely_match}'. Confirm this class; only override it if it is "
                f"clearly wrong, and justify the override in the rationale."
            )
        else:
            entity_hint = (
                f"\nHINT: Prior analysis suggests this table represents "
                f"a '{likely_entity}' entity.\n"
            )

    ref_inventory = _format_ref_inventory(ref_classes)
    source_cols = _format_source_columns(columns)

    class_names = ", ".join(c["name"] for c in ref_classes)

    return f"""Align this source database table to the reference model.

{step1}
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


def _count_non_custom_alignments(result: dict[str, Any]) -> int:
    """Count mapped (non-custom) column alignments in an alignment result."""
    alignments = result.get("column_alignments", [])
    if not isinstance(alignments, list):
        return 0
    return sum(1 for a in alignments if isinstance(a, dict) and a.get("alignment") != "custom")


def _should_retry_with_full_inventory(
    result: dict[str, Any],
    total_columns: int,
    *,
    min_confidence: float = RETRY_MIN_CONFIDENCE,
    min_mapped_ratio: float = RETRY_MIN_MAPPED_RATIO,
) -> bool:
    """Decide if shortlist result is weak enough to warrant full-inventory retry."""
    ref_class = str(result.get("ref_class", "") or "")
    if not ref_class:
        return True

    confidence = _clamp_confidence(result.get("ref_class_confidence", 0.0))
    if total_columns <= 0:
        return confidence < min_confidence

    mapped = _count_non_custom_alignments(result)
    mapped_ratio = mapped / total_columns
    # Retry only when both quality signals are weak to avoid unnecessary full passes.
    return confidence < min_confidence and mapped_ratio < min_mapped_ratio


def _alignment_result_score(result: dict[str, Any], total_columns: int) -> float:
    """Compute a comparison score for two alignment outputs."""
    ref_class = str(result.get("ref_class", "") or "")
    confidence = _clamp_confidence(result.get("ref_class_confidence", 0.0))
    mapped = _count_non_custom_alignments(result)
    mapped_ratio = (mapped / total_columns) if total_columns > 0 else 0.0
    return (1.0 if ref_class else 0.0) + confidence + mapped_ratio


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
        response = call_with_backoff(lambda: client.chat.completions.create(
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
        ))
        result = json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.warning("LLM alignment failed for table %s: %s", table_name, e)
        result = {}

    if not isinstance(result, dict):
        result = {}

    # Validate ref_class
    ref_class = str(result.get("ref_class", "") or "")
    if ref_class not in valid_classes:
        # CR-2: fall back to the affinity-derived entity when it is a valid class,
        # rather than blanking it — we trust the prior analysis as a strong default.
        likely_match = next(
            (c["name"] for c in ref_classes
             if str(c["name"]).lower() == str(likely_entity).lower()),
            "",
        )
        ref_class = likely_match
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
# Mapping hints (DD-045) — deterministic, opt-in (--include-mapping-hints)
# ---------------------------------------------------------------------------
#
# Hints give the `design-mapping` skill a richer starting point WITHOUT
# authoring production SQL or committing decisions. Every non-trivial hint
# carries requires_human_confirmation=True. The SKOS predicate is deliberately
# NOT emitted — it is a trivial relabel of the existing `alignment` category the
# skill derives itself (see DD-045 "Considered and dropped").

# Normalize SQL/source/XSD types to a small set of logical types.
_LOGICAL_TYPE_MAP = {
    # strings
    "varchar": "string", "nvarchar": "string", "char": "string", "nchar": "string",
    "text": "string", "ntext": "string", "string": "string", "str": "string",
    "uuid": "string", "uniqueidentifier": "string", "guid": "string", "anyuri": "string",
    # integers
    "int": "int", "integer": "int", "bigint": "int", "smallint": "int",
    "tinyint": "int", "long": "int", "short": "int", "byte": "int",
    "nonnegativeinteger": "int", "positiveinteger": "int",
    # decimals
    "decimal": "decimal", "numeric": "decimal", "money": "decimal",
    "smallmoney": "decimal", "float": "decimal", "real": "decimal",
    "double": "decimal",
    # booleans
    "bit": "bool", "bool": "bool", "boolean": "bool",
    # dates
    "date": "date",
    # datetimes
    "datetime": "datetime", "datetime2": "datetime", "datetimeoffset": "datetime",
    "timestamp": "datetime", "smalldatetime": "datetime", "datetimestamp": "datetime",
}

# Logical type → SQL type used in CAST(...) hints.
_SQL_CAST_TYPE = {
    "string": "VARCHAR",
    "int": "INT",
    "decimal": "DECIMAL",
    "bool": "BOOLEAN",
    "date": "DATE",
    "datetime": "TIMESTAMP",
}

# Column-name tokens that suggest a discriminator (subclass-split signal).
_DISCRIMINATOR_NAMES = {
    "type", "kind", "category", "status", "classification", "subtype", "class",
}

# Column-name tokens that suggest a record-ordering column (dedup signal).
_ORDERING_TOKENS = ("modified", "updated", "changed", "created", "timestamp", "version")


def _normalize_logical_type(raw_type: Any) -> str:
    """Reduce a SQL/source/XSD type to a small logical type, or 'unknown'."""
    if not raw_type:
        return "unknown"
    t = str(raw_type).strip().lower()
    if "(" in t:  # strip precision, e.g. varchar(50) / decimal(10,2)
        t = t.split("(", 1)[0].strip()
    for sep in ("#", "/", ":"):  # reduce URI / CURIE to local name
        if sep in t:
            t = t.rsplit(sep, 1)[-1]
    return _LOGICAL_TYPE_MAP.get(t, "unknown")


def _transform_hint(
    column: dict[str, Any],
    ref_property_name: str,
    ref_property_range: str,
    source_alias: str = "source",
) -> dict[str, Any]:
    """Deterministic, non-authoritative transform suggestion for a matched column.

    Returns {transform_hint, transform_confidence, requires_human_confirmation,
    transform_rationale}. Only an exact name + same logical type passthrough may
    set requires_human_confirmation=False; everything else must be confirmed.
    """
    col_name = str(column.get("name", "") or "")
    col_type = _normalize_logical_type(column.get("data_type", ""))
    target_type = _normalize_logical_type(ref_property_range)
    ref = f"{source_alias}.{col_name}"
    name_match = bool(col_name) and col_name.lower() == str(ref_property_name or "").lower()

    if col_type != "unknown" and col_type == target_type:
        if name_match:
            return {
                "transform_hint": ref,
                "transform_confidence": 0.9,
                "requires_human_confirmation": False,
                "transform_rationale": (
                    f"Same logical type ({col_type}) and matching name; direct passthrough"
                ),
            }
        return {
            "transform_hint": ref,
            "transform_confidence": 0.7,
            "requires_human_confirmation": True,
            "transform_rationale": (
                f"Same logical type ({col_type}) but name differs from "
                f"'{ref_property_name}'; confirm passthrough"
            ),
        }

    if col_type != "unknown" and target_type != "unknown":
        sql_type = _SQL_CAST_TYPE.get(target_type, target_type.upper())
        return {
            "transform_hint": f"CAST({ref} AS {sql_type})",
            "transform_confidence": 0.6,
            "requires_human_confirmation": True,
            "transform_rationale": (
                f"Source type {col_type} differs from target range {target_type}; "
                "cast candidate — confirm encoding/semantics"
            ),
        }

    return {
        "transform_hint": ref,
        "transform_confidence": 0.3,
        "requires_human_confirmation": True,
        "transform_rationale": (
            "Type compatibility unclear; confirm transform and any normalization policy"
        ),
    }


def _distinct_samples(column: dict[str, Any]) -> set[str]:
    """Distinct stringified sample values for a column."""
    return {str(s) for s in (column.get("samples") or [])}


def _is_discriminator(column: dict[str, Any]) -> bool:
    """Heuristic: does this column look like a subclass discriminator?"""
    name = str(column.get("name", "") or "").lower()
    if name in _DISCRIMINATOR_NAMES or name.endswith("type") or name.endswith("kind"):
        return True
    distinct = _distinct_samples(column)
    logical = _normalize_logical_type(column.get("data_type", ""))
    return 2 <= len(distinct) <= 5 and logical in ("int", "string", "bool")


def _collect_sibling_subclasses(ref_classes: list[dict[str, Any]]) -> list[str]:
    """Collect distinct specialization subclass names across the reference model."""
    seen: list[str] = []
    for cls in ref_classes:
        for spec in cls.get("specializations", []):
            name = spec.get("class", "")
            if name and name not in seen:
                seen.append(name)
    return seen


def _detect_structural_hints(
    table_name: str,
    columns: list[dict[str, Any]],
    ref_classes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Lightweight detection of structural mapping candidates (all advisory).

    Emits split_candidate / dedup_candidate / multi_target_candidate hints. Each
    is a candidate only and carries requires_human_confirmation=True.
    """
    hints: list[dict[str, Any]] = []
    sibling_subclasses = _collect_sibling_subclasses(ref_classes)

    # split_candidate — discriminator column + >=2 sibling subclasses available.
    if len(sibling_subclasses) >= 2:
        for col in columns:
            if _is_discriminator(col):
                hints.append({
                    "type": "split_candidate",
                    "source_table": table_name,
                    "discriminator_column": col.get("name", ""),
                    "sampled_values": sorted(_distinct_samples(col)),
                    "target_class_candidates": list(sibling_subclasses),
                    "requires_human_confirmation": True,
                    "rationale": (
                        f"Low-cardinality discriminator '{col.get('name', '')}' with "
                        f"{len(sibling_subclasses)} sibling subclass(es) available"
                    ),
                })
                break  # one split signal per table is enough

    # dedup_candidate — an id-like natural key column + >=1 ordering column.
    id_cols = [
        c.get("name", "") for c in columns
        if str(c.get("name", "") or "").lower().endswith("id")
    ]
    ordering_cols = [
        c.get("name", "") for c in columns
        if _normalize_logical_type(c.get("data_type", "")) in ("date", "datetime")
        or any(tok in str(c.get("name", "") or "").lower() for tok in _ORDERING_TOKENS)
    ]
    if id_cols and ordering_cols:
        hints.append({
            "type": "dedup_candidate",
            "source_table": table_name,
            "natural_key_column": id_cols[0],
            "ordering_column_candidates": ordering_cols,
            "requires_human_confirmation": True,
            "rationale": (
                "Natural-key-like column with ordering column(s); confirm whether "
                "deduplication / latest-record selection is required"
            ),
        })

    # multi_target_candidate — column name matches properties in >=2 classes.
    prop_owners: dict[str, set[str]] = {}
    for cls in ref_classes:
        for p in cls.get("properties", []):
            pname = str(p.get("name", "") or "").lower()
            if pname:
                prop_owners.setdefault(pname, set()).add(cls.get("name", ""))
    for col in columns:
        cname = str(col.get("name", "") or "").lower()
        owners = prop_owners.get(cname, set())
        if len(owners) >= 2:
            hints.append({
                "type": "multi_target_candidate",
                "source_table": table_name,
                "source_column": col.get("name", ""),
                "target_class_candidates": sorted(owners),
                "requires_human_confirmation": True,
                "rationale": (
                    f"Column '{col.get('name', '')}' matches a property in "
                    f"{len(owners)} reference classes; confirm intended target(s)"
                ),
            })

    return hints


def _build_property_range_index(
    ref_classes: list[dict[str, Any]],
) -> dict[tuple[str | None, str], str]:
    """Index (class, property) → range, with a (None, property) name fallback."""
    idx: dict[tuple[str | None, str], str] = {}
    for cls in ref_classes:
        cls_name = cls.get("name", "")
        for p in cls.get("properties", []):
            pname = p.get("name", "")
            rng = p.get("range", "") or ""
            idx[(cls_name, pname)] = rng
            idx.setdefault((None, pname), rng)
        for spec in cls.get("specializations", []):
            for p in spec.get("properties", []):
                pname = p.get("name", "")
                if pname:
                    idx.setdefault((None, pname), p.get("range", "") or "")
    return idx


def _lookup_property_range(
    idx: dict[tuple[str | None, str], str],
    ref_class: str,
    ref_property: str,
) -> str:
    """Resolve a property range by (class, property) then by property name."""
    if (ref_class, ref_property) in idx:
        return idx[(ref_class, ref_property)]
    return idx.get((None, ref_property), "")


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
    include_mapping_hints: bool = False,
    max_prompt_classes: int = MAX_REF_CLASSES_PER_PROMPT,
    retry_min_confidence: float = RETRY_MIN_CONFIDENCE,
    retry_min_mapped_ratio: float = RETRY_MIN_MAPPED_RATIO,
    max_workers: int = DEFAULT_MAX_WORKERS,
    force: bool = False,
    cost_warning: bool = False,
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
        include_mapping_hints: DD-045 — when True, enrich each column with a
            deterministic transform hint and each table with structural hints.
            Default output (False) is unchanged, preserving the design-domain
            pre-modeling contract.
        max_prompt_classes: Max number of reference classes in first pass prompt.
        retry_min_confidence: Retry threshold for ref class confidence.
        retry_min_mapped_ratio: Retry threshold for mapped column ratio.
        max_workers: Max concurrent per-table LLM calls (CR-1). ``1`` reproduces
            the legacy fully-serial path exactly.
        force: When True, bypass both cache layers (domain-level ``affinity_sha256``
            skip and the per-table sidecar cache) and re-align everything.

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

    if cost_warning:
        from ._cost import print_cost_warning
        total_tables = sum(len(v) for v in domain_tables.values())
        print_cost_warning(
            command="propose-alignment",
            table_count=total_tables,
            max_workers=max_workers,
            model=model,
            force=force,
        )

    # Per-table sidecar cache (CR-5 fine-grained layer); disabled with --force.
    cache = open_cache(analysis_dir, "propose-alignment", enabled=not force)

    output_files: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for domain_id, tables in sorted(domain_tables.items()):
        report(f"  📐 Domain: {domain_id} ({len(tables)} table(s))")

        # Get domain URIs from first table entry
        domain_uris = tables[0].get("domain_uris", []) if tables else []

        affinity_hash = compute_affinity_hash((t["system"], t["table"]) for t in tables)

        # CR-5: domain-level skip — reuse an existing alignment whose freshness
        # hash already matches the current affinity set (unless --force).
        out_path = output_dir / f"{domain_id}-alignment.yaml"
        if not force and out_path.exists():
            existing_hash = _read_alignment_affinity_hash(out_path)
            if existing_hash and existing_hash == affinity_hash:
                report(f"     ⏭  Up to date (affinity unchanged) — skipped {out_path.name}")
                output_files.append(out_path)
                continue

        # Resolve reference model inventory
        ref_classes = extract_ref_model_inventory(domain_uris, catalog_path)
        if ref_classes:
            report(
                f"     Ref model: {len(ref_classes)} class(es), "
                f"{sum(len(c.get('properties', [])) for c in ref_classes)} properties"
            )
        else:
            report(f"     ⚠ No reference model resolved for {domain_uris}")

        # DD-045: property-range index for deterministic transform hints
        range_index = (
            _build_property_range_index(ref_classes) if include_mapping_hints else {}
        )

        # Stable signature of the reference model for cache-key invalidation.
        ref_signature = compute_entry_hash([
            [c.get("name", ""), [p.get("name", "") for p in c.get("properties", [])]]
            for c in ref_classes
        ])
        align_params = {
            "model": model,
            "max_prompt_classes": max_prompt_classes,
            "retry_min_confidence": retry_min_confidence,
            "retry_min_mapped_ratio": retry_min_mapped_ratio,
            "ref_signature": ref_signature,
        }

        alignment = DomainAlignment(
            domain=domain_id,
            domain_uris=domain_uris,
            generated_at=datetime.now(timezone.utc).isoformat(),
            model_used=model,
            affinity_sha256=affinity_hash,
        )

        def _process_table(tbl_info: dict[str, Any]) -> dict[str, Any] | None:
            """Compute (or reuse) the normalized alignment result for one table.

            Runs in a worker thread under ``map_concurrent``; performs only the
            LLM call (+ cache lookup) and returns plain data. The deterministic
            ``TableAlignment`` is assembled later on the main thread in input
            order so the YAML output stays diff-stable.
            """
            system = tbl_info["system"]
            table = tbl_info["table"]
            columns = get_columns(system, table)
            if not columns:
                return {"system": system, "table": table, "columns": [], "result": None}

            likely_entity = tbl_info.get("likely_entity", "")
            indicative_columns = tbl_info.get("indicative_columns", [])

            cache_key = compute_entry_hash({
                "system": system,
                "table": table,
                "likely_entity": likely_entity,
                "columns": [
                    {"name": c.get("name"), "type": c.get("data_type"),
                     "samples": c.get("samples", [])}
                    for c in columns
                ],
                "params": align_params,
            })
            cached = cache.get(cache_key)
            if cached is not None:
                return {"system": system, "table": table, "columns": columns,
                        "result": cached, "cache_key": cache_key, "from_cache": True}

            shortlist_classes = _select_ref_classes_for_table(
                table, columns, ref_classes,
                likely_entity=likely_entity,
                indicative_columns=indicative_columns,
                max_classes=max_prompt_classes,
            )
            try:
                result = align_table(
                    client, model, table, columns, shortlist_classes,
                    likely_entity=likely_entity,
                )
                if (
                    len(shortlist_classes) < len(ref_classes)
                    and _should_retry_with_full_inventory(
                        result, len(columns),
                        min_confidence=retry_min_confidence,
                        min_mapped_ratio=retry_min_mapped_ratio,
                    )
                ):
                    full_result = align_table(
                        client, model, table, columns, ref_classes,
                        likely_entity=likely_entity,
                    )
                    if _alignment_result_score(
                        full_result, len(columns)
                    ) >= _alignment_result_score(result, len(columns)):
                        result = full_result
            except Exception as exc:  # noqa: BLE001 — isolate a single table failure
                logger.warning("Alignment failed for %s.%s: %s", system, table, exc)
                result = {"ref_class": "", "ref_class_confidence": 0.0,
                          "column_alignments": []}
            return {"system": system, "table": table, "columns": columns,
                    "result": result, "cache_key": cache_key, "from_cache": False}

        processed = map_concurrent(_process_table, tables, max_workers=max_workers)

        for entry in processed:
            if entry is None:
                continue
            system = entry["system"]
            table = entry["table"]
            columns = entry["columns"]
            result = entry["result"]
            if not columns or result is None:
                report(f"     ⚠ No columns found for {system}.{table}", level="verbose")
                continue

            if not entry.get("from_cache") and entry.get("cache_key"):
                cache.put(entry["cache_key"], result)

            # Build TableAlignment (deterministic; no LLM)
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
                    ref_class_name = ca.get("ref_class", result.get("ref_class", ""))
                    col_obj = next(
                        (c for c in columns if c["name"] == ca["column"]), None
                    )
                    column_alignment = ColumnAlignment(
                        column=ca["column"],
                        data_type=col_data_type,
                        ref_class=ref_class_name,
                        ref_property=ca["ref_property"],
                        alignment=ca["alignment"],
                        confidence=ca["confidence"],
                        rationale=ca.get("rationale", ""),
                    )
                    if include_mapping_hints and col_obj is not None:
                        prop_range = _lookup_property_range(
                            range_index, ref_class_name, ca["ref_property"]
                        )
                        hint = _transform_hint(
                            col_obj, ca["ref_property"], prop_range
                        )
                        column_alignment.transform_hint = hint["transform_hint"]
                        column_alignment.transform_confidence = hint["transform_confidence"]
                        column_alignment.requires_human_confirmation = (
                            hint["requires_human_confirmation"]
                        )
                        column_alignment.transform_rationale = hint["transform_rationale"]
                    col_alignments.append(column_alignment)

            ta = TableAlignment(
                system=system,
                table=table,
                ref_class=result.get("ref_class", ""),
                ref_class_confidence=result.get("ref_class_confidence", 0.0),
                columns=col_alignments,
                custom_columns=custom_cols,
            )
            if include_mapping_hints:
                ta.structural_hints = _detect_structural_hints(
                    table, columns, ref_classes
                )
            alignment.tables.append(ta)

            matched = len(col_alignments)
            custom = len(custom_cols)
            cache_marker = " (cached)" if entry.get("from_cache") else ""
            report(
                f"     ├─ {system}.{table} → {ta.ref_class} "
                f"({matched} matched, {custom} custom){cache_marker}",
                level="verbose",
            )

        # Build reference rollup
        alignment.reference_rollup = _build_reference_rollup(alignment, ref_classes)

        # Write output
        out_path = write_alignment_output(alignment, output_dir)
        output_files.append(out_path)
        report(f"     ✓ Written: {out_path.name}")

    cache.flush()
    return output_files


def _read_alignment_affinity_hash(alignment_path: Path) -> str:
    """Return the ``affinity_sha256`` recorded in an existing alignment file."""
    try:
        data = yaml.safe_load(alignment_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("affinity_sha256", "") or "")


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
        "schema_version": ALIGNMENT_HASH_SCHEMA_VERSION,
        "domain": alignment.domain,
        "domain_uris": alignment.domain_uris,
        "generated_at": alignment.generated_at,
        "model_used": alignment.model_used,
        # DD-061: digest of the affinity (system, table) set for the freshness gate.
        "source_sha256": alignment.affinity_sha256,
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
            col_dict: dict[str, Any] = {
                "column": ca.column,
                "data_type": ca.data_type,
                "ref_class": ca.ref_class,
                "ref_property": ca.ref_property,
                "alignment": ca.alignment,
                "confidence": ca.confidence,
                "rationale": ca.rationale,
            }
            # DD-045: emit hint fields only when populated (default unchanged)
            if ca.transform_hint is not None:
                col_dict["transform_hint"] = ca.transform_hint
                col_dict["transform_confidence"] = ca.transform_confidence
                col_dict["requires_human_confirmation"] = ca.requires_human_confirmation
                col_dict["transform_rationale"] = ca.transform_rationale
            table_dict["columns"].append(col_dict)
        # DD-045: emit structural hints only when present (default unchanged)
        if ta.structural_hints:
            table_dict["structural_hints"] = ta.structural_hints
        data["tables"].append(table_dict)

    output_file = output_dir / f"{alignment.domain}-alignment.yaml"
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return output_file
