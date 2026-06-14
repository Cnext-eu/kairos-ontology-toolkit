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
#: DD-070 (issue #166) — max sibling/shared-module classes added to the STEP-2
#: property pool in cross-module mode, on top of the home table-class shortlist.
MAX_CROSS_MODULE_CLASSES = 8
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
    # DD-069 review flags (issues #167/#168) — populated only when a deterministic
    # plausibility/address rule fires; emitted only when review is True so the
    # default YAML output stays byte-identical.
    review: bool | None = None
    review_reason: str | None = None
    # DD-070 cross-module match tagging (issue #166) — populated only when a column
    # maps to a property on a sibling / shared accelerator-module class. Emitted only
    # when set, so default (home-only) output stays byte-identical.
    ref_module: str | None = None
    ref_module_uri: str | None = None
    belongs_to_domain: str | None = None
    belongs_to_domains: list[str] | None = None


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
    #: DD-070 (issue #166) — sibling/shared-module classes that source columns
    #: matched cross-domain; tells the modeler which module to import. Populated
    #: only in cross-module mode.
    cross_module_matches: list[dict[str, Any]] = field(default_factory=list)
    #: DD-070 (issue #166) — params signature (cross_module/accelerator/pool) so the
    #: freshness skip distinguishes a cross-module run from a home-only one.
    alignment_params_sha256: str | None = None
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
    module_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Resolve domain URIs and extract full class+property inventory.

    If *inventory_dir* contains pre-generated YAML inventories (DD-044), those
    are preferred over re-parsing TTL files.

    When *module_map* (``{uri: {"module", "domains"}}``) is provided (DD-070,
    cross-module mode), each class is additionally tagged with ``module``,
    ``source_uri``, ``ref_class_id`` and ``belongs_to_domains``, and dedup is keyed
    on ``ref_class_id`` (so a same-named class in a different module is preserved).
    Without it, behaviour is unchanged: name-based dedup and no module tags.

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
            if module_map is not None:
                logger.warning(
                    "Cross-module: could not resolve accelerator import URI %s", uri
                )
            continue

        module_info = (module_map or {}).get(uri, {})
        module = module_info.get("module", "")

        ref = parse_reference_model(Path(path), include_specializations=True)
        for cls in ref.get("classes", []):
            cls_name = cls.get("name", "")
            # Cross-module mode dedups on (uri, name) so a same-named class in a
            # different module is kept; home-only mode keeps historical name dedup.
            dedup_key = f"{uri}#{cls_name}" if module_map is not None else cls_name
            if dedup_key in seen_classes:
                continue
            seen_classes.add(dedup_key)

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
            if module_map is not None:
                cls_dict["module"] = module
                cls_dict["source_uri"] = uri
                cls_dict["ref_class_id"] = f"{module}:{cls_name}" if module else cls_name
                cls_dict["belongs_to_domains"] = list(module_info.get("domains", []))
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


def _module_tag(cls: dict[str, Any]) -> str:
    """Render a ``  [module: X]`` suffix for a tagged cross-module class.

    Returns an empty string for home-only classes (no ``module`` key), keeping
    the default prompt byte-identical.
    """
    module = cls.get("module", "")
    return f"  [module: {module}]" if module else ""


def _format_ref_inventory(ref_classes: list[dict[str, Any]]) -> str:
    """Format reference model inventory for the LLM prompt."""
    lines = []
    for cls in ref_classes:
        props = cls.get("properties", [])
        prop_lines = []
        for p in props[:MAX_REF_PROPERTIES_PER_PROMPT]:
            range_str = f" ({p['range']})" if p.get("range") else ""
            prop_lines.append(f"    - {p['name']} [{p.get('label', p['name'])}]{range_str}")
        lines.append(f"  CLASS: {cls['name']} ({cls.get('label', cls['name'])})"
                     f"{_module_tag(cls)}")
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


def _select_property_pool(
    table_name: str,
    columns: list[dict[str, Any]],
    property_ref_classes: list[dict[str, Any]],
    table_shortlist: list[dict[str, Any]],
    *,
    indicative_columns: list[str] | None = None,
    max_cross: int = MAX_CROSS_MODULE_CLASSES,
) -> list[dict[str, Any]]:
    """Build the STEP-2 property candidate pool for cross-module mode (DD-070).

    Always includes the home table-classification shortlist, plus the top
    ``max_cross`` sibling/shared-module classes (``is_home`` False) scored by
    property/column token overlap, so a precise sibling class (e.g. Address) can
    surface for an address column without crowding out the home candidates.
    Deterministic: ties broken by ``ref_class_id``/name.
    """
    if indicative_columns is None:
        indicative_columns = []

    selected_ids: set[str] = set()
    selected: list[dict[str, Any]] = []

    def _cid(cls: dict[str, Any]) -> str:
        return str(cls.get("ref_class_id") or cls.get("name", ""))

    for cls in table_shortlist:
        cid = _cid(cls)
        if cid not in selected_ids:
            selected_ids.add(cid)
            selected.append(cls)

    table_tokens = _tokenize_text(table_name)
    column_tokens: set[str] = set()
    for col in columns:
        column_tokens.update(_tokenize_text(str(col.get("name", ""))))
        for sample in col.get("samples", [])[:2]:
            column_tokens.update(_tokenize_text(str(sample)))
    indicative_tokens = _tokenize_text(" ".join(indicative_columns))

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for cls in property_ref_classes:
        if cls.get("is_home"):
            continue
        cid = _cid(cls)
        if cid in selected_ids:
            continue
        score = _score_ref_class(
            cls,
            table_tokens=table_tokens,
            column_tokens=column_tokens,
            likely_entity_tokens=set(),
            indicative_tokens=indicative_tokens,
        )
        scored.append((score, cid, cls))

    # Keep only classes with some lexical signal; sort by score then id (stable).
    scored = [s for s in scored if s[0] > 0.0]
    scored.sort(key=lambda x: (-x[0], x[1]))
    for _, cid, cls in scored[:max_cross]:
        selected_ids.add(cid)
        selected.append(cls)

    return selected


def _build_class_meta_index(
    property_ref_classes: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Index tagged classes by name → list of module metadata (DD-070).

    Each entry: ``{module, source_uri, belongs_to_domains, is_home}``. A name may
    map to several entries (e.g. a home class and a same-named sibling-module
    class), disambiguated later by the model-supplied ``ref_module``.
    """
    index: dict[str, list[dict[str, Any]]] = {}
    for cls in property_ref_classes:
        name = str(cls.get("name", ""))
        if not name:
            continue
        index.setdefault(name, []).append({
            "module": cls.get("module", ""),
            "source_uri": cls.get("source_uri", ""),
            "belongs_to_domains": list(cls.get("belongs_to_domains", [])),
            "is_home": bool(cls.get("is_home")),
        })
    return index


def _resolve_column_module(
    ref_class_name: str,
    ref_module: str,
    class_meta: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """Resolve a matched column's class to sibling-module metadata, or None.

    Returns the chosen non-home meta dict when the column maps to a
    sibling/shared-module class; returns None when the match is home-domain (no
    tag) or the class is unknown. Prefers an explicit model-supplied ``ref_module``,
    then a home class (to avoid false cross-module tags), then any sibling class.
    """
    metas = class_meta.get(ref_class_name)
    if not metas:
        return None
    chosen: dict[str, Any] | None = None
    if ref_module:
        chosen = next((m for m in metas if m["module"] == ref_module), None)
    if chosen is None:
        chosen = next((m for m in metas if m["is_home"]), None)
    if chosen is None:
        chosen = next((m for m in metas if not m["is_home"]), None)
    if chosen is None or chosen["is_home"]:
        return None
    return chosen


def build_alignment_prompt(
    table_name: str,
    columns: list[dict[str, Any]],
    ref_classes: list[dict[str, Any]],
    likely_entity: str = "",
    *,
    table_ref_classes: list[dict[str, Any]] | None = None,
) -> str:
    """Build the alignment prompt for one source table.

    Two-stage in a single call:
    1. Which reference class does this table best align to?
    2. For each column, which reference property is the best match?

    When *table_ref_classes* is provided (DD-070 cross-module mode), STEP 1 is
    constrained to those home-domain classes while STEP 2 may match properties on
    ANY class in *ref_classes* (the widened accelerator pool). Without it (default),
    both steps draw from *ref_classes* and the output is unchanged.
    """
    table_classes = table_ref_classes if table_ref_classes is not None else ref_classes
    entity_hint = ""
    step1 = "STEP 1: Determine which reference model class this table best represents."
    likely_match = ""
    if likely_entity:
        # CR-2: when the affinity step already derived the entity and it matches a
        # candidate class, anchor STEP 1 on it instead of re-deriving from scratch.
        likely_match = next(
            (c["name"] for c in table_classes
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

    class_names = ", ".join(c["name"] for c in table_classes)

    cross_module_note = ""
    ref_module_field = ""
    if table_ref_classes is not None:
        ref_module_field = (
            '\n      "ref_module": "<module name if the matched property\'s class is '
            'a sibling/shared module, else empty>",'
        )
        cross_module_note = (
            "\nCROSS-MODULE: Some reference classes below belong to sibling or shared "
            "modules (marked '[module: <name>]'). For STEP 1 choose the table's class "
            "ONLY from the table-candidate classes listed above. For STEP 2 you MAY map "
            "a column to a property on ANY class, including a sibling-module class — "
            "prefer a precise sibling-module match (e.g. an Address, PaymentTerms, or "
            "Currency class) over force-fitting an address/payment/currency column onto "
            "an unrelated home-domain scalar. When a column maps to a sibling-module "
            "class, set its `ref_module` to that class's module name.\n"
        )

    return f"""Align this source database table to the reference model.

{step1}
STEP 2: For each source column, find the best matching reference model property.
{entity_hint}{cross_module_note}
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
      "ref_class": "<class name that owns this property>",{ref_module_field}
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
    *,
    table_ref_classes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run LLM alignment for one source table against reference model classes.

    Returns normalized dict with ref_class, ref_class_confidence, column_alignments.

    When *table_ref_classes* is given (DD-070 cross-module mode), the table's
    ``ref_class`` is validated against those home classes while each column's
    ``ref_class`` may be any class in *ref_classes* (the widened pool); a per-column
    ``ref_module`` is captured when the model supplies one.
    """
    if not ref_classes:
        return {
            "ref_class": "",
            "ref_class_confidence": 0.0,
            "column_alignments": [],
        }

    prompt = build_alignment_prompt(
        table_name, columns, ref_classes, likely_entity,
        table_ref_classes=table_ref_classes,
    )
    table_classes = table_ref_classes if table_ref_classes is not None else ref_classes
    valid_classes = {c["name"] for c in table_classes}

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
            (c["name"] for c in table_classes
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
        norm: dict[str, Any] = {
            "column": col_name,
            "ref_class": str(ca.get("ref_class", ref_class) or ref_class),
            "ref_property": str(ca.get("ref_property", "") or ""),
            "alignment": alignment,
            "confidence": _clamp_confidence(ca.get("confidence", 0.0)),
            "rationale": str(ca.get("rationale", "") or ""),
        }
        # DD-070: carry the model's sibling-module signal only when present, so the
        # normalized result (and per-table cache) stays identical in default mode.
        ref_module = str(ca.get("ref_module", "") or "")
        if ref_module:
            norm["ref_module"] = ref_module
        alignments.append(norm)

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
# Plausibility / address review pass (DD-069, issues #167/#168)
# ---------------------------------------------------------------------------
#
# Deterministic, no-LLM guards that FLAG (never reclassify) implausible column
# alignments for human review. The pass runs on the main thread during table
# assembly, AFTER sidecar-cache retrieval; it only decorates ``ColumnAlignment``
# objects and never mutates the cached raw LLM ``result`` dict. When no rule
# fires the YAML output is byte-identical to pre-DD-069.

#: Below this LLM confidence a name-mismatched map is considered review-worthy.
REVIEW_MIN_CONFIDENCE = 0.6

#: Unambiguous address-part tokens — strong enough to flag on their own.
_ADDRESS_PART_TOKENS = frozenset({
    "street", "postalcode", "postcode", "zipcode", "addressline",
    "housenumber", "houseno",
})

#: Address qualifier tokens that, combined with a weak token, confirm an
#: address-part column (e.g. ``shipper_city``, ``billing_zip``).
_ADDRESS_QUALIFIER_TOKENS = frozenset({
    "shipper", "consignee", "billing", "shipping", "delivery", "invoice",
    "mailing", "registered", "home", "work", "contact",
})

#: Ambiguous address tokens — only treated as address parts together with a
#: qualifier (bare ``country``/``city`` are too easily citizenship/name fields).
_ADDRESS_WEAK_TOKENS = frozenset({"city", "country", "zip", "postal", "address"})

#: Property name fragments that mark a property as ADDRESS-flavoured (so an
#: address-part column mapped here is plausible and must NOT be flagged).
_ADDRESS_PROPERTY_TOKENS = frozenset({
    "address", "street", "city", "country", "postal", "zip", "location",
})

#: Generic identity / name properties a weakly-evidenced or address/financial
#: column should not silently land on. Specific identifiers (taxIdentifier,
#: vatNumber, bankAccountIdentifier, ...) are deliberately excluded.
_GENERIC_IDENTITY_PROPERTIES = frozenset({
    "partyidentifier", "registrationnumber", "partyname", "name", "identifier",
})

#: Column tokens that mark a column as financial-flavoured.
_FINANCIAL_COLUMN_TOKENS = frozenset({
    "iban", "bic", "swift", "currency", "payment", "amount", "balance",
})


def _build_property_label_index(
    ref_classes: list[dict[str, Any]],
) -> dict[tuple[str | None, str], str]:
    """Index (class, property) → label, with a (None, property) name fallback."""
    idx: dict[tuple[str | None, str], str] = {}
    for cls in ref_classes:
        cls_name = cls.get("name", "")
        for p in cls.get("properties", []):
            pname = p.get("name", "")
            label = p.get("label", "") or pname
            idx[(cls_name, pname)] = label
            idx.setdefault((None, pname), label)
    return idx


def _lookup_property_label(
    idx: dict[tuple[str | None, str], str],
    ref_class: str,
    ref_property: str,
) -> str:
    """Resolve a property label by (class, property) then by property name."""
    if (ref_class, ref_property) in idx:
        return idx[(ref_class, ref_property)]
    return idx.get((None, ref_property), "")


def _compact_name(value: str) -> str:
    """Lowercased alphanumeric-only form of a name (deterministic)."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _detect_address_part(column_name: str) -> bool:
    """Return True when *column_name* is strong evidence of an address part."""
    tokens = _tokenize_text(column_name)
    if not tokens:
        return False
    # Compact form so address_line_1 / postal_code / house_number also match.
    compact = _compact_name(column_name)
    if any(tok in tokens or tok in compact for tok in _ADDRESS_PART_TOKENS):
        return True
    # Weak tokens require an address qualifier to confirm (shipper_city, ...).
    if (tokens & _ADDRESS_WEAK_TOKENS) and (tokens & _ADDRESS_QUALIFIER_TOKENS):
        return True
    return False


def _is_address_property(ref_property: str) -> bool:
    """Return True when *ref_property* is an address-flavoured property."""
    tokens = _tokenize_text(ref_property)
    compact = _compact_name(ref_property)
    return any(t in tokens or t in compact for t in _ADDRESS_PROPERTY_TOKENS)


def _review_column_alignment(
    *,
    column_name: str,
    data_type: str,
    ref_class: str,
    ref_property: str,
    confidence: float,
    label_index: dict[tuple[str | None, str], str],
) -> str | None:
    """Return a review reason when a column map is implausible, else ``None``.

    Deterministic; FLAGS (never changes) the mapping. Covers issue #167
    (address-part columns force-fit onto non-address scalars) and issue #168
    (boolean→identity, financial→identity, and weak-name + low-confidence maps).
    """
    if not ref_property:
        return None

    prop_label = _lookup_property_label(label_index, ref_class, ref_property)
    col_tokens = _tokenize_text(column_name)
    prop_tokens = _tokenize_text(ref_property) | _tokenize_text(prop_label)
    shared = col_tokens & prop_tokens
    is_identity = ref_property.lower() in _GENERIC_IDENTITY_PROPERTIES

    # #167 — address-part columns. Mapping to a non-address scalar is implausible;
    # mapping to an address-flavoured property is plausible (and exempt from the
    # generic low-confidence rule below, since street↔address share no token).
    if _detect_address_part(column_name):
        if _is_address_property(ref_property):
            return None
        return (
            f"address-part column '{column_name}' mapped to non-address property "
            f"'{ref_property}'; model an address relationship / shared Address concept"
        )

    logical = _normalize_logical_type(data_type)

    # #168 — boolean source mapped to a string identity/name property.
    if logical == "bool" and is_identity:
        return (
            f"boolean column '{column_name}' mapped to identity/name property "
            f"'{ref_property}'; likely a flag, not an identifier"
        )

    # #168 — financial-flavoured column mapped to a generic identity property.
    if (col_tokens & _FINANCIAL_COLUMN_TOKENS) and is_identity:
        return (
            f"financial-flavoured column '{column_name}' mapped to identity/name "
            f"property '{ref_property}'; confirm the intended target"
        )

    # #168 — no shared name token AND low confidence. Numeric→string identifier is
    # common & valid, so it is only flagged here when the name also doesn't line up.
    if not shared and confidence < REVIEW_MIN_CONFIDENCE:
        return (
            f"column '{column_name}' and property '{ref_property}' share no name "
            f"token and confidence is low ({confidence:.2f})"
        )

    return None


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
    cross_module: bool = False,
    accelerator: str | None = None,
    ref_models_dir: Path | None = None,
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
        cross_module: DD-070 (issue #166) — when True, widen the STEP-2 property
            candidate pool to the whole accelerator (sibling/shared modules) so
            columns can match cross-module properties, and tag each cross-module
            match with its owning ``ref_module``. Requires *accelerator* +
            *ref_models_dir*. Default False keeps output byte-identical.
        accelerator: Accelerator pack name whose ``data-domains.yaml`` defines the
            cross-module property pool (required when *cross_module* is True).
        ref_models_dir: Reference-models directory containing ``accelerator-packs/``
            (required when *cross_module* is True).

    Returns list of written output file paths.
    """
    if report is None:
        report = lambda msg, **kw: None  # noqa: E731

    # DD-070: resolve the accelerator import → module map for cross-module mode.
    accelerator_uri_modules: dict[str, dict[str, Any]] = {}
    if cross_module:
        if not accelerator or not ref_models_dir:
            raise ValueError(
                "--cross-module requires an accelerator and a reference-models "
                "directory. Pass --accelerator <name> (and ensure "
                "ontology-reference-models/ is present)."
            )
        from .analyse_sources import load_accelerator_uri_modules
        accelerator_uri_modules = load_accelerator_uri_modules(
            Path(ref_models_dir), accelerator
        )
        if not accelerator_uri_modules:
            raise ValueError(
                f"--cross-module: no data-domains.yaml found for accelerator "
                f"'{accelerator}' under {ref_models_dir}. Check the accelerator name "
                "and that reference models are installed."
            )
        report(
            f"  🔗 Cross-module: {len(accelerator_uri_modules)} accelerator module "
            f"URI(s) from '{accelerator}'"
        )

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

        # DD-070: params signature distinguishes a cross-module run from a prior
        # home-only one so the freshness skip does not reuse stale output. Only
        # computed/persisted in cross-module mode (default output stays identical).
        params_hash = ""
        if cross_module:
            params_hash = compute_entry_hash({
                "cross_module": True,
                "accelerator": accelerator or "",
                "accelerator_uris": sorted(accelerator_uri_modules.keys()),
                "home_uris": sorted(domain_uris),
            })

        # CR-5: domain-level skip — reuse an existing alignment whose freshness
        # hash already matches the current affinity set (unless --force). In
        # cross-module mode the params hash must match too (DD-070).
        out_path = output_dir / f"{domain_id}-alignment.yaml"
        if not force and out_path.exists():
            existing_hash = _read_alignment_affinity_hash(out_path)
            if existing_hash and existing_hash == affinity_hash:
                params_ok = (not cross_module) or (
                    _read_alignment_params_hash(out_path) == params_hash
                )
                if params_ok:
                    report(
                        f"     ⏭  Up to date (affinity unchanged) — skipped {out_path.name}"
                    )
                    output_files.append(out_path)
                    continue

        # Resolve reference model inventory (home domain — STEP 1 + rollup + hints)
        ref_classes = extract_ref_model_inventory(domain_uris, catalog_path)
        if ref_classes:
            report(
                f"     Ref model: {len(ref_classes)} class(es), "
                f"{sum(len(c.get('properties', [])) for c in ref_classes)} properties"
            )
        else:
            report(f"     ⚠ No reference model resolved for {domain_uris}")

        # DD-070: widened STEP-2 property pool spanning the whole accelerator.
        if cross_module:
            home_uri_set = set(domain_uris)
            property_ref_classes = extract_ref_model_inventory(
                sorted(accelerator_uri_modules.keys()), catalog_path,
                module_map=accelerator_uri_modules,
            )
            for c in property_ref_classes:
                c["is_home"] = c.get("source_uri", "") in home_uri_set
            class_meta = _build_class_meta_index(property_ref_classes)
            cross_count = sum(1 for c in property_ref_classes if not c.get("is_home"))
            report(
                f"     Cross-module pool: {len(property_ref_classes)} class(es) "
                f"({cross_count} sibling/shared)"
            )
        else:
            property_ref_classes = ref_classes
            class_meta = {}

        # DD-045: property-range index for deterministic transform hints
        range_index = (
            _build_property_range_index(ref_classes) if include_mapping_hints else {}
        )

        # DD-069: property-label index for the deterministic review pass (always
        # built — cheap, and the review flags are an always-on quality guard).
        review_label_index = _build_property_label_index(ref_classes)

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
        if cross_module:
            # DD-070: cross-module results must not collide with home-only ones.
            align_params["cross_module"] = True
            align_params["accelerator"] = accelerator or ""
            align_params["cross_module_signature"] = compute_entry_hash([
                [c.get("ref_class_id", c.get("name", "")),
                 [p.get("name", "") for p in c.get("properties", [])]]
                for c in property_ref_classes
            ])

        alignment = DomainAlignment(
            domain=domain_id,
            domain_uris=domain_uris,
            generated_at=datetime.now(timezone.utc).isoformat(),
            model_used=model,
            affinity_sha256=affinity_hash,
            alignment_params_sha256=params_hash or None,
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
                if cross_module:
                    # DD-070: STEP 1 stays home-scoped; STEP 2 uses the widened
                    # accelerator pool. No full-inventory retry (cost guard).
                    prop_pool = _select_property_pool(
                        table, columns, property_ref_classes, shortlist_classes,
                        indicative_columns=indicative_columns,
                    )
                    result = align_table(
                        client, model, table, columns, prop_pool,
                        likely_entity=likely_entity,
                        table_ref_classes=shortlist_classes,
                    )
                else:
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

        # DD-070: accumulate cross-module matches across the domain's tables.
        cross_module_acc: dict[tuple[str, str], dict[str, Any]] = {}

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
            address_hints: list[dict[str, Any]] = []
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
                        # Issue #164: triage disposition filled during domain
                        # modeling (model | silver-passthrough | skip); null until
                        # a modeler dispositions it.
                        "disposition": None,
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
                    # DD-069: deterministic plausibility/address review flag.
                    review_reason = _review_column_alignment(
                        column_name=ca["column"],
                        data_type=col_data_type,
                        ref_class=ref_class_name,
                        ref_property=ca["ref_property"],
                        confidence=ca["confidence"],
                        label_index=review_label_index,
                    )
                    if review_reason:
                        column_alignment.review = True
                        column_alignment.review_reason = review_reason
                        if include_mapping_hints and _detect_address_part(ca["column"]):
                            address_hints.append({
                                "type": "address_candidate",
                                "source_table": table,
                                "source_column": ca["column"],
                                "current_property": ca["ref_property"],
                                "requires_human_confirmation": True,
                                "rationale": review_reason,
                            })
                    # DD-070: tag matches that resolved to a sibling/shared module.
                    if cross_module:
                        meta = _resolve_column_module(
                            ref_class_name,
                            str(ca.get("ref_module", "") or ""),
                            class_meta,
                        )
                        if meta is not None:
                            column_alignment.ref_module = meta["module"] or None
                            column_alignment.ref_module_uri = meta["source_uri"] or None
                            domains = meta.get("belongs_to_domains", [])
                            if len(domains) == 1:
                                column_alignment.belongs_to_domain = domains[0]
                            elif len(domains) > 1:
                                column_alignment.belongs_to_domains = list(domains)
                            key = (ref_class_name, meta["module"])
                            acc = cross_module_acc.setdefault(key, {
                                "ref_class": ref_class_name,
                                "ref_module": meta["module"],
                                "ref_module_uri": meta["source_uri"],
                                "belongs_to_domains": list(domains),
                                "source_columns": [],
                            })
                            acc["source_columns"].append(
                                f"{system}.{table}.{ca['column']}"
                            )
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
                ) + address_hints
            alignment.tables.append(ta)

            matched = len(col_alignments)
            custom = len(custom_cols)
            cache_marker = " (cached)" if entry.get("from_cache") else ""
            report(
                f"     ├─ {system}.{table} → {ta.ref_class} "
                f"({matched} matched, {custom} custom){cache_marker}",
                level="verbose",
            )

        # Build reference rollup (home-domain classes only — DD-070 keeps cross-
        # module matches in a separate section to avoid distorting coverage%).
        alignment.reference_rollup = _build_reference_rollup(alignment, ref_classes)

        # DD-070: emit cross-module matches, deterministically sorted.
        if cross_module_acc:
            matches = []
            for _key, m in cross_module_acc.items():
                matches.append({
                    "ref_class": m["ref_class"],
                    "ref_module": m["ref_module"],
                    "ref_module_uri": m["ref_module_uri"],
                    "belongs_to_domains": m["belongs_to_domains"],
                    "source_columns": sorted(m["source_columns"]),
                })
            alignment.cross_module_matches = sorted(
                matches, key=lambda r: (r["ref_module"], r["ref_class"])
            )
            report(
                f"     🔗 Cross-module matches: {len(alignment.cross_module_matches)} "
                "class(es)"
            )

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


def _read_alignment_params_hash(alignment_path: Path) -> str:
    """Return the ``alignment_params_sha256`` recorded in an existing file (DD-070)."""
    try:
        data = yaml.safe_load(alignment_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("alignment_params_sha256", "") or "")


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
            # DD-069: emit review flags only when a rule fired (default unchanged)
            if ca.review:
                col_dict["review"] = True
                col_dict["review_reason"] = ca.review_reason
            # DD-070: emit cross-module tags only when set (default unchanged)
            if ca.ref_module:
                col_dict["ref_module"] = ca.ref_module
                if ca.ref_module_uri:
                    col_dict["ref_module_uri"] = ca.ref_module_uri
                if ca.belongs_to_domain:
                    col_dict["belongs_to_domain"] = ca.belongs_to_domain
                elif ca.belongs_to_domains:
                    col_dict["belongs_to_domains"] = ca.belongs_to_domains
            table_dict["columns"].append(col_dict)
        # DD-045: emit structural hints only when present (default unchanged)
        if ta.structural_hints:
            table_dict["structural_hints"] = ta.structural_hints
        data["tables"].append(table_dict)

    # DD-070: emit cross-module sections only in cross-module mode (default unchanged)
    if alignment.alignment_params_sha256:
        data["alignment_params_sha256"] = alignment.alignment_params_sha256
    if alignment.cross_module_matches:
        data["cross_module_matches"] = alignment.cross_module_matches

    output_file = output_dir / f"{alignment.domain}-alignment.yaml"
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return output_file
