# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""LLM-powered source-column → reference-model-property alignment.

Pre-modeling step that produces per-domain alignment proposals showing how
source columns map to reference model classes and properties. Consumes
affinity reports from ``analyse-sources`` and produces machine-readable YAML
that the modeling skill uses to pre-populate the Source Evidence Table.

The candidate property pool a column may be mapped to is *owner-tagged*: every
offered property is presented, enumerated and validated together with the class
that declares it. That single structure carries two guarantees:

* value objects reachable one hop from the anchor are offered at all, so a
  measurement the anchor class does not carry itself stops being reported as a
  gap (issue #517, :func:`expand_value_object_pool`);
* a proposed ``(class, property)`` pair must exist as a pair, not merely as two
  names that each exist somewhere in the pool (issue #520, qualified schema enum
  plus :func:`enforce_class_property_pairs`).

Requires an AI provider configuration (GITHUB_TOKEN or AZURE_AI_ENDPOINT).
"""

from __future__ import annotations

import json
import logging
import hashlib
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .source_analysis import (
    ALIGNMENT_ALGORITHM_VERSION,
    ALIGNMENT_HASH_SCHEMA_VERSION,
    compute_affinity_hash,
)
from .anchor_resolution import (
    AnchorResolution,
    load_confirmed_alias_index,
    resolve_table_anchor,
)
from .unresolved_anchors import (
    REASON_AMBIGUOUS_CONFIRMED_ALIAS,
    UnresolvedAnchor,
    load_unresolved_anchors_doc,
    merge_preserving_anchor_resolutions,
    unresolved_anchor_id,
    unresolved_anchors_path,
    write_unresolved_anchors_doc,
)
from .analyse_sources import (
    DEFAULT_MODEL,
    bridge_anchor_classes,
    load_cross_domain_bridges,
    load_data_domains,
    parse_source_vocabulary,
    parse_reference_model,
)
from .ai_provider import (
    ROLE_ALIGNMENT,
    create_chat_completion,
    get_ai_client,
    resolve_ai_seed,
    resolve_reasoning_effort,
    resolve_role_model,
    sanitize_provider_error,
)
from ._provenance import ai_attribution, provenance_comment
from .anchor_tables import (
    ANCHOR_CONFIDENCE_FLOOR,
    load_excluded_tables,
    load_table_anchors,
    regroup_by_anchor,
)
from .tracing import call_metadata, flush_tracing, new_session_id
from .ai_preflight import require_ai_provider
from ._concurrency import call_with_backoff, map_concurrent, DEFAULT_MAX_WORKERS
from ._cache import compute_entry_hash, open_cache
from ._samples import example_values as _render_example_values
from ._samples import is_pii_column
from .entity_projections import (
    EntityProjection,
    ProjectionConfig,
    load_entity_projections,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Columns per alignment call. Wider tables are split across successive calls and
#: merged (see :func:`align_table`), never truncated: an unassessed column is worse
#: than a slow one, because it cannot be mapped and does not surface as an orphan
#: either. Raised from 80 once splitting existed to make the cap safe.
MAX_COLUMNS_PER_PROMPT = 200
MAX_REF_PROPERTIES_PER_PROMPT = 60
MAX_REF_CLASSES_PER_PROMPT = 12
#: DD-070 (issue #166) — max sibling/shared-module classes added to the STEP-2
#: property pool in cross-module mode, on top of the home table-class shortlist.
MAX_CROSS_MODULE_CLASSES = 8
RETRY_MIN_CONFIDENCE = 0.6
RETRY_MIN_MAPPED_RATIO = 0.4
MAX_SAMPLE_CHARS = 48
#: Sample values shown per column in the alignment prompt (DD-166).
#:
#: Three was too few to tell a governed code list from free text -- the judgement
#: this step exists to make. Raised to match the bronze capture limit
#: (``import_source.MAX_SAMPLE_VALUES``); capturing 20 and then showing 3 would
#: waste the evidence. Affinity stays at three deliberately: it classifies a table
#: into a domain and needs only a type hint, so it should not carry the extra
#: prompt weight or PII surface.
MAX_SAMPLES_PER_COLUMN = 20

#: Issue #182 — confidence floor below which a ``custom`` column's LLM-suggested
#: property is treated as untrustworthy and emitted as the canonical *unmatched*
#: form (``ref_property: null``) instead of a confident-but-wrong guess.
CUSTOM_CONFIDENCE_FLOOR = 0.5

#: Issue #182 — a suggested property reused across this many *dissimilar* custom
#: columns is treated as a catch-all sink and downgraded to unmatched.
CATCH_ALL_MIN_COLUMNS = 3

#: Issue #182 — model tier used by the opt-in ``--high-accuracy`` preset for this
#: accuracy-sensitive alignment step. Prefer a strong *non-reasoning* model
#: (``gpt-5.4``): alignment is deterministic closed-vocabulary matching, so a
#: reasoning model (gpt-5.5+) adds latency/cost without benefit.
#: ``analyse-sources`` stays on the mini tier.
HIGH_ACCURACY_MODEL = "gpt-5.4"

# ---------------------------------------------------------------------------
# Alignment-reliability — typed per-table generation outcomes
from kairos_ontology.core.generation_outcome import (  # noqa: E402
    OUTCOME_FALLBACK_ONLY,
    OUTCOME_PROVIDER_FAILURE,
    OUTCOME_SEMANTIC_SUCCESS,
)


class AlignmentTotalFailureError(RuntimeError):
    """Raised when every attempted table's semantic generation failed.

    "Attempted" excludes tables skipped via the per-domain freshness cache and
    ``fallback_only`` tables (no reference model to align against — a separate,
    opt-in concern gated by ``--allow-fallback-output``). When raised, **no**
    registry was written by the run at all: every write is staged and committed
    only after the run-wide semantic verdict is known, so a mixed domain (some
    tables ``provider_failure``, some ``fallback_only``) and an opted-in
    ``fallback_only``-only domain are equally left uncommitted, and whatever
    existed on disk is untouched. Callers must exit non-zero and never report
    success.
    """


# These narrow column-triage heuristics belong to proposal generation.

#: Lower-cased substrings that identify likely operational/audit custom columns.
#: They only inform the proposal bucket; they never remove a coverage obligation.
_OPERATIONAL_PATTERNS = (
    "created_",
    "updated_",
    "modified_",
    "inserted_",
    "deleted_",
    "_created",
    "_updated",
    "_modified",
    "createdat",
    "updatedat",
    "_by",
    "createdby",
    "modifiedby",
    "systemcreate",
    "systemlastedit",
    "timestamp",
    "rowversion",
    "row_version",
    "loaddate",
    "load_date",
    "load_ts",
    "loadts",
    "etl_",
    "_etl",
    "_dwh",
    "dwh_",
    "is_deleted",
    "isdeleted",
    "source_id",
    "sourceid",
    "source_system",
    "sourcesystem",
    "_guid",
    "guid",
    "uuid",
    "_uid",
    "_hash",
    "checksum",
)

_CF_SLOT_RE = re.compile(r"^cf[a-z]*\d+$", re.IGNORECASE)

_AUDIT_AUTO_PATTERNS = (
    "created_",
    "_created",
    "createdon",
    "createdby",
    "createdat",
    "updated_",
    "_updated",
    "updatedon",
    "updatedby",
    "updatedat",
    "modified_",
    "_modified",
    "modifiedon",
    "modifiedby",
    "inserted_",
    "is_deleted",
    "isdeleted",
    "systemcreate",
    "systemlastedit",
    "rowversion",
    "row_version",
    "loaddate",
    "load_date",
    "load_ts",
    "loadts",
    "last_ingest",
    "ingest_date",
    "etl_",
    "_etl",
    "_dwh",
    "dwh_",
    "tenant_id",
    "tenantid",
    "_hash",
    "checksum",
)


def _is_operational_column(column: str) -> bool:
    """Return whether a custom column looks operational/audit-oriented."""

    name = (column or "").lower()
    return any(pattern in name for pattern in _OPERATIONAL_PATTERNS)


def is_generic_vendor_slot(column: str) -> bool:
    """Return whether a name is an opaque vendor custom-field slot."""

    return bool(_CF_SLOT_RE.match((column or "").strip()))


def auto_disposition(column: str) -> str | None:
    """Return the narrow auto-fillable disposition, if one is safe."""

    name = (column or "").lower()
    if any(pattern in name for pattern in _AUDIT_AUTO_PATTERNS):
        return "skip"
    return None


def normalize_local_proposal(raw: Any) -> dict[str, str] | None:
    """Validate a model-proposed **hub-local** property, or return ``None`` (DD-170).

    The aligner is told never to invent a ``ref_property``, and that stays true: an
    invented reference IRI is a hallucination that fails resolution later. A hub-local
    proposal is a different object — it says "this does not exist, someone should create
    it" — and it is what turns a Stage 3 backlog of unhomed columns into a list of named
    properties on named classes to accept or reject.

    Keeping the two apart is the whole safety property, so this enforces it structurally:

    * a proposal carrying anything IRI-shaped is rejected outright, because the hub mints
      its own IRIs and a model-supplied one would be indistinguishable from a resolvable
      reference term downstream;
    * a proposal without a name is nothing;
    * the name is normalised to lowerCamelCase, matching the naming rule
      ``validate --syntax`` enforces, so an accepted proposal does not immediately fail
      the next gate.
    """
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    # Scoped to the structural fields. ``why`` is prose, and discarding an otherwise
    # good proposal because its rationale happens to mention a URN would cost more than
    # it protects: the risk is an IRI being *used* as a term, not being talked about.
    for key in ("name", "range", "on_class"):
        text = str(raw.get(key) or "")
        if "://" in text or text.lower().startswith(("http:", "https:", "urn:")):
            logger.warning("Discarding local property proposal carrying an IRI: %r", raw)
            return None
    parts = re.findall(r"[A-Za-z0-9]+", name)
    if not parts:
        return None
    camel = parts[0][:1].lower() + parts[0][1:] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
    proposal = {"name": camel}
    for key in ("range", "on_class", "why"):
        value = str(raw.get(key) or "").strip()
        if value:
            proposal[key] = value
    return proposal


#: Proposal name shapes that encode a role as an attribute (DD-171).
#:
#: ``isSubcontractor``, ``hasCarrierRole``, ``subcontractorStatus``. Harmless on an
#: ordinary class; on a party class the pattern library flags, this is
#: ``subclass-identity-by-role`` arriving as a property instead of a subclass.
_ROLE_FLAG_RE = re.compile(
    r"^(?:is|has)[A-Z]|(?:Role|Status)$|Role[A-Z]",
)


def flag_risky_proposals(
    custom_columns: list[dict[str, Any]],
    *,
    class_cautions: dict[str, str],
    ref_class_uri: str = "",
) -> int:
    """Mark local-property proposals that a pattern-library caution bears on (DD-171).

    Flags, never blocks. A role flag is sometimes the right first slice — the pattern
    library says so itself, permitting one as a ``physical_simplification`` provided it
    is "documented as a denormalised projection of the role-assignment link entity,
    never the semantic model itself". What must not happen is it becoming the model by
    default, which is exactly what bulk-accepting proposals would do.

    Observed on a real run before this existed: aligning ``contacts`` produced
    ``associatedCompanyIsSubcontractor``, ``associatedCompanyIsIntermodalOperator`` and
    ``associatedCompanySubcontractorStatus`` as booleans on ``Contact`` — four role
    flags on the wrong class, faithful to the source and blind to the rule.

    Returns the number flagged.
    """
    caution = class_cautions.get(ref_class_uri, "")
    if not caution:
        return 0
    flagged = 0
    for entry in custom_columns:
        proposal = entry.get("proposed_local_property")
        if not isinstance(proposal, dict):
            continue
        name = str(proposal.get("name") or "")
        if not _ROLE_FLAG_RE.search(name):
            continue
        proposal["needs_review"] = True
        proposal["review_reason"] = (
            f"Proposes a role as an attribute on a class the pattern library flags. "
            f"{caution} Accept only as a documented denormalised projection of a "
            "role-assignment entity, not as the role model itself."
        )
        flagged += 1
    return flagged


def load_glossary_terms(hub_root: Path | None, *, limit: int = 120) -> list[str]:
    """Return the business's own vocabulary from ``businessdiscovery/*.ttl`` (DD-171).

    Grounding, not authority. A proposal should reuse the term the business already uses
    where one exists, rather than minting ``associatedCompanySubcontractorStatus``.
    Returns ``[]`` when the hub has no authored glossary, which is common early and must
    never be an error.
    """
    if hub_root is None:
        return []
    directory = Path(hub_root) / "businessdiscovery"
    if not directory.is_dir():
        return []
    labels: set[str] = set()
    label_re = re.compile(r"skos:prefLabel\s+\"([^\"]+)\"")
    for path in sorted(directory.glob("*.ttl")):
        if path.name.startswith(("glossary-template", "_")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        labels.update(m.group(1).strip() for m in label_re.finditer(text))
        if len(labels) >= limit:
            break
    return sorted(labels)[:limit]


def recommend_disposition(column: str) -> str:
    """Return an advisory custom-column disposition recommendation."""

    if is_generic_vendor_slot(column):
        return "silver-passthrough"
    if _is_operational_column(column) or auto_disposition(column) == "skip":
        return "skip"
    return ""


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
    # DD-075 sample-grounded evidence. ``example_values`` is produced by default
    # (PII masked via the shared policy); suppressed with --no-sample-values.
    # ``transform_compat`` is an advisory warning when a proposed CAST looks
    # incompatible with the real sampled values. Both emitted only when present.
    example_values: list[str] | None = None
    transform_compat: str | None = None
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
    #: Issue #182 (WS6) — anchor-class provenance so a rejected/hallucinated class
    #: is reported rather than silently blanked. ``matched`` = model picked a valid
    #: class; ``fallback`` = invalid pick recovered via the affinity entity;
    #: ``rejected`` = invalid pick with no valid fallback (unanchored); ``unmatched``
    #: = model returned no class.
    ref_class_status: str = "matched"
    #: The original invalid class the model proposed, when it was rejected/fell back.
    rejected_ref_class: str | None = None
    #: Issue #192 (Phase A1) / DD-188 — deterministic, additive relationship
    #: candidates (clustered entity-projection columns, downgraded object
    #: properties). Populated only when a detector fires, so default output stays
    #: unchanged; the projection detector fires only when the accelerator pack
    #: ships an ``entity-projections.yaml``.
    relationship_candidates: list[dict[str, Any]] = field(default_factory=list)
    #: DD-179 — relational consistency warnings across the table's whole mapping
    #: (e.g. two distinct role groups collapsing onto one property). Advisory: a
    #: coarser model is a legitimate design choice, so these flag rather than
    #: block. Emitted only when a rule fires, so default output is unchanged.
    consistency_flags: list[str] = field(default_factory=list)
    #: F6 (toolkit-optimizations) — the true source-vocabulary column count and a
    #: deterministic digest of the sorted source column names, captured before any
    #: prompt truncation. Persisted so ``check-claims`` can detect columns that were
    #: dropped from the registry. ``0`` / ``""`` when not populated.
    source_column_count: int = 0
    source_column_sha256: str = ""
    #: F2/F7 (toolkit-optimizations) — the candidate business entity the affinity/
    #: analysis stage inferred for this source table (``likely_entity``). Carried
    #: through so ``alignment_to_registry`` can detect when tables with *different*
    #: candidate entities collapse onto one ``ref_class`` (a possible grain merge).
    #: Empty when no candidate entity was inferred.
    likely_entity: str = ""
    #: Alignment-reliability — typed per-table generation outcome. Default
    #: ``OUTCOME_SEMANTIC_SUCCESS`` keeps the happy-path output unchanged; the
    #: producer only ever sets ``provider_failure`` / ``fallback_only`` (see
    #: module docstring constants). ``generation_provider`` / ``generation_model``
    #: / ``generation_error`` are populated only alongside a non-success outcome
    #: and ``generation_error`` is always pre-sanitized (no secrets).
    generation_outcome: str = OUTCOME_SEMANTIC_SUCCESS
    generation_provider: str | None = None
    generation_model: str | None = None
    generation_error: str | None = None
    #: uri-anchor-contract — the canonical inventory URI a confirmed discovery
    #: alias (``core-concepts-conformance.yaml`` ``conforms``/
    #: ``conforms-with-rename`` outcome) resolved this table's anchor to.
    #: Populated only when ``ref_class_status == "confirmed"``; empty otherwise
    #: (byte-identical output when no conformance artifact is supplied).
    likely_entity_uri: str = ""
    #: uri-anchor-contract — the candidate URIs that made a confirmed anchor
    #: ambiguous (``ref_class_status == "unresolved"``), kept for transparency/
    #: evidence on the table itself in addition to the dedicated
    #: ``DomainAlignment.unresolved_anchors`` record. Empty otherwise.
    anchor_candidate_uris: list[str] = field(default_factory=list)


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
    #: DD-094 — SHA-256 over the affinity ``(system, table)`` set this run saw,
    #: enabling the canonical completeness freshness check.
    affinity_sha256: str | None = None
    #: Issue #182 — algorithm/prompt-contract version this output was produced with.
    #: Lets the canonical completeness gate flag pre-hardening output as unverifiable.
    algorithm_version: int = ALIGNMENT_ALGORITHM_VERSION
    #: uri-anchor-contract — tables whose anchor could not be resolved because
    #: more than one confirmed alias/URI was plausible for the same table.
    #: These are also persisted as a separate versioned record (see
    #: ``unresolved_anchors.py``) so the decision survives re-runs and isn't
    #: silently overwritten by a "nearest class" guess.
    unresolved_anchors: list[dict[str, Any]] = field(default_factory=list)
    #: #528 follow-up — tables this domain's affinity claimed but which the
    #: schema-catalogue screen had already routed to not-business-data, each with
    #: the evidence that excluded it. Kept on the artifact rather than dropped
    #: silently: the screen is a heuristic, so a table that vanishes from a
    #: domain has to be answerable ("why is my orders sheet not aligned?")
    #: without re-running anything.
    excluded_tables: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Affinity report reading
# ---------------------------------------------------------------------------


def load_affinity_reports(
    analysis_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Load affinity reports and group tables by primary domain.

    Returns dict: domain_id → list of table dicts (each with system, table,
    columns count, likely_entity, indicative_columns, domain_uris).

    Tables whose affinity ``domain`` is empty are skipped: alignment picks candidate
    classes *from* a domain, so there is nothing to align them against. ``analyse_sources``
    blanks ``domain`` whenever the LLM assignment failed, so the skipped set is exactly the
    tables no domain claimed. Historically that skip was silent and they vanished from
    every artifact (issue #492/#500 -- "12 Qlik tables entirely untracked"); they are now
    counted and warned about here, and enumerated by ``domain-coverage``'s
    ``unassigned_source_tables`` (DD-160).
    """
    domain_tables: dict[str, list[dict[str, Any]]] = {}
    unassigned: list[str] = []

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
                unassigned.append(f"{system}.{tbl.get('table', '?')}")
                continue
            domain_tables.setdefault(domain, []).append(
                {
                    "system": system,
                    "table": tbl["table"],
                    "total_columns": tbl.get("total_columns", 0),
                    "likely_entity": tbl.get("likely_entity", ""),
                    "indicative_columns": tbl.get("indicative_columns", []),
                    "domain_uris": tbl.get("domain_uris", []),
                }
            )

    if unassigned:
        logger.warning(
            "%d source table(s) have no affinity domain and are excluded from alignment: "
            "%s. These have no canonical home — see 'kairos-ontology domain-coverage' "
            "(unassigned_source_tables) and re-run analyse-sources if the assignment "
            "merely failed.",
            len(unassigned),
            ", ".join(sorted(unassigned)),
        )

    return domain_tables


# ---------------------------------------------------------------------------
# Reference model property extraction (richer than _resolve_module_classes)
# ---------------------------------------------------------------------------


def _sorted_terms(terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order reference-model terms reproducibly (DD-175).

    Sorted on ``(name, uri)``: the name is what the prompt renders and what a
    human reads in a diff, and the URI breaks the tie between same-named terms
    from different modules. Both are stable across processes, which the parsed
    graph order is not.
    """
    return sorted(terms, key=lambda t: (str(t.get("name") or ""), str(t.get("uri") or "")))


def extract_ref_model_inventory(
    domain_uris: list[str],
    catalog_path: Path | None,
    *,
    module_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Resolve domain URIs and extract full class+property inventory.

    are preferred over re-parsing TTL files.

    When *module_map* (``{uri: {"module", "domains"}}``) is provided (DD-070,
    cross-module mode), each class is additionally tagged with ``module``,
    ``source_uri``, ``ref_class_id`` and ``belongs_to_domains``, and dedup is keyed
    on ``ref_class_id`` (so a same-named class in a different module is preserved).
    Full URI is always the identity key; local names remain display data.

    Returns list of class dicts with:
    {name, uri, label, comment, properties: [{name, uri, label, range, range_label,
     prop_type, comment}], specializations: [...]}
    """
    # DD-173: no cached-inventory fast path. This used to prefer
    # referencemodels-unpacked/*.yaml whenever the directory existed, which meant a hub
    # WITH inventories kept whatever the resolver got wrong when they were written --
    # the schema:domainIncludes fix was invisible to exactly the hubs that had run
    # generate-inventory. Resolving live costs milliseconds and cannot go stale.

    if not catalog_path or not catalog_path.exists():
        return []

    try:
        from kairos_ontology.core.catalog_utils import CatalogResolver

        resolver = CatalogResolver.with_reference_models(catalog_path)
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
                logger.warning("Cross-module: could not resolve accelerator import URI %s", uri)
            continue

        module_info = (module_map or {}).get(uri, {})
        module = module_info.get("module", "")

        ref = parse_reference_model(
            Path(path),
            include_specializations=True,
            catalog_path=catalog_path,
        )
        for cls in _sorted_terms(ref.get("classes", [])):
            cls_name = cls.get("name", "")
            dedup_key = str(cls.get("uri") or f"{uri}#{cls_name}")
            if dedup_key in seen_classes:
                continue
            seen_classes.add(dedup_key)

            # Enrich properties with full metadata from the parsed graph.
            #
            # DD-175: sorted, because the source order is rdflib graph-iteration
            # order and therefore differs between processes. That order reaches
            # the LLM prompt verbatim, so an unsorted list means every run sends
            # a *different* prompt and no seed can make the answer reproducible.
            # Own and inherited stay in separate groups (the distinction is real
            # and the prompt relies on it); each group is ordered within itself.
            props = []
            for group in ("properties", "inherited_properties"):
                for p in _sorted_terms(cls.get(group, [])):
                    props.append(
                        {
                            "uri": p.get("uri", ""),
                            "name": p.get("name", ""),
                            "label": p.get("label", ""),
                            "range": p.get("range", ""),
                            # Issue #517: the *resolved* range URI, not just its local
                            # name. Value-object expansion follows object-property
                            # ranges one hop out, and a local name is ambiguous the
                            # moment two modules both declare e.g. ``Terminal``.
                            "range_uri": p.get("range_uri", ""),
                            "comment": "",
                            # Carried through so the prompt can mark an object property
                            # (DD-172); this rebuild previously dropped it, leaving every
                            # property indistinguishable from a literal one.
                            "type": p.get("type", ""),
                        }
                    )

            cls_dict: dict[str, Any] = {
                "uri": cls.get("uri", ""),
                "name": cls_name,
                "label": cls.get("label", cls_name),
                "comment": cls.get("comment", ""),
                "properties": props,
                "_semantic": {
                    "semantic_profile": ref.get("semantic_profile", "kairos-design"),
                    "closure_hash": ref.get("closure_hash", ""),
                    "import_complete": ref.get("import_complete", True),
                    "source_identity": uri,
                },
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




# ---------------------------------------------------------------------------
# LLM prompt and alignment
# ---------------------------------------------------------------------------


def _hub_root_from_catalog(catalog_path: Path | None) -> Path | None:
    """Walk up from the catalog to the directory holding ``pyproject.toml`` (DD-181).

    The accelerator resolver reads ``[tool.kairos].accelerator`` from the hub's
    ``pyproject.toml``, which sits above ``ontology-hub/``. Walking up rather than
    assuming a fixed depth keeps this working for a catalog at either level.
    """
    if not catalog_path:
        return None
    for candidate in Path(catalog_path).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def resolve_bridge_anchor_classes(
    bridge_classes: dict[str, str],
    catalog_path: Path | None,
    *,
    exclude_uris: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve blueprint-authorised cross-domain classes into anchor candidates (DD-181).

    *bridge_classes* maps ``class_uri -> target_domain``, from
    :func:`~.analyse_sources.bridge_anchor_classes`.

    A source table often holds rows of an entity its domain *references* rather than
    *owns*: ``stops`` sits under ``consignment``, but each row is a transport call,
    a concept ``route-schedule`` owns. Offering only home classes leaves the model
    with nothing truthful to pick, and it correctly declines — which is how 306
    columns across nine tables ended up unanchored (DD-180) with no way forward
    short of importing a module the domain has no business owning.

    A declared bridge already says this reach is authorised, so the class is offered
    as an anchor and tagged with the domain that owns it. Ownership does not move:
    the tag is what keeps the boundary check (DD-163) able to tell an authorised
    reference from a redeclaration.

    Classes already in the home pool are excluded via *exclude_uris* — the model has
    seen those, and offering them twice would just inflate the prompt.
    """
    if not bridge_classes or not catalog_path:
        return []

    modules = sorted({uri.split("#")[0] + "#" for uri in bridge_classes if "#" in uri})
    if not modules:
        return []

    wanted = set(bridge_classes)
    skip = exclude_uris or set()
    resolved: list[dict[str, Any]] = []
    for cls in extract_ref_model_inventory(modules, catalog_path):
        uri = str(cls.get("uri") or "")
        if uri not in wanted or uri in skip:
            continue
        entry = dict(cls)
        entry["bridge_target_domain"] = bridge_classes[uri]
        resolved.append(entry)
    return _sorted_terms(resolved)


def _bridge_tag(cls: dict[str, Any]) -> str:
    """Render the cross-domain marker for a blueprint-bridged anchor candidate."""
    owner = cls.get("bridge_target_domain", "")
    if not owner:
        return ""
    return (
        f"  [CROSS-DOMAIN → owned by '{owner}', referenced here under a blueprint-declared "
        f"relationship; anchoring a table to it is allowed, redeclaring it locally is not]"
    )


def _module_tag(cls: dict[str, Any]) -> str:
    """Render a ``  [module: X]`` suffix for a tagged cross-module class.

    Returns an empty string for home-only classes (no ``module`` key), keeping
    the default prompt byte-identical.
    """
    module = cls.get("module", "")
    return f"  [module: {module}]" if module else ""


def _value_object_tag(cls: dict[str, Any]) -> str:
    """Render the ``[VALUE OBJECT …]`` marker for an issue-#517 pool addition.

    Empty for a shortlist class, so a domain with no value objects renders the
    same prompt it always did.
    """
    via = str((cls.get("_value_object_of") or {}).get("via") or "")
    if not via:
        return ""
    return (
        f"  [VALUE OBJECT / RELATED ENTITY reached from {via} — the reference model "
        f"puts these properties here, not on the class that owns the link]"
    )


def _format_ref_inventory(ref_classes: list[dict[str, Any]]) -> str:
    """Format reference model inventory for the LLM prompt."""
    lines = []
    for cls in ref_classes:
        props = cls.get("properties", [])
        prop_lines = []
        for p in props[:MAX_REF_PROPERTIES_PER_PROMPT]:
            range_str = f" ({p['range']})" if p.get("range") else ""
            # DD-172: mark object properties. Rendered identically to datatype ones,
            # `hasBillingAddress (Address)` looked like a string property called
            # Address, so the model could neither map a flat column to it nor say what
            # it implies. Observed live: `billing_address` came back "no address
            # property is listed on TradeParty" while hasBillingAddress -> Address was
            # sitting in the very list it was reading.
            kind = ""
            if str(p.get("type") or "").lower() == "object":
                kind = " [OBJECT PROPERTY → links to a related entity, not a literal]"
            label = p.get("label") or p["name"]
            label_str = f" [{label}]" if label != p["name"] else ""
            prop_lines.append(f"    - {p['name']}{label_str}{range_str}{kind}")
        lines.append(
            f"  CLASS: {cls['name']} ({cls.get('label', cls['name'])})"
            f"{_module_tag(cls)}{_bridge_tag(cls)}{_value_object_tag(cls)}"
        )
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
                    spec_prop_names = ", ".join(p.get("name", "") for p in spec_props[:10])
                    lines.append(f"      - {spec['class']}: {spec_prop_names}")
                else:
                    lines.append(f"      - {spec['class']}: (no own properties)")
    return "\n".join(lines)


#: Sample values shown for a column whose cardinality is high or unknown (DD-166).
#:
#: Twenty values is the right budget for a *code list*, which is the judgement alignment
#: makes. It is pure cost on a surrogate key, a timestamp or a free-text note, where the
#: values carry no shape the model can use and three already establish the type.
MAX_SAMPLES_HIGH_CARDINALITY = 3

#: A column with at most this many distinct values is an enum candidate and gets the
#: full budget. Matches ``MAX_SAMPLES_PER_COLUMN``: if every distinct value fits,
#: showing all of them *is* the evidence.
ENUM_CARDINALITY_CEILING = MAX_SAMPLES_PER_COLUMN

#: Ceiling on the whole table's rendered sample text, in characters.
#:
#: Sized from the real corpus: the widest table here has 1,304 columns, where an
#: unbudgeted twenty-per-column renders ~162 KB — roughly 41k tokens of samples alone,
#: in a prompt sent to a reasoning model once per table. The per-column rule below
#: usually keeps a table well under this; the cap exists so a pathologically wide table
#: degrades gracefully instead of dominating the run.
MAX_TABLE_SAMPLE_CHARS = 8000


def _samples_for_column(col: dict[str, Any]) -> list[str]:
    """Choose how many sample values this column earns.

    Cardinality decides. A column with few distinct values is a code-list candidate and
    the values are the evidence; a high-cardinality column is identified by its name and
    type, and twenty IDs say nothing that three do not.
    """
    values = _compact_prompt_samples(col.get("samples") or [])
    distinct = col.get("distinct_count")
    generous = isinstance(distinct, int) and 0 < distinct <= ENUM_CARDINALITY_CEILING
    return values if generous else values[:MAX_SAMPLES_HIGH_CARDINALITY]


#: Smallest number of columns sharing a leading token that counts as a role (DD-179).
#: Two is the meaningful floor — ``shipper_code`` + ``shipper_name`` is exactly the
#: pattern worth surfacing, and it is the commonest shape of a flattened relationship.
MIN_ROLE_GROUP_COLUMNS = 2

#: A "group" covering more than this share of a table is the table's own subject, not
#: a role within it: on a ``customers`` table half the columns start with ``customer``,
#: and calling that a related entity would invent a relationship that is not there.
MAX_ROLE_GROUP_SHARE = 0.5

#: Leading tokens that never denote a role — they are structural or temporal
#: qualifiers that cluster for reasons unrelated to entity identity.
_NON_ROLE_TOKENS = frozenset(
    {
        "is", "has", "no", "id", "code", "name", "date", "time", "created", "updated",
        "modified", "deleted", "archived", "total", "sum", "count", "min", "max", "avg",
        "first", "last", "new", "old", "current", "previous", "default", "temp", "tmp",
    }
)

#: Trailing tokens marking a column as *identifying or naming an entity*.
#:
#: This is what separates a role from a coincidence of prefixes. ``shipper_code``
#: + ``shipper_name`` refers to an entity twice; ``ActualDate`` +
#: ``ActualTimeFrom`` and ``KmLoadingTotal`` + ``KmUnloadingTotal`` share a prefix
#: for reasons that have nothing to do with entity identity, and were grouped by a
#: prefix-only rule on the live corpus. Requiring one of these markers targets the
#: pattern the "two roles must not share a property" rule is actually about, and
#: keeps the prompt quiet on the rest — an unhelpful group is not neutral, it
#: asserts a relationship the data does not have.
_ENTITY_REFERENCE_TOKENS = frozenset(
    {
        "code", "codes", "name", "names", "id", "ids", "identifier", "key", "keys",
        "number", "no", "nr", "ref", "reference", "description", "descr", "label",
    }
)


def _is_entity_reference(column_name: str) -> bool:
    """True when the column's non-leading tokens identify or name something."""
    cleaned = str(column_name or "").replace("_", " ").replace("-", " ")
    tokens = [t.lower() for t in _TOKEN_RE.findall(cleaned)]
    return any(t in _ENTITY_REFERENCE_TOKENS for t in tokens[1:])


def _leading_token(column_name: str) -> str:
    """Return the first token of a column name (``shipper_code`` -> ``shipper``)."""
    cleaned = str(column_name or "").replace("_", " ").replace("-", " ")
    tokens = _TOKEN_RE.findall(cleaned)
    return tokens[0].lower() if tokens else ""


def group_columns_by_role(
    columns: list[dict[str, Any]],
) -> tuple[list[tuple[str, list[dict[str, Any]]]], list[dict[str, Any]]]:
    """Split columns into apparent role groups and the ungrouped remainder (DD-179).

    Returns ``(groups, ungrouped)`` where *groups* is an ordered list of
    ``(role_token, columns)``.

    A flat table hides its relationships in its naming. ``shipper_code``,
    ``shipper_name``, ``consignee_code``, ``consignee_name`` is not six unrelated
    columns — it is two references to the same kind of entity, in two different
    roles, and that is the single strongest signal available for choosing between
    two object properties with the same range. Presented as a flat list, the model
    has to rediscover it from names alone on every call, and nothing stops it
    mapping both roles onto the same property.

    Grouping is deliberately conservative: shared leading token, at least
    :data:`MIN_ROLE_GROUP_COLUMNS` members, no more than
    :data:`MAX_ROLE_GROUP_SHARE` of the table, never a structural token like ``is``
    or ``created``, and at least one member that actually *identifies or names*
    something (:data:`_ENTITY_REFERENCE_TOKENS`). That last condition is what makes
    the rule precise: without it the live corpus produced groups like
    ``ActualDate``/``ActualTimeFrom`` and ``KmLoadingTotal``/``KmUnloadingTotal``,
    which share a prefix for reasons unrelated to entity identity. A false group is
    worse than none — it asserts a relationship the data does not have.

    Column order within a group, and group order, follow the input, which is
    already deterministic (DD-175).
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for col in columns:
        token = _leading_token(col.get("name", ""))
        if token and token not in _NON_ROLE_TOKENS:
            buckets.setdefault(token, []).append(col)

    ceiling = max(MIN_ROLE_GROUP_COLUMNS, int(len(columns) * MAX_ROLE_GROUP_SHARE))
    grouped_names: set[str] = set()
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for token, members in buckets.items():
        if not MIN_ROLE_GROUP_COLUMNS <= len(members) <= ceiling:
            continue
        if not any(_is_entity_reference(m.get("name", "")) for m in members):
            continue
        groups.append((token, members))
        grouped_names.update(str(m.get("name", "")) for m in members)

    ungrouped = [c for c in columns if str(c.get("name", "")) not in grouped_names]
    return groups, ungrouped


def _format_source_columns(columns: list[dict[str, Any]]) -> str:
    """Format source columns for the LLM prompt, within a per-table sample budget."""
    lines = []
    remaining = MAX_TABLE_SAMPLE_CHARS
    # Defence in depth: align_table chunks to this size before calling, so a caller
    # reaching this slice has bypassed the split and would otherwise silently drop
    # columns from the prompt.
    for col in columns[:MAX_COLUMNS_PER_PROMPT]:
        prompt_samples = _samples_for_column(col)
        samples_str = ", ".join(prompt_samples)
        if len(samples_str) > remaining:
            # Budget spent: keep enough to convey the type, drop the rest. Columns render
            # in source order, so this trims the tail rather than a chosen few.
            samples_str = ", ".join(prompt_samples[:MAX_SAMPLES_HIGH_CARDINALITY])
            if len(samples_str) > remaining:
                samples_str = ""
        remaining -= len(samples_str)
        samples_part = f" | samples: {samples_str}" if samples_str else ""
        lines.append(f"  - {col['name']} ({col.get('data_type', 'unknown')}){samples_part}")
    return "\n".join(lines)


def format_role_structure(columns: list[dict[str, Any]]) -> str:
    """Render the table's apparent role structure for the prompt (DD-179).

    Returns an empty string when no role group is found, so a table without this
    shape sends a byte-identical prompt to before.
    """
    groups, ungrouped = group_columns_by_role(columns[:MAX_COLUMNS_PER_PROMPT])
    if not groups:
        return ""

    lines = [
        "APPARENT ROLE STRUCTURE (derived from column naming, not declared):",
        "",
        "  Columns sharing a leading token usually describe ONE related entity in a",
        "  specific role. Treat each group as a unit: decide what entity it refers to,",
        "  then which property carries that role. Two DIFFERENT groups must NOT map to",
        "  the same object property — that is the signal telling them apart.",
        "",
    ]
    for token, members in groups:
        names = ", ".join(str(m.get("name", "")) for m in members)
        lines.append(f'  ROLE "{token}" ({len(members)} columns): {names}')
    if ungrouped:
        others = ", ".join(str(c.get("name", "")) for c in ungrouped)
        lines.append(f"  (no role group: {others})")
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
    """Keep semantically useful, bounded, **distinct** sample values for prompts.

    Deduplication matters more as the cap rises: showing "ACTIVE" twenty times says
    nothing that showing it once does not, and it crowds out the values that would have
    revealed the rest of the code list.
    """
    kept: list[str] = []
    seen: set[str] = set()
    for raw in samples:
        text = str(raw).strip()
        if _is_noisy_sample(text):
            continue
        clipped = _clip_sample_text(text)
        if clipped in seen:
            continue
        seen.add(clipped)
        kept.append(clipped)
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


#: Issue #517 — max value-object / related classes appended to the STEP-2 property
#: pool on top of the table shortlist. Sized like ``MAX_CROSS_MODULE_CLASSES``: enough
#: to carry an anchor's measurement objects (``Vessel`` reaches exactly three tonnage
#: classes through ``hasCapacity``) without letting one richly-linked class flood the
#: prompt with everything it points at.
MAX_VALUE_OBJECT_CLASSES = 8


def expand_value_object_pool(
    shortlist: list[dict[str, Any]],
    ref_classes: list[dict[str, Any]],
    *,
    anchor_class: str = "",
    max_classes: int = MAX_VALUE_OBJECT_CLASSES,
) -> list[dict[str, Any]]:
    """Return classes reachable one hop out as value objects (issue #517).

    Measurement/quantity value objects are the normal reference-model idiom: the
    entity carries an object property, and the *number* lives on a small class at
    the other end. ``imo/vessel-registry`` is the canonical shape —
    ``Vessel --hasCapacity--> VesselCapacity``, with ``GrossTonnage``,
    ``NetTonnage`` and ``DeadweightTonnage`` as its subclasses, each carrying the
    actual value (``grossTonnageValue``). ``Vessel`` itself carries none of them.

    The shortlist is a flat top-N lexical scoring over the whole domain, so on the
    real corpus those value objects lose to whatever else happens to share a token:
    for ``d_vyr_ship_s_archive`` the twelve selected classes were ``Vessel`` plus
    eleven certificate/security classes, and ``grossTonnageValue`` was never shown
    to the model at all. The column came back as ``no listed Vessel property
    corresponds to gross registered tonnage`` and became a false blueprint gap.

    Two hops are walked, and only two:

    * the **range class** of each object property on a shortlisted class, with its
      full property list;
    * that range class's **subclasses**, each contributing only its *own* asserted
      properties — the parent already supplies the inherited ones, and re-listing
      them turns a handful of specialisations into pages of identical prompt text.

    A candidate with nothing of its own to offer is skipped, which is what keeps
    this quiet: an abstract range class, or a subclass that only inherits, adds no
    vocabulary and so is not worth a prompt slot.

    *anchor_class* is walked first so the table's own anchor gets first claim on the
    budget. Everything is deterministic: shortlist order, then the (already sorted)
    property order, then subclasses by ``(name, uri)``.

    Returns only the **added** classes, each tagged ``_value_object_of``
    (``{"owner", "via"}``) so :func:`_format_ref_inventory` can name the route and
    the caller can tell an addition from a shortlist entry.
    """
    if max_classes <= 0:
        return []

    by_uri: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for cls in ref_classes:
        uri = str(cls.get("uri") or "")
        if uri:
            by_uri.setdefault(uri, cls)
        name = str(cls.get("name") or "")
        if name:
            by_name.setdefault(name, cls)

    def _key(cls: dict[str, Any]) -> str:
        return str(cls.get("uri") or "") or str(cls.get("name") or "")

    have = {_key(c) for c in shortlist}
    owners = sorted(
        shortlist, key=lambda c: 0 if str(c.get("name") or "") == anchor_class else 1
    )

    added: list[dict[str, Any]] = []
    seen: set[str] = set()
    for owner in owners:
        owner_name = str(owner.get("name") or "")
        for prop in owner.get("properties") or []:
            if str(prop.get("type") or "").lower() != "object":
                continue
            target = by_uri.get(str(prop.get("range_uri") or "")) or by_name.get(
                str(prop.get("range") or "")
            )
            if target is None:
                continue
            via = f"{owner_name}.{prop.get('name', '')}"

            # (candidate class, the properties it contributes). The range class
            # contributes everything it offers; a subclass contributes only what it
            # declares itself.
            chain: list[tuple[dict[str, Any], list[dict[str, Any]]]] = [
                (target, list(target.get("properties") or []))
            ]
            specs = sorted(
                target.get("specializations") or [],
                key=lambda s: (str(s.get("class") or ""), str(s.get("class_uri") or "")),
            )
            for spec in specs:
                spec_name = str(spec.get("class") or "")
                spec_uri = str(spec.get("class_uri") or "")
                resolved = by_uri.get(spec_uri) or {
                    "uri": spec_uri,
                    "name": spec_name,
                    "label": spec_name,
                    "comment": "",
                }
                chain.append((resolved, list(spec.get("properties") or [])))

            for candidate, own_properties in chain:
                key = _key(candidate)
                if not key or key in have or key in seen or not own_properties:
                    continue
                seen.add(key)
                entry = dict(candidate)
                entry["properties"] = own_properties
                # The range class's specialisations are appended as their own pool
                # entries above; rendering them again under the parent would say the
                # same thing twice.
                entry.pop("specializations", None)
                entry["_value_object_of"] = {"owner": owner_name, "via": via}
                added.append(entry)
                if len(added) >= max_classes:
                    return added
    return added


def build_class_property_index(
    ref_classes: list[dict[str, Any]],
) -> dict[str, frozenset[str]]:
    """Map each offered class name to the property names offered *on it* (#520).

    This is the structure issues #517 and #520 share. #517 widens the candidate pool
    with other classes' properties, which is exactly what makes #520's hazard worse:
    the strict schema's ``ref_property`` enum is one flat list for the whole schema,
    so it validates that a name exists *somewhere in the pool*, never that it exists
    on the class it is being assigned to. Recording the owner is what lets
    :func:`enforce_class_property_pairs` check the pair rather than the name.

    Keyed by *name* because a name is all the model returns. Same-named classes from
    different modules are unioned — ``tic/terminal-infrastructure#Terminal`` and
    ``tic/locations#Terminal`` are both in the ``terminal-operations`` pool and
    nothing in the response distinguishes them.
    """
    index: dict[str, set[str]] = {}
    for cls in ref_classes:
        name = str(cls.get("name") or "")
        if not name:
            continue
        bucket = index.setdefault(name, set())
        for prop in cls.get("properties") or []:
            prop_name = str(prop.get("name") or "")
            if prop_name:
                bucket.add(prop_name)
    return {name: frozenset(props) for name, props in index.items()}


def build_property_owner_index(
    pair_index: dict[str, frozenset[str]],
) -> dict[str, tuple[str, ...]]:
    """Invert :func:`build_class_property_index`: property name → owning classes."""
    owners: dict[str, set[str]] = {}
    for cls_name, props in pair_index.items():
        for prop in props:
            owners.setdefault(prop, set()).add(cls_name)
    return {prop: tuple(sorted(names)) for prop, names in owners.items()}


def enforce_class_property_pairs(
    alignments: list[dict[str, Any]],
    ref_classes: list[dict[str, Any]],
) -> tuple[int, int]:
    """Reject or repair ``(ref_class, ref_property)`` pairs absent from the pool (#520).

    DD-177's strict schema was meant to make an invalid proposal structurally
    impossible. It half-succeeded: a flat property enum makes an *invented* name
    impossible but leaves a real name on the wrong class fully representable, and
    that is the failure mode least likely to be caught downstream — the name is
    real, the enum accepted it, and only a human re-resolving the closure notices.
    Observed live: ``terminalName`` attached to a ``Terminal`` class that does not
    carry it, reported by the authoring agent as a hallucination it was not.

    Two outcomes, both deterministic:

    * **repaired** — the property exists on exactly one offered class. The property
      determines its own owner, so the class is corrected rather than the mapping
      thrown away. This is the common case and it *recovers* recall.
    * **rejected** — the property exists on no offered class, or on several and none
      of them is the one named. Nothing here can choose between them, so the column
      collapses to the canonical unmatched form (``alignment: custom``,
      ``ref_property`` cleared) with the discarded pair recorded in the rationale.
      An honest null beats a plausible wrong class that survives into an
      ``rdfs:subPropertyOf`` assertion.

    Deliberately *not* a retry: the enum already pins the property name, so a
    mismatch is a class-assignment slip, and re-rolling the whole table would
    re-litigate every mapping that was right to fix one that was not.

    Mutates *alignments* in place; returns ``(repaired, rejected)``.
    """
    pair_index = build_class_property_index(ref_classes)
    owner_index = build_property_owner_index(pair_index)

    repaired = 0
    rejected = 0
    for entry in alignments:
        if not isinstance(entry, dict) or entry.get("alignment") == "custom":
            continue
        prop = str(entry.get("ref_property") or "")
        cls_name = str(entry.get("ref_class") or "")
        if not prop or prop in pair_index.get(cls_name, frozenset()):
            continue
        owners = owner_index.get(prop, ())
        if len(owners) == 1:
            entry["ref_class"] = owners[0]
            repaired += 1
            continue
        entry["alignment"] = "custom"
        entry["ref_property"] = ""
        detail = (
            "none of the offered classes carries it"
            if not owners
            else f"it is carried by {', '.join(owners)}, not by '{cls_name}'"
        )
        entry["rationale"] = (
            f"Rejected wrong-class reference property '{prop}' on '{cls_name}': "
            f"{detail}. Original rationale: {entry.get('rationale', '') or '(none)'}"
        )
        rejected += 1
    return repaired, rejected


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
        index.setdefault(name, []).append(
            {
                "module": cls.get("module", ""),
                "source_uri": cls.get("source_uri", ""),
                "belongs_to_domains": list(cls.get("belongs_to_domains", [])),
                "is_home": bool(cls.get("is_home")),
            }
        )
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
    class_cautions: dict[str, str] | None = None,
    glossary_terms: list[str] | None = None,
    anchor_override: str | None = None,
    qualified_properties: bool = False,
) -> str:
    """Build the alignment prompt for one source table.

    Two-stage in a single call:
    1. Which reference class does this table best align to?
    2. For each column, which reference property is the best match?

    When *table_ref_classes* is provided (DD-070 cross-module mode), STEP 1 is
    constrained to those home-domain classes while STEP 2 may match properties on
    ANY class in *ref_classes* (the widened accelerator pool). Without it (default),
    both steps draw from *ref_classes* and the output is unchanged.

    When *anchor_override* is set (uri-anchor-contract / DD-185), STEP 1 is stated
    as decided rather than asked, and the affinity hint is dropped. Found on a live
    Langfuse trace: the prompt still said "prior analysis suggests 'Company'" while
    the run's fixed anchor was TradeParty — the model deliberated a question whose
    answer was pinned, against a hint contradicting it, and mapped columns toward
    its own pick.

    When *qualified_properties* is True (issue #520), ``ref_property`` is asked for
    as ``OwningClass.propertyName``, matching the qualified response-schema enum
    :func:`build_alignment_response_schema` emits when the pair vocabulary fits the
    provider budget. The prose and the enum must agree, so the caller passes
    whichever form the schema actually used rather than assuming one.
    """
    table_classes = table_ref_classes if table_ref_classes is not None else ref_classes

    # DD-171: the pattern library's normative cautions for the classes in play, and the
    # business's own vocabulary. Without these the aligner proposes source-shaped terms
    # that the model's own rules reject -- observed live, four role-as-boolean-flag
    # proposals on Contact in a single table.
    caution_block = ""
    relevant = sorted(
        {
            text
            for cls in table_classes
            for text in [(class_cautions or {}).get(str(cls.get("uri") or ""), "")]
            if text
        }
    )
    if relevant:
        bullet_lines = "\n".join(f"- {text}" for text in relevant)
        caution_block = (
            "\n\nPATTERN LIBRARY — normative cautions for these classes:\n"
            + bullet_lines
            + "\nDo NOT propose a role as a boolean flag or status string on these "
            "classes. Roles belong on a qualified role-assignment entity. If the source "
            "only has flags, say so in 'why' rather than proposing the flag as the model."
        )

    glossary_block = ""
    if glossary_terms:
        # Audited on a live trace: the flat dump put 'Vessel Departure' and
        # 'Postcode Zone' into a companies-table prompt. Keep only terms sharing
        # a token with this table's own name or columns — the ones the model
        # could actually use — with the full glossary still governing naming at
        # review time.
        table_tokens = _tokenize_text(table_name)
        for col in columns:
            table_tokens |= _tokenize_text(str(col.get("name", "")))
        relevant_terms = [t for t in glossary_terms if _tokenize_text(t) & table_tokens]
        if relevant_terms:
            glossary_block = (
                "\n\nBUSINESS VOCABULARY (use these words where one fits; they are the "
                "business's own terms):\n" + ", ".join(relevant_terms)
            )

    entity_hint = ""
    step1 = "STEP 1: Determine which reference model class this table best represents."
    likely_match = ""
    if anchor_override:
        # The anchor is already decided (human-confirmed alias or global anchor
        # call); asking STEP 1 again wastes reasoning and risks the model mapping
        # columns toward a different class than the one that will be recorded.
        step1 = (
            f"STEP 1 (already decided): this table IS '{anchor_override}'. Do not "
            f"reconsider the class. Set ref_class to '{anchor_override}' and map "
            f"every column with that anchor fixed, using properties of "
            f"'{anchor_override}' or of any other listed class where the column "
            f"genuinely belongs to a related entity."
        )
        likely_entity = ""
    if likely_entity:
        # CR-2: when the affinity step already derived the entity and it matches a
        # candidate class, anchor STEP 1 on it instead of re-deriving from scratch.
        likely_match = next(
            (
                c["name"]
                for c in table_classes
                if str(c["name"]).lower() == str(likely_entity).lower()
            ),
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
    # DD-179: blank line either side when present; empty string when no role group
    # was found, so a table without this shape keeps its previous prompt exactly.
    role_block = format_role_structure(columns)
    role_structure = f"\n{role_block}\n" if role_block else ""

    class_names = ", ".join(c["name"] for c in table_classes)
    semantic_records = [c.get("_semantic", {}) for c in ref_classes]
    modules = sorted(
        {
            str(item.get("source_identity"))
            for item in semantic_records
            if item.get("source_identity")
        }
    )
    # DD-172: this block used to carry closure hashes, the selection rule, an
    # import-complete boolean and "omitted modules: none in this prompt slice" —
    # provenance for a human debugging a run, not anything a model can act on, repeated
    # in every prompt and competing for attention with the classes it is meant to read.
    # Only the module list survives, and only when it says something.
    semantic_disclosure = (
        f"REFERENCE MODULES IN SCOPE: {', '.join(modules)}\n" if modules else ""
    )

    # Issue #517: the value-object pool also splits STEP 1 from STEP 2, so
    # ``table_ref_classes is not None`` no longer implies cross-module mode. Gate on
    # the thing the note actually describes — a class tagged '[module: X]' — so a
    # home-only run is never told to read markers that are not there.
    cross_module_note = ""
    ref_module_field = ""
    if table_ref_classes is not None and any(str(c.get("module") or "") for c in ref_classes):
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

    # Issue #517: name the idiom explicitly. Left empty when the pool has no value
    # objects, so those prompts stay byte-identical.
    value_object_note = ""
    if any(c.get("_value_object_of") for c in ref_classes):
        value_object_note = (
            "\nVALUE OBJECTS: classes marked '[VALUE OBJECT / RELATED ENTITY reached "
            "from <Class>.<property>]' hold measurements and identifiers that the "
            "linking class does not carry itself — a gross-tonnage column belongs on "
            "GrossTonnage.grossTonnageValue, not nowhere. Map a column to one of these "
            "when it is genuinely that measurement, and never report such a column as "
            "unmatched merely because the table's own class does not list it.\n"
        )

    # Issue #520: the schema enum and the prose must ask for the same token shape.
    ref_property_hint = "<real reference property name, or null if alignment is custom>"
    property_format_note = ""
    if qualified_properties:
        ref_property_hint = (
            "<OwningClass.propertyName exactly as listed above, or null if custom>"
        )
        property_format_note = (
            "\n- PROPERTY NAMING: give ref_property as '<OwningClass>.<propertyName>', using "
            "the CLASS heading the property is listed under above (e.g. "
            "'GrossTonnage.grossTonnageValue'). A property name is only valid on the class "
            "that declares it; qualifying it with any other class is rejected."
        )

    return f"""Align this source database table to the reference model.

{step1}
STEP 2: For each source column, find the best matching reference model property.
{entity_hint}{caution_block}{glossary_block}{cross_module_note}{value_object_note}
{semantic_disclosure}
SOURCE TABLE: {table_name}
COLUMNS:
{source_cols}
{role_structure}
REFERENCE MODEL CLASSES AND PROPERTIES:
{ref_inventory}

Instructions:
- For ref_class, choose the ONE class from the reference model that best represents
  this table. It must be one of: {class_names}.
  If NONE of these classes genuinely fits this table, set ref_class to null (do NOT
  force-fit a table onto an unrelated class — a wrong anchor is worse than none).
- For each column, find the best matching property from ANY reference class
  (not limited to the table's primary class).
- alignment values: "exact" (same concept and name), "semantic" (same concept,
  different name), "partial" (related but not equivalent), "custom" (no match).
- CRITICAL — unmatched columns: when a column has no genuine reference-model
  property, set alignment to "custom", ref_property to null, and (optionally) a
  short free-text "note" describing the concept. Do NOT invent a camelCase property
  name for "ref_property", and NEVER reuse one suggested name across several unrelated
  columns — a confident-but-wrong guess (e.g. mapping many different columns all onto
  "stageCode" or "customsID") is worse than an honest null.
- SEPARATELY, for a custom column that carries real business meaning, you MAY fill
  "proposed_local_property": a property the hub should define for itself because the
  reference model has none. This is NOT a reference property and must never be used as
  ref_property; it is a proposal for a human to accept or reject at design time.
  Give {{"name": "<lowerCamelCase>", "range": "<xsd type or class name>",
  "on_class": "<the class this property belongs on>", "why": "<one line>"}}.
  Omit it (null) for an audit stamp, a surrogate key, a vendor placeholder, or anything
  whose meaning you cannot state — an unnecessary proposal costs a reviewer more than a
  missing one. Never emit an IRI here; the hub mints that itself.
- OBJECT PROPERTIES: a property marked [OBJECT PROPERTY] links to another entity; a
  flat source column can never BE one. When a column (or a cluster of columns like
  street/city/postcode) is clearly the content of the entity an object property points
  at, do NOT map it to that object property and do NOT call it unmatched. Set
  ref_property to null and use "proposed_local_property" with
  "range": "<the target class name>" and "why" naming the object property it should be
  reached through. That records "this belongs behind hasBillingAddress → Address"
  rather than losing it.
- Do NOT over-map: a real ref_property must come from the class's listed properties
  above. Never map more distinct columns onto a class than it has properties.
- ref_class_confidence: 0.0-1.0 for the table→class match.{property_format_note}

Respond with JSON only:
{{
  "ref_class": "<class name or null>",
  "ref_class_confidence": 0.0-1.0,
  "column_alignments": [
    {{
      "column": "<source column name>",
      "ref_class": "<class name that owns this property, or null if custom>",{ref_module_field}
      "ref_property": "{ref_property_hint}",
      "alignment": "exact|semantic|partial|custom",
      "confidence": 0.0-1.0,
      "note": "<optional: short concept description for a custom column>",
      "proposed_local_property": null,
      "rationale": "brief explanation"
    }}
  ]
}}"""


#: Provider ceiling on enum values *in total across one schema* (DD-177).
#:
#: Measured against the live endpoint by bisection: 999 accepted, 1,000
#: rejected with "Expected at most 1000 enum values in total within a single
#: schema". "In total" is the trap — the class enum is emitted twice (once for
#: the table's own class, once inside the reusable column verdict), the
#: alignment kinds cost four, and every nullable enum carries its own ``null``.
#: A fixed per-enum cap therefore overshoots; the property budget is whatever
#: is left once the rest of the schema is paid for.
TOTAL_SCHEMA_ENUM_BUDGET = 999

#: Headroom kept below the provider limit, so a schema close to the ceiling is
#: not rejected outright by a future change in how the provider counts.
SCHEMA_ENUM_SAFETY_MARGIN = 20

#: The four alignment kinds a column verdict may carry.
ALIGNMENT_KINDS = ("exact", "semantic", "partial", "custom")

#: Version of the *candidate pool contract* — which classes' properties are offered
#: to the model, and how a proposed ``(class, property)`` pair is validated.
#:
#: Folded into both the per-table cache key and the domain freshness hash. Issues
#: #517 and #520 change what the model can see and what survives validation, so an
#: on-disk alignment produced before them is not merely older, it is answering a
#: narrower question — reusing it would keep serving the false gaps this fixes.
#: Bump whenever the pool or the pair check changes.
ALIGNMENT_POOL_CONTRACT = 2


def qualified_property_names(ref_classes: list[dict[str, Any]]) -> list[str]:
    """Render the pool as ``ClassName.propertyName`` tokens (issue #520)."""
    return sorted(
        {
            f"{cls['name']}.{prop['name']}"
            for cls in ref_classes
            if cls.get("name")
            for prop in (cls.get("properties") or [])
            if prop.get("name")
        }
    )


def schema_uses_qualified_properties(response_format: dict[str, Any]) -> bool:
    """Whether the built schema's ``ref_property`` enum carries qualified pairs.

    The prompt has to ask for the same token shape the enum accepts, and only the
    schema builder knows which tier the budget allowed. Reading the answer back off
    the schema keeps that single source of truth instead of re-deriving the budget
    arithmetic at the call site. A bare property name never contains a dot, so the
    test is unambiguous.
    """
    try:
        verdict = response_format["json_schema"]["schema"]["$defs"]["ColumnVerdict"]
        values = verdict["properties"]["ref_property"].get("enum") or []
    except (KeyError, TypeError):
        return False
    return any(isinstance(v, str) and "." in v for v in values)


def build_alignment_response_schema(
    column_names: list[str],
    class_names: list[str],
    property_names: list[str],
    *,
    qualified_properties: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Build a strict response schema for one table's alignment (DD-177).

    Returns ``(response_format, notes)``, where *notes* records any constraint
    that had to be relaxed — a dropped enum is reported, never silent.

    The point is the *shape*, not validation. Under plain JSON mode the model
    may simply omit a column it has no opinion about, and measurement shows
    which columns it omits drifts between runs: three identical runs of the
    party domain mapped 24, 22 and 23 columns with **zero** disagreement about
    what the shared columns meant. The instability was entirely in what the
    model chose to answer for.

    So ``column_alignments`` is an object keyed by column name with every key
    ``required`` and ``additionalProperties`` false, rather than an array.
    Omitting a column then violates the schema: the model must return a verdict
    for each one, even if that verdict is "no reference property fits". It also
    rules out a duplicated or invented column name for free.

    Enums pin ``ref_property`` and ``ref_class`` to terms that actually exist,
    which makes a hallucinated property unrepresentable rather than caught
    afterwards by ``normalize_local_proposal`` (DD-170). Classes are budgeted
    first because they are the smaller vocabulary and anchor the table; the
    property enum takes what remains of
    :data:`TOTAL_SCHEMA_ENUM_BUDGET`. An enum that does not fit is dropped and
    the field falls back to a free string — reported in *notes*, never silent,
    and the downstream validation still runs, so this weakens the constraint
    rather than the correctness of the result.

    Issue #520: a flat property enum only proves a name exists *somewhere* in the
    pool, never that it exists on the class it is assigned to, so a real name on the
    wrong class validates cleanly. Passing *qualified_properties* (``Class.property``
    tokens from :func:`qualified_property_names`) makes the pair itself the enum
    member, which is the structural fix rather than a check after the fact. It is
    tried first and costs more — measured over all seventeen domains of a real
    75-table hub, the widest (``booking``: 215 classes, 378 pairs) costs 803 of the
    975 available, and every domain fits — so the degradation is three-tier rather
    than two: qualified pairs, then bare names, then a free string. Whenever the
    bare enum would have fitted it still does, and
    :func:`enforce_class_property_pairs` covers the lower two tiers.
    """
    notes: list[str] = []
    budget = TOTAL_SCHEMA_ENUM_BUDGET - SCHEMA_ENUM_SAFETY_MARGIN - len(ALIGNMENT_KINDS)

    def fit(values: list[str], *, copies: int = 1) -> tuple[dict[str, Any] | None, int, int]:
        """Cost an enum against the shared budget without spending it.

        Returns ``(field or None, cost, distinct value count)``. *copies* is how many
        times this enum appears in the finished schema: the provider counts every
        occurrence, and ``$ref`` does not help because the limit is on values
        emitted, not on distinct definitions.
        """
        unique = sorted({v for v in values if v})
        if not unique:
            return None, 0, 0
        cost = (len(unique) + 1) * copies  # +1 for the null each enum carries
        if cost > budget:
            return None, cost, len(unique)
        return {"type": ["string", "null"], "enum": [*unique, None]}, cost, len(unique)

    def enum_field(values: list[str], label: str, *, copies: int = 1) -> dict[str, Any]:
        """A nullable string, enum-constrained while the shared budget allows."""
        nonlocal budget
        field_, cost, count = fit(values, copies=copies)
        if field_ is None:
            if count:
                notes.append(
                    f"{label} enum dropped: {count} values cost {cost} against "
                    f"{budget} remaining of the provider's "
                    f"{TOTAL_SCHEMA_ENUM_BUDGET}-value schema budget; the model may "
                    f"name a term that does not exist."
                )
            return {"type": ["string", "null"]}
        budget -= cost
        return field_

    # Classes are emitted twice (table anchor + column verdict), so they are
    # costed once at double and the same field object is reused for both.
    class_field = enum_field(class_names, "ref_class", copies=2)

    property_field: dict[str, Any] | None = None
    if qualified_properties:
        fitted, cost, count = fit(qualified_properties)
        if fitted is not None:
            budget -= cost
            property_field = fitted
        else:
            notes.append(
                f"ref_property enum not qualified: {count} Class.property pairs cost "
                f"{cost} against {budget} remaining of the provider's "
                f"{TOTAL_SCHEMA_ENUM_BUDGET}-value schema budget; falling back to "
                f"unqualified names, so a wrong-class pair is caught by "
                f"post-validation instead of by the schema."
            )
    if property_field is None:
        property_field = enum_field(property_names, "ref_property")

    verdict = {
        "type": "object",
        "properties": {
            "ref_class": dict(class_field),
            "ref_property": property_field,
            "alignment": {"type": "string", "enum": list(ALIGNMENT_KINDS)},
            "confidence": {"type": "number"},
            "note": {"type": ["string", "null"]},
            "proposed_local_property": {"type": ["string", "null"]},
            "rationale": {"type": "string"},
        },
        # strict mode requires every property to be listed as required; an
        # optional field is expressed as nullable, not as an absent key.
        "required": [
            "ref_class",
            "ref_property",
            "alignment",
            "confidence",
            "note",
            "proposed_local_property",
            "rationale",
        ],
        "additionalProperties": False,
    }

    columns = list(dict.fromkeys(column_names))
    schema = {
        # $defs/$ref keeps one copy of the verdict shape. Inlining it per column
        # blows the provider's total-schema-size limit at realistic table widths.
        "$defs": {"ColumnVerdict": verdict},
        "type": "object",
        "properties": {
            "ref_class": dict(class_field),
            "ref_class_confidence": {"type": "number"},
            "column_alignments": {
                "type": "object",
                "properties": {c: {"$ref": "#/$defs/ColumnVerdict"} for c in columns},
                "required": columns,
                "additionalProperties": False,
            },
        },
        "required": ["ref_class", "ref_class_confidence", "column_alignments"],
        "additionalProperties": False,
    }
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "column_alignment", "strict": True, "schema": schema},
    }
    return response_format, notes


def normalize_schema_response(result: dict[str, Any]) -> dict[str, Any]:
    """Convert an object-keyed ``column_alignments`` back to the list shape (DD-177).

    The strict schema keys verdicts by column name so omission is impossible;
    every consumer downstream expects the historical list of dicts each carrying
    its own ``column``. Converting here keeps that contract, so the schema is a
    change to how the answer is *obtained*, not to how it is read.

    A response already in list form passes through untouched, which is what
    happens when the model rejected the schema and fell back to JSON mode.
    """
    alignments = result.get("column_alignments")
    if not isinstance(alignments, dict):
        return result
    converted = [
        {"column": name, **verdict}
        for name, verdict in alignments.items()
        if isinstance(verdict, dict)
    ]
    return {**result, "column_alignments": converted}


#: Flag raised when two distinct role groups collapse onto one object property.
FLAG_ROLE_COLLISION = "role-collision"


def flag_role_collisions(
    columns: list[dict[str, Any]],
    alignments: list[dict[str, Any]],
) -> list[str]:
    """Flag distinct role groups mapped onto the same property (DD-179).

    The relational check the prompt cannot enforce. If ``shipper_code`` and
    ``consignee_code`` both land on ``hasShipper``, one of them is wrong — and it
    is wrong in a way that reads as plausible in isolation, because each mapping
    is individually defensible. Only looking at the set reveals it.

    Flags, never blocks: two roles legitimately share a property when the model
    is genuinely coarser than the source (a single ``hasParty`` where the source
    tracks shipper and consignee separately), and that is a design decision for a
    human, not an error to reject automatically.

    Only the *shared leading token* defines a role here, so this cannot fire on
    columns that merely happen to map alike.
    """
    groups, _ = group_columns_by_role(columns)
    if len(groups) < 2:
        return []

    role_of = {
        str(member.get("name", "")): token for token, members in groups for member in members
    }
    property_roles: dict[str, set[str]] = {}
    for entry in alignments:
        if not isinstance(entry, dict):
            continue
        prop = entry.get("ref_property")
        role = role_of.get(str(entry.get("column", "")))
        if prop and role:
            property_roles.setdefault(str(prop), set()).add(role)

    return [
        f"{FLAG_ROLE_COLLISION}: roles {sorted(roles)} both map to '{prop}' — "
        f"distinct roles sharing one property loses the distinction the source makes; "
        f"confirm the model is deliberately coarser, or split the property."
        for prop, roles in sorted(property_roles.items())
        if len(roles) > 1
    ]


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
    anchor_override: str | None = None,
    anchor_status: str = "confirmed",
    anchor_confidence: float | None = None,
    class_cautions: dict[str, str] | None = None,
    glossary_terms: list[str] | None = None,
    trace_session_id: str = "",
) -> dict[str, Any]:
    """Align one source table, splitting across calls when it is too wide.

    ``MAX_COLUMNS_PER_PROMPT`` used to *truncate*: a table's columns beyond the cap were
    silently never shown to the model, so they could never be mapped and never appeared
    as orphans either — they simply were not assessed. With real tables running to 121
    columns that is a coverage hole disguised as a clean result.

    Wide tables are now split into successive calls and the column alignments merged.
    Chunks after the first are pinned to the first chunk's ``ref_class`` via
    ``anchor_override``, because a chunk of trailing columns has no way to recognise the
    table's identity on its own and would otherwise be free to pick a different class
    for the same table.

    The table-level verdict comes from the first chunk, which holds the identifying
    columns; later chunks contribute only column alignments.
    """
    chunk_size = MAX_COLUMNS_PER_PROMPT
    if len(columns) <= chunk_size:
        return _align_table_once(
            client,
            model,
            table_name,
            columns,
            ref_classes,
            likely_entity,
            table_ref_classes=table_ref_classes,
            anchor_override=anchor_override,
            anchor_status=anchor_status,
            anchor_confidence=anchor_confidence,
            class_cautions=class_cautions,
            glossary_terms=glossary_terms,
            trace_session_id=trace_session_id,
        )

    chunks = [columns[i : i + chunk_size] for i in range(0, len(columns), chunk_size)]
    logger.info(
        "Table %s has %d columns; splitting alignment across %d calls",
        table_name,
        len(columns),
        len(chunks),
    )

    merged = _align_table_once(
        client,
        model,
        table_name,
        chunks[0],
        ref_classes,
        likely_entity,
        table_ref_classes=table_ref_classes,
        anchor_override=anchor_override,
        anchor_status=anchor_status,
        anchor_confidence=anchor_confidence,
        class_cautions=class_cautions,
        glossary_terms=glossary_terms,
        trace_session_id=trace_session_id,
    )
    pinned = anchor_override or merged.get("ref_class")
    for chunk in chunks[1:]:
        part = _align_table_once(
            client,
            model,
            table_name,
            chunk,
            ref_classes,
            likely_entity,
            table_ref_classes=table_ref_classes,
            anchor_override=pinned,
            anchor_status=anchor_status,
            anchor_confidence=anchor_confidence,
            class_cautions=class_cautions,
            glossary_terms=glossary_terms,
            trace_session_id=trace_session_id,
        )
        merged["column_alignments"].extend(part.get("column_alignments") or [])
        # A failure in any chunk is a failure for the table: the alternative is
        # reporting a partial column set as if it were complete.
        if part.get("generation_outcome") != OUTCOME_SEMANTIC_SUCCESS:
            merged["generation_outcome"] = part.get("generation_outcome")
            merged["generation_error"] = part.get("generation_error")
    return merged


def _align_table_once(
    client,
    model: str,
    table_name: str,
    columns: list[dict[str, Any]],
    ref_classes: list[dict[str, Any]],
    likely_entity: str = "",
    *,
    table_ref_classes: list[dict[str, Any]] | None = None,
    anchor_override: str | None = None,
    anchor_status: str = "confirmed",
    anchor_confidence: float | None = None,
    class_cautions: dict[str, str] | None = None,
    glossary_terms: list[str] | None = None,
    trace_session_id: str = "",
) -> dict[str, Any]:
    """Run LLM alignment for one source table against reference model classes.

    Returns normalized dict with ref_class, ref_class_confidence, column_alignments.

    When *table_ref_classes* is given (DD-070 cross-module mode), the table's
    ``ref_class`` is validated against those home classes while each column's
    ``ref_class`` may be any class in *ref_classes* (the widened pool); a per-column
    ``ref_module`` is captured when the model supplies one.

    uri-anchor-contract: when *anchor_override* is given (a class name resolved
    from a confirmed discovery alias/URI — see ``anchor_resolution.py``), it wins
    over whatever class name the model proposes: the table's anchor is human-
    confirmed evidence, not a similarity guess, so it is never re-litigated by
    the LLM's own (possibly different) opinion. The LLM call still runs so
    columns are aligned to properties of the confirmed class.
    """
    if not ref_classes:
        return {
            "ref_class": "",
            "ref_class_confidence": 0.0,
            "column_alignments": [],
            "generation_outcome": OUTCOME_FALLBACK_ONLY,
        }

    table_classes = table_ref_classes if table_ref_classes is not None else ref_classes
    valid_classes = {c["name"] for c in table_classes}
    pool_class_names = {str(c.get("name") or "") for c in ref_classes if c.get("name")}

    # DD-177: constrain the answer's shape, not just its syntax. Property and
    # class names are drawn from the same inventory the prompt renders, so the
    # enum and the prose cannot disagree. Issue #520: prefer qualified
    # ``Class.property`` enum members, which make a wrong-class pair
    # unrepresentable rather than merely detectable.
    response_format, schema_notes = build_alignment_response_schema(
        [str(c.get("name", "")) for c in columns if c.get("name")],
        [str(c.get("name", "")) for c in ref_classes if c.get("name")],
        [
            str(p.get("name", ""))
            for c in ref_classes
            for p in (c.get("properties") or [])
            if p.get("name")
        ],
        qualified_properties=qualified_property_names(ref_classes),
    )
    for note in schema_notes:
        logger.info("Alignment schema for %s: %s", table_name, note)

    # Built after the schema so the prose asks for whichever token shape the
    # budget actually allowed.
    prompt = build_alignment_prompt(
        table_name,
        columns,
        ref_classes,
        likely_entity,
        table_ref_classes=table_ref_classes,
        class_cautions=class_cautions,
        glossary_terms=glossary_terms,
        anchor_override=anchor_override,
        qualified_properties=schema_uses_qualified_properties(response_format),
    )

    generation_outcome = OUTCOME_SEMANTIC_SUCCESS
    generation_error: str | None = None
    try:
        response = call_with_backoff(
            lambda: create_chat_completion(
                client,
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert ontologist. You align source database columns "
                            "to reference model classes and properties based on semantic "
                            "meaning, not just name similarity. Always respond with valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                seed=resolve_ai_seed(ROLE_ALIGNMENT),
                reasoning_effort=resolve_reasoning_effort(ROLE_ALIGNMENT),
                response_format=response_format,
                # A model that cannot honour the schema must still be asked for
                # JSON, rather than losing the constraint we already had.
                param_fallbacks={"response_format": {"type": "json_object"}},
                # DD-184: verb-first and stable, so it stays filterable; the table
                # and the pass number are metadata, not part of the name.
                trace_name="align-table",
                trace_metadata=call_metadata(
                    trace_session_id,
                    ROLE_ALIGNMENT,
                    table=table_name,
                    source_columns=len(columns),
                    candidate_classes=len(table_classes),
                    anchor_override=anchor_override or "",
                    likely_entity=likely_entity,
                    schema_enum_notes=schema_notes,
                ),
            )
        )
        result = normalize_schema_response(json.loads(response.choices[0].message.content))
    except Exception as e:
        logger.warning("LLM alignment failed for table %s: %s", table_name, e)
        result = {}
        generation_outcome = OUTCOME_PROVIDER_FAILURE
        generation_error = sanitize_provider_error(e)

    if not isinstance(result, dict):
        result = {}

    # Validate ref_class
    proposed_ref_class = str(result.get("ref_class", "") or "")
    ref_class = proposed_ref_class
    # WS6 (issue #182): record anchor provenance so a hallucinated/rejected class is
    # reported rather than silently blanked.
    ref_class_status = "matched"
    rejected_ref_class = None
    if anchor_override:
        # uri-anchor-contract: a confirmed URI/alias anchor always wins — the
        # model's own class pick (matched/fallback/rejected/unmatched) is
        # simply not consulted for the *anchor* decision once confirmed
        # evidence exists (it is still used for column-level property
        # alignment below).
        #
        # DD-185: a global-anchor-call override travels the same path but is
        # recorded as status "anchored" with its own confidence, never as
        # "confirmed" — confirmed means a human decided, and an artifact must
        # not claim review that did not happen.
        ref_class = anchor_override
        ref_class_status = anchor_status
        ref_class_confidence = 1.0 if anchor_confidence is None else float(anchor_confidence)
    elif not proposed_ref_class:
        ref_class_status = "unmatched"
        ref_class_confidence = _clamp_confidence(result.get("ref_class_confidence", 0.0))
    elif proposed_ref_class not in valid_classes:
        # CR-2: fall back to the affinity-derived entity when it is a valid class,
        # rather than blanking it — we trust the prior analysis as a strong default.
        likely_match = next(
            (
                c["name"]
                for c in table_classes
                if str(c["name"]).lower() == str(likely_entity).lower()
            ),
            "",
        )
        ref_class = likely_match
        rejected_ref_class = proposed_ref_class
        ref_class_status = "fallback" if likely_match else "rejected"
        ref_class_confidence = _clamp_confidence(result.get("ref_class_confidence", 0.0))
    else:
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
        ref_property = str(ca.get("ref_property", "") or "")
        col_ref_class = str(ca.get("ref_class", ref_class) or ref_class)
        # Issue #520: a qualified ``Class.property`` answer carries its own owner,
        # and the owner it names is the authoritative one — the point of the
        # qualified enum is that the pair travels as a single token. Split it back
        # into the historical two fields so nothing downstream has to know.
        if "." in ref_property:
            owner, _, bare = ref_property.partition(".")
            if bare and owner in pool_class_names:
                col_ref_class, ref_property = owner, bare
        # WS-NORM (issue #182): canonical state model. The pipeline's single
        # discriminator is ``alignment == "custom"``; a "mapped" alignment with no
        # ``ref_property`` is contradictory (it cannot be counted as a real map),
        # so collapse it to the unmatched/custom form deterministically.
        if alignment != "custom" and not ref_property:
            alignment = "custom"
        norm: dict[str, Any] = {
            "column": col_name,
            "ref_class": col_ref_class,
            "ref_property": ref_property,
            "alignment": alignment,
            "confidence": _clamp_confidence(ca.get("confidence", 0.0)),
            "rationale": str(ca.get("rationale", "") or ""),
        }
        # WS7 (issue #182): for an unmatched column the model may return a short
        # free-text ``note`` instead of inventing a property name; carry it through.
        note = str(ca.get("note", "") or "").strip()
        if note:
            norm["note"] = note
        proposal = normalize_local_proposal(ca.get("proposed_local_property"))
        if proposal:
            norm["proposed_local_property"] = proposal
        # DD-070: carry the model's sibling-module signal only when present, so the
        # normalized result (and per-table cache) stays identical in default mode.
        ref_module = str(ca.get("ref_module", "") or "")
        if ref_module:
            norm["ref_module"] = ref_module
        alignments.append(norm)

    # Issue #520: the deterministic backstop. A no-op when the qualified enum was in
    # force; the whole guarantee when it was not (budget overflow, or the provider
    # rejecting the schema and falling back to plain JSON mode).
    repaired, rejected = enforce_class_property_pairs(alignments, ref_classes)
    if repaired or rejected:
        logger.warning(
            "Alignment for %s: %d wrong-class propert%s reassigned to their owning "
            "class, %d rejected as unmatched (no single owner in the candidate pool).",
            table_name,
            repaired,
            "y" if repaired == 1 else "ies",
            rejected,
        )

    return {
        "ref_class": ref_class,
        "ref_class_confidence": ref_class_confidence,
        "ref_class_status": ref_class_status,
        "rejected_ref_class": rejected_ref_class,
        "column_alignments": alignments,
        "generation_outcome": generation_outcome,
        "generation_error": generation_error,
    }


def _clamp_confidence(val: Any) -> float:
    """Clamp a value to [0.0, 1.0] float."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def _normalize_property_token(name: str) -> str:
    """Lower-cased alphanumeric token of a property/column name for similarity."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _source_column_digest(columns: list[dict[str, Any]]) -> tuple[int, str]:
    """Return ``(count, sha256)`` for a table's full source column set (F6).

    Deterministic and independent of prompt truncation: the digest is computed
    over the sorted source column *names* so a later omission (or a source-vocab
    drift) is detectable at ``check-claims`` time. Empty input yields ``(0, "")``.
    """
    names = sorted(str(c.get("name", "") or "") for c in columns)
    if not any(names):
        return 0, ""
    h = hashlib.sha256()
    h.update("\n".join(names).encode("utf-8"))
    return len(columns), h.hexdigest()


def _build_reconciled_passthrough(column: dict[str, Any]) -> dict[str, Any]:
    """Build a passthrough custom column for a source column the LLM never returned.

    F6 (toolkit-optimizations): prompt truncation (``MAX_COLUMNS_PER_PROMPT``) — or
    a model that simply omits a column — can drop source columns before they reach
    the Claim Registry, making a registry look complete when it is not. To keep the
    governance gate honest, every unaccounted source column is materialized as a
    deterministic passthrough candidate carrying an explicit
    ``reconciled_omission`` marker, so it enters custom-column triage instead of
    silently vanishing. ``disposition`` is left ``None`` for the Checkpoint-3b
    triage; ``suggested_property`` is ``None`` (the column was never analysed).
    """
    name = str(column.get("name", "") or "")
    return {
        "column": name,
        "data_type": str(column.get("data_type", "") or "unknown"),
        "suggested_property": None,
        "confidence": 0.0,
        "rationale": (
            "Source column not returned by the alignment model (beyond the prompt "
            "column cap or omitted); reconciled as a passthrough candidate so it is "
            "not silently dropped from the Claim Registry."
        ),
        "recommended_disposition": recommend_disposition(name),
        "disposition": None,
        "disposition_source": "",
        "reconciled_omission": True,
    }


def _build_object_property_passthrough(
    column: str,
    data_type: str,
    ref_property: str,
    target: dict[str, Any],
    *,
    reason: str = "unresolved_target",
) -> dict[str, Any]:
    """Build a passthrough custom column for a downgraded object-property map (F3).

    A scalar column that the model attached to an object property with no
    resolvable governed target is retained here as passthrough *evidence* (never
    lost) while its governed disposition moves to the relationship candidate — so
    the column is counted exactly once.

    ``reason`` (proposal-quality) documents *why* the map was downgraded —
    ``"unresolved_target"`` (default, pre-existing F3 behaviour, byte-identical
    rationale), ``"technical_actor"``, ``"missing_identifier_evidence"``, or
    ``"missing_typed_role_evidence"``.
    """
    rationale = (
        f"Scalar column was mapped to object property '{ref_property}' whose "
        "target entity does not resolve to a governed class; retained as "
        "passthrough evidence while the relationship is modelled separately."
    )
    if reason == "technical_actor":
        rationale = (
            f"Column looks like a technical/audit actor reference (e.g. "
            f"created_by/updated_by) rather than a business-entity identity; "
            f"object property '{ref_property}' is downgraded to audit/"
            "passthrough evidence by default (proposal-quality)."
        )
    elif reason == "missing_identifier_evidence":
        rationale = (
            f"Column was mapped to object property '{ref_property}' but shows "
            "no target/entity identifier evidence (name or data type); retained "
            "as passthrough evidence pending confirmation (proposal-quality)."
        )
    elif reason == "missing_typed_role_evidence":
        rationale = (
            f"Column was mapped to specialized location property "
            f"'{ref_property}' without explicit typed-role evidence in the "
            "column name; retained as passthrough evidence pending confirmation "
            "(proposal-quality)."
        )
    return {
        "column": column,
        "data_type": data_type or "unknown",
        "suggested_property": None,
        "confidence": 0.0,
        "rationale": rationale,
        "recommended_disposition": recommend_disposition(column),
        "disposition": None,
        "disposition_source": "",
        "object_property_passthrough": True,
        "object_property": ref_property,
    }


def _build_object_property_candidate(
    table_name: str,
    column: str,
    ref_property: str,
    target: dict[str, Any],
    *,
    reason: str = "unresolved_target",
) -> dict[str, Any]:
    """Build a relationship candidate for an unresolved object-property map (F3)."""
    target_name = target.get("target_name") or ""
    target_phrase = f" to a '{target_name}'" if target_name else ""
    rationale = (
        f"Scalar column '{column}' was aligned to object property "
        f"'{ref_property}'{target_phrase}, but no governed target class "
        "resolves. Model the relationship to a governed target node and keep "
        "the scalar column as passthrough evidence."
    )
    if reason == "missing_identifier_evidence":
        rationale = (
            f"Scalar column '{column}' was aligned to object property "
            f"'{ref_property}'{target_phrase}, but shows no target/entity "
            "identifier evidence. Confirm the source column actually "
            "references another entity before modelling the relationship "
            "(proposal-quality)."
        )
    elif reason == "missing_typed_role_evidence":
        rationale = (
            f"Scalar column '{column}' was aligned to specialized location "
            f"property '{ref_property}'{target_phrase}, but the column name "
            "gives no explicit typed-role evidence for that role. Confirm the "
            "role before modelling a specialized location relationship "
            "(proposal-quality)."
        )
    return {
        "type": "object_property_relationship_candidate",
        "source_table": table_name,
        "source_columns": [column],
        "suggested_relationship": ref_property,
        "target_concept": target_name,
        "target_class_uri": target.get("target_class_uri"),
        "target_resolved": bool(target.get("target_resolved")),
        "cardinality": target.get("cardinality", "n:1"),
        "requires_human_confirmation": True,
        "rationale": rationale,
    }


def _build_custom_column(
    ca: dict[str, Any],
    col_data_type: str,
    *,
    confidence_floor: float,
) -> dict[str, Any]:
    """Build one canonical *custom* (unmatched) column entry (issue #182).

    WS-NORM canonical form: an unmatched source column carries a *suggested*
    property only when the model is confident enough to be trusted; below
    ``confidence_floor`` the suggestion is dropped (``suggested_property: None``)
    rather than emitting a confident-but-wrong guess (Problem 1). ``disposition``
    is left ``None`` for the Checkpoint-3b triage (issue #164).
    """
    confidence = _clamp_confidence(ca.get("confidence", 0.0))
    suggested = str(ca.get("ref_property", "") or "").strip() or None
    if suggested is not None and confidence < confidence_floor:
        suggested = None
    column = ca["column"]
    # WS2 (issue #182): advisory recommendation always; final disposition only
    # auto-filled for narrow audit/technical columns (stamped ``heuristic``).
    recommended = recommend_disposition(column)
    auto = auto_disposition(column)
    entry: dict[str, Any] = {
        "column": column,
        "data_type": col_data_type,
        "suggested_property": suggested,
        "confidence": confidence,
        "rationale": ca.get("rationale", ""),
        # Issue #182 WS2: advisory triage recommendation (skip / silver-passthrough
        # / "" for a business column a human must decide on).
        "recommended_disposition": recommended,
        # Issue #164: triage disposition filled during domain modeling
        # (model | silver-passthrough | skip); null until a modeler dispositions it.
        "disposition": auto,
        "disposition_source": "heuristic" if auto else "",
    }
    note = str(ca.get("note", "") or "").strip()
    if note:
        entry["note"] = note
    proposal = normalize_local_proposal(ca.get("proposed_local_property"))
    if proposal:
        entry["proposed_local_property"] = proposal
    return entry


def _downgrade_catch_all_suggestions(
    custom_columns: list[dict[str, Any]],
    *,
    min_columns: int = CATCH_ALL_MIN_COLUMNS,
) -> int:
    """Null out catch-all ``suggested_property`` sinks across a domain (issue #182).

    When one suggested property is proposed for ``min_columns`` or more *dissimilar*
    custom columns (e.g. ``stageCode``/``customsID`` each becoming a sink for ~15
    unrelated columns), it is an unreliable fallback, not a real signal. Such
    suggestions are dropped to the honest unmatched form. Columns whose name closely
    matches the suggested property are not counted as dissimilar, so a genuinely
    repeated real attribute is preserved. Returns the number of entries downgraded.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for cc in custom_columns:
        suggested = cc.get("suggested_property")
        if not suggested:
            continue
        groups.setdefault(str(suggested), []).append(cc)

    downgraded = 0
    for suggested, members in groups.items():
        token = _normalize_property_token(suggested)
        dissimilar = [
            cc for cc in members if _normalize_property_token(cc.get("column", "")) != token
        ]
        if len(dissimilar) >= min_columns:
            for cc in dissimilar:
                cc["suggested_property"] = None
                downgraded += 1
    return downgraded


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
    "varchar": "string",
    "nvarchar": "string",
    "char": "string",
    "nchar": "string",
    "text": "string",
    "ntext": "string",
    "string": "string",
    "str": "string",
    "uuid": "string",
    "uniqueidentifier": "string",
    "guid": "string",
    "anyuri": "string",
    # integers
    "int": "int",
    "integer": "int",
    "bigint": "int",
    "smallint": "int",
    "tinyint": "int",
    "long": "int",
    "short": "int",
    "byte": "int",
    "nonnegativeinteger": "int",
    "positiveinteger": "int",
    # decimals
    "decimal": "decimal",
    "numeric": "decimal",
    "money": "decimal",
    "smallmoney": "decimal",
    "float": "decimal",
    "real": "decimal",
    "double": "decimal",
    # booleans
    "bit": "bool",
    "bool": "bool",
    "boolean": "bool",
    # dates
    "date": "date",
    # datetimes
    "datetime": "datetime",
    "datetime2": "datetime",
    "datetimeoffset": "datetime",
    "timestamp": "datetime",
    "smalldatetime": "datetime",
    "datetimestamp": "datetime",
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
    "type",
    "kind",
    "category",
    "status",
    "classification",
    "subtype",
    "class",
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


def _parses_as(value: str, target_type: str) -> bool:
    """Conservative check: does a single raw value parse as the target type?

    Only obvious numeric/bool cases are checked. Dates/locale formats are NOT
    parsed (too ambiguous) and always count as compatible to avoid false alarms.
    """
    text = str(value or "").strip()
    if not text:
        return True  # NULL/empty is not evidence of incompatibility
    if target_type == "int":
        return re.fullmatch(r"[+-]?\d+", text) is not None
    if target_type == "decimal":
        return re.fullmatch(r"[+-]?\d*\.?\d+([eE][+-]?\d+)?", text) is not None
    if target_type == "bool":
        return text.lower() in {"0", "1", "true", "false", "t", "f", "y", "n", "yes", "no"}
    return True


def _transform_compat_note(column: dict[str, Any], target_range: str) -> str | None:
    """Advisory warning when sampled values look incompatible with a CAST target.

    Returns a short note (e.g. "2/5 sample values are non-numeric — cast may
    NULL") or None. Numeric/bool targets only; never raises confidence, never
    blocks. Returns None when there are no samples or the target is not numeric/
    bool (we don't second-guess string/date casts from a 5-row sample).
    """
    target_type = _normalize_logical_type(target_range)
    if target_type not in {"int", "decimal", "bool"}:
        return None
    samples = [str(s).strip() for s in (column.get("samples") or []) if str(s).strip()]
    if not samples:
        return None
    bad = [s for s in samples if not _parses_as(s, target_type)]
    if not bad:
        return None
    kind = "non-boolean" if target_type == "bool" else "non-numeric"
    return f"{len(bad)}/{len(samples)} sample values are {kind} — CAST may NULL/fail; confirm"


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
                hints.append(
                    {
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
                    }
                )
                break  # one split signal per table is enough

    # dedup_candidate — an id-like natural key column + >=1 ordering column.
    id_cols = [
        c.get("name", "") for c in columns if str(c.get("name", "") or "").lower().endswith("id")
    ]
    ordering_cols = [
        c.get("name", "")
        for c in columns
        if _normalize_logical_type(c.get("data_type", "")) in ("date", "datetime")
        or any(tok in str(c.get("name", "") or "").lower() for tok in _ORDERING_TOKENS)
    ]
    if id_cols and ordering_cols:
        hints.append(
            {
                "type": "dedup_candidate",
                "source_table": table_name,
                "natural_key_column": id_cols[0],
                "ordering_column_candidates": ordering_cols,
                "requires_human_confirmation": True,
                "rationale": (
                    "Natural-key-like column with ordering column(s); confirm whether "
                    "deduplication / latest-record selection is required"
                ),
            }
        )

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
            hints.append(
                {
                    "type": "multi_target_candidate",
                    "source_table": table_name,
                    "source_column": col.get("name", ""),
                    "target_class_candidates": sorted(owners),
                    "requires_human_confirmation": True,
                    "rationale": (
                        f"Column '{col.get('name', '')}' matches a property in "
                        f"{len(owners)} reference classes; confirm intended target(s)"
                    ),
                }
            )

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


def _build_class_uri_index(
    ref_classes: list[dict[str, Any]],
) -> dict[str, str]:
    """Index governed class ``name`` → ``uri`` (F3 object-property target resolver).

    Used to decide whether an object property's target entity resolves to a
    governed class in the hub's reference inventory. Classes without a ``uri`` are
    skipped (the catalog-fallback extraction path omits per-class URIs).
    """
    idx: dict[str, str] = {}
    for cls in ref_classes:
        name = str(cls.get("name", "") or "")
        uri = str(cls.get("uri", "") or "")
        if name and uri:
            idx.setdefault(name, uri)
    return idx


#: F3 (toolkit-optimizations) — property names known to be *object* properties
#: (relationships to an entity/node) even when the local inventory carries no
#: ``rdfs:range``. Kept conservative and lower-cased/compacted; covers the DCSA
#: place/location relationships called out in the finding.
_OBJECT_PROPERTY_NAME_HINTS = frozenset(
    {
        "haslocation",
        "hasplaceofreceipt",
        "hasplaceofdelivery",
        "hasplaceofloading",
        "hasplaceofdischarge",
        "hasplaceofissue",
        "hasplaceofissuance",
        "hasaddress",
        "hasorigin",
        "hasdestination",
    }
)


def _resolve_object_property_target(
    ref_property: str,
    ref_class: str,
    range_index: dict[tuple[str | None, str], str],
    class_uri_by_name: dict[str, str],
) -> dict[str, Any] | None:
    """Classify a column→property map as an object property and resolve its target.

    F3 (toolkit-optimizations): a scalar source column attached to an *object*
    property (e.g. ``hasPlaceOfReceipt``, ``hasLocation``) makes the registry look
    covered without a target node. This resolver detects object properties two
    deterministic ways: a class-like ``rdfs:range`` (a PascalCase local name — XSD
    literal ranges are lower-cased), or a curated object-property name hint when
    range metadata is absent.

    Returns ``None`` for scalar/datatype properties (no change). For an object
    property returns ``{target_name, target_class_uri, target_resolved,
    cardinality}`` where ``target_resolved`` is True only when the target class is
    a governed class in the hub inventory.
    """
    rng = _lookup_property_range(range_index, ref_class, ref_property)
    local = ""
    if rng:
        local = str(rng).split("#")[-1].split("/")[-1].strip()
    is_class_like = bool(local) and local[:1].isupper()
    is_hint = _compact_name(ref_property) in _OBJECT_PROPERTY_NAME_HINTS
    if not (is_class_like or is_hint):
        return None
    target_name = local if is_class_like else ""
    target_uri = class_uri_by_name.get(target_name) if target_name else None
    return {
        "target_name": target_name,
        "target_class_uri": target_uri,
        "target_resolved": bool(target_uri),
        "cardinality": "n:1",
    }


# ---------------------------------------------------------------------------
# Generic object-relationship safeguards (proposal-quality)
# ---------------------------------------------------------------------------
#
# Deterministic, accelerator-agnostic guards that decide whether a scalar
# column aligned to an *object* property should keep its object-property
# mapping, or be downgraded to passthrough evidence + a relationship candidate
# (same F3 mechanism as an unresolved target). Kept generic on purpose — no
# accelerator/DCSA/logistics-specific vocabulary is introduced here; the only
# domain-flavoured names this module already knows about
# (``_OBJECT_PROPERTY_NAME_HINTS``) predate this change and stay untouched.
# Findings #7/#9 (proposal-quality): technical/audit actor columns must never
# become an in-domain relationship claim; any other object-property mapping
# needs identifier evidence (a plain descriptive scalar is not an entity
# reference); a *location*-flavoured object property additionally needs
# typed-role evidence (the column must actually look like the role the
# property names, e.g. "receipt"/"delivery") before a specialized property is
# trusted over a generic one.

#: Compact substrings that mark a column as a technical/audit actor reference
#: (who created/changed the record) rather than a business-entity identity.
#: Generic across accelerators; deliberately narrow to the "<verb>by" shape so
#: legitimate business-party columns are not swept up.
_TECHNICAL_ACTOR_PATTERNS: tuple[str, ...] = (
    "createdby",
    "updatedby",
    "modifiedby",
    "deletedby",
    "approvedby",
    "reviewedby",
    "authorizedby",
    "changedby",
    "lasteditedby",
    "enteredby",
)


def _is_technical_actor_column(column_name: str) -> bool:
    """Return True when *column_name* is a technical/audit actor reference.

    Generic safeguard (proposal-quality finding #9): ``created_by_*`` /
    ``updated_by_*`` and analogous technical-actor columns default to
    audit/passthrough evidence unless there is explicit business-entity
    identity evidence — which this deterministic pass cannot itself confirm,
    so it always downgrades. A human can still restore the object-property
    mapping if the column really does carry business-party identity.
    """
    compact = _compact_name(column_name)
    return any(pat in compact for pat in _TECHNICAL_ACTOR_PATTERNS)


#: Name tokens that mark a column as identifier-like (points at another row /
#: entity rather than describing it). Generic across accelerators.
_IDENTIFIER_NAME_TOKENS = frozenset(
    {
        "id",
        "identifier",
        "code",
        "reference",
        "ref",
        "key",
        "number",
        "no",
        "uuid",
        "guid",
        "num",
    }
)

#: Data-type tokens that mark a column as identifier-like by storage shape
#: (surrogate keys are typically integral or UUID, never free text).
_IDENTIFIER_DATA_TYPE_TOKENS = frozenset(
    {
        "int",
        "bigint",
        "smallint",
        "tinyint",
        "integer",
        "uuid",
        "guid",
        "uniqueidentifier",
    }
)


def _looks_like_identifier_column(column_name: str, data_type: str) -> bool:
    """Return True when *column_name*/*data_type* look like an entity identifier.

    Generic safeguard (proposal-quality finding #9): an object-property
    relationship must be backed by target/entity identifier evidence — a
    descriptive scalar (a name, a free-text note) is not itself evidence that
    the source system holds a reference to another entity. Tokenized (not
    substring) matching avoids false positives such as "point" containing
    "int" (see :func:`_tokenize_text`).
    """
    if _tokenize_text(column_name) & _IDENTIFIER_NAME_TOKENS:
        return True
    if _tokenize_text(data_type) & _IDENTIFIER_DATA_TYPE_TOKENS:
        return True
    return False


#: The two fully-generic location object properties. They carry no specific
#: role of their own (unlike ``hasPlaceOfReceipt`` → "receipt"), so they are
#: exempt from the typed-role-evidence check below.
_GENERIC_LOCATION_PROPERTIES = frozenset({"haslocation", "hasaddress"})

#: Prefixes stripped (longest first) from a compacted object-property name to
#: derive its location role token, e.g. ``hasPlaceOfReceipt`` → ``receipt``.
_LOCATION_ROLE_PREFIXES: tuple[str, ...] = ("hasplaceof", "hasportof", "has")


def _is_location_object_property(ref_property: str) -> bool:
    """Return True when *ref_property* is one of the curated location hints."""
    return _compact_name(ref_property) in _OBJECT_PROPERTY_NAME_HINTS


def _location_role_token(ref_property: str) -> str | None:
    """Derive the typed role token a location property expects evidence for.

    Returns ``None`` for the fully-generic ``hasLocation`` / ``hasAddress``
    (no specific role to require evidence for) and for any name this
    conservative prefix-stripping cannot reduce to a non-empty token.
    """
    compact = _compact_name(ref_property)
    if compact in _GENERIC_LOCATION_PROPERTIES:
        return None
    for prefix in _LOCATION_ROLE_PREFIXES:
        if compact.startswith(prefix) and len(compact) > len(prefix):
            return compact[len(prefix) :]
    return None


def _has_typed_role_evidence(column_name: str, role_token: str) -> bool:
    """Return True when *column_name* itself carries the expected role token.

    Generic safeguard (proposal-quality finding #9): a specialized location
    property (origin/receipt/delivery/discharge/...) must only be selected
    when the source column's own name gives explicit evidence of that role —
    e.g. a column literally named "PlaceOfReceipt" or "receipt_location", not
    a bare "location"/"place" column force-fit onto the most specific-sounding
    property the model happened to pick.
    """
    return role_token in _compact_name(column_name)


def _object_relationship_downgrade_reason(
    *,
    column: str,
    data_type: str,
    ref_property: str,
    target_resolved: bool,
) -> str | None:
    """Decide whether an object-property column map should be downgraded.

    Returns ``None`` to keep the mapping unchanged, or one of:

    * ``"technical_actor"`` — a ``created_by_*`` / ``updated_by_*`` style
      technical-actor column (finding #9) — audit/passthrough only, never a
      relationship candidate;
    * ``"missing_typed_role_evidence"`` — a specialized location property
      (e.g. ``hasPlaceOfReceipt``) selected without the column itself naming
      that role;
    * ``"missing_identifier_evidence"`` — a non-location object property
      selected without identifier-like evidence on the source column;
    * ``"unresolved_target"`` — the pre-existing F3 check: no governed target
      class resolves (preserved as the last check so the default behaviour
      for an already-safe mapping is unchanged).
    """
    if _is_technical_actor_column(column):
        return "technical_actor"
    if _is_location_object_property(ref_property):
        role_token = _location_role_token(ref_property)
        if role_token and not _has_typed_role_evidence(column, role_token):
            return "missing_typed_role_evidence"
    elif not _looks_like_identifier_column(column, data_type):
        return "missing_identifier_evidence"
    if not target_resolved:
        return "unresolved_target"
    return None


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

#: Generic identity / name properties a weakly-evidenced or address/financial
#: column should not silently land on. Specific identifiers (taxIdentifier,
#: vatNumber, bankAccountIdentifier, ...) are deliberately excluded.
_GENERIC_IDENTITY_PROPERTIES = frozenset(
    {
        "partyidentifier",
        "registrationnumber",
        "partyname",
        "name",
        "identifier",
    }
)

#: Column tokens that mark a column as financial-flavoured.
_FINANCIAL_COLUMN_TOKENS = frozenset(
    {
        "iban",
        "bic",
        "swift",
        "currency",
        "payment",
        "amount",
        "balance",
    }
)


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


def _is_projection_part_column(column_name: str, projections: Sequence[EntityProjection]) -> bool:
    """Return True when *column_name* is a part of any configured projection.

    DD-188: the toolkit no longer carries the token list this used to test against.
    With no configured projections there is no vocabulary, so nothing is a part —
    that is the intended no-config behaviour, not a degraded one.
    """
    return any(_projection_column_match(column_name, p) is not None for p in projections)


@lru_cache(maxsize=None)
def _projection_property_tokens(projection: EntityProjection) -> frozenset[str]:
    """Tokens that mark a reference *property* as belonging to this projection.

    Derived entirely from the pack's own part-kind, context and target-concept
    vocabulary rather than a second hand-maintained list: a property whose name
    carries any word the projection uses to recognise its parts is, by the pack's
    own definition, a plausible home for one of those parts.
    """
    tokens: set[str] = set()
    for part in projection.part_kinds:
        tokens |= set(part.tokens)
        tokens |= set(part.compact)
    tokens |= set(projection.context_tokens)
    if projection.target_concept:
        tokens.add(_compact_name(projection.target_concept))
    return frozenset(t for t in tokens if t)


def _is_projection_target_property(
    ref_property: str, projections: Sequence[EntityProjection]
) -> bool:
    """Return True when *ref_property* is flavoured like one of the projections."""
    tokens = _tokenize_text(ref_property)
    compact = _compact_name(ref_property)
    for projection in projections:
        vocab = _projection_property_tokens(projection)
        if any(t in tokens or t in compact for t in vocab):
            return True
    return False


# ---------------------------------------------------------------------------
# Entity-projection relationship-candidate detection
# (issue #192 Phase A1 → issue #531 / DD-188)
# ---------------------------------------------------------------------------
#
# Deterministic, no-LLM, no-cross-module-widening detector for *entity
# projections*: scalar columns on one source table that together evidence a
# separate entity the source system flattened away. It clusters a table's columns
# by role and emits a candidate only when a role carries at least
# ``min_complementary_parts`` DISTINCT part kinds, so a single column never fires.
# Candidates are ADDITIVE (the scalar column dispositions are untouched) and carry
# ``requires_human_confirmation``.
#
# DD-188 splits this into logic and data. Everything in this section is the logic
# — cluster by role, require complementary kinds, resolve the target class in the
# domain's import closure, emit an advisory candidate — and it is as true for a
# bank as for a carrier. Every token it matches on comes from the accelerator
# pack's ``entity-projections.yaml`` (:mod:`kairos_ontology.core.entity_projections`).
# There is deliberately **no built-in vocabulary**: a pack that ships no projection
# config produces no candidates, and the absence is logged. A silent fallback would
# keep shipping one industry's tokens to every other industry, which is exactly
# what DD-188 forbids.
#
# Cluster *identity* is content-addressed and independent of membership: the
# ``cluster_id`` derives only from (domain, source table, role, target concept,
# cardinality). That is what lets a re-run refresh which columns contribute to a
# cluster while the cluster — and any human decision recorded against it —
# survives.


def _projection_column_match(
    column_name: str, projection: EntityProjection
) -> tuple[str, str] | None:
    """Return ``(part_kind, role)`` when *column_name* is a part of *projection*.

    The three rules the pack's data drives, and nothing else:

    * **role** — the first (sorted) ``role_qualifier`` token in the name, else
      ``"default"``. A qualifier such as ``billing`` / ``pickup`` separates
      role-specific clusters so ``billing_*`` and ``pickup_*`` become two distinct
      relationships rather than one merged entity.
    * **kind** — the first declared ``part_kind`` whose ``tokens`` intersect the
      column's token set, or whose ``compact`` entries appear in its compacted
      name. Kinds are matched in declaration order, most specific first, and a
      column lands on exactly one.
    * **confirmation** — a ``weak`` kind counts only alongside a role qualifier or
      a context token; a ``requires: context`` kind counts only alongside a context
      token, a role qualifier being explicitly insufficient. When the matched kind's
      gate is not satisfied the column is not a part at all: kinds are ordered so
      the first match is the right one, and falling through to a later, vaguer kind
      would defeat the gate rather than honour it.
    """
    tokens = _tokenize_text(column_name)
    if not tokens:
        return None
    compact = _compact_name(column_name)
    roles = sorted(tokens & projection.role_qualifiers)
    role = roles[0] if roles else "default"
    has_context = bool(tokens & projection.context_tokens)

    for part in projection.part_kinds:
        if not (tokens & part.tokens or any(kw in compact for kw in part.compact)):
            continue
        if part.needs_context:
            return (part.kind, role) if has_context else None
        if part.weak:
            return (part.kind, role) if (roles or has_context) else None
        return part.kind, role
    return None


def _projection_relationship_name(role: str, projection: EntityProjection) -> str:
    """Suggest the object-property name for one role group of *projection*.

    ``default_relationship`` when the role is ``default``, otherwise
    ``relationship_naming`` with ``{Role}`` title-cased (``pickup`` →
    ``hasPickupAddress``). Both strings come from the pack; when it authors
    neither, the projection id is used rather than a name invented here.
    """
    if role == "default":
        return projection.default_relationship or projection.id
    pattern = projection.relationship_naming
    if not pattern:
        return projection.default_relationship or projection.id
    return pattern.replace("{Role}", f"{role[:1].upper()}{role[1:]}")


def _resolve_projection_target(
    projection: EntityProjection, closure_uris: frozenset[str]
) -> str | None:
    """Return the first ``target_candidates`` URI present in the domain's closure.

    ``None`` when none of them resolve — the candidate is still emitted, flagged
    ``target_resolved: false``, because a projection the columns clearly evidence
    is a real finding even where the pack's preferred class is not imported here.
    Never guess a substitute, never drop the candidate.
    """
    for uri in projection.target_candidates:
        if uri in closure_uris:
            return uri
    return None


def _relationship_cluster_id(
    domain: str,
    source_table: str,
    role: str,
    target_concept: str,
    cardinality: str,
) -> str:
    """Stable, content-addressed relationship-cluster id (proposal-quality).

    Derived ONLY from the cluster's stable dimensions — source table, semantic
    role/prefix, target class/concept, and cardinality (qualified by domain to
    avoid collisions across domains sharing a table name) — and deliberately
    NEVER from which columns currently contribute. That is what lets a refresh
    report membership changes (columns added/removed) while the cluster keeps
    the same identity, so a human decision recorded against it is never
    silently orphaned by a re-run (see ``claim_registry.DomainHandoff`` sibling
    concept and ``_merge_relationship_candidates``).
    """
    basis = "|".join(
        [
            domain or "",
            source_table or "",
            role or "default",
            target_concept or "",
            cardinality or "",
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _detect_projection_relationship_candidates(
    table_name: str,
    columns: list[dict[str, Any]],
    *,
    projections: Sequence[EntityProjection] = (),
    closure_uris: frozenset[str] = frozenset(),
    domain: str = "",
) -> list[dict[str, Any]]:
    """Detect projected-entity column clusters and emit relationship candidates.

    Deterministic and additive. For each configured projection, groups its part
    columns by role and emits one candidate per role carrying at least
    ``min_complementary_parts`` distinct part kinds.

    DD-188: *projections* is pack data. With none configured this returns nothing —
    the toolkit has no address (or cargo, or party) vocabulary of its own to fall
    back to, by design. ``closure_uris`` is the set of class URIs the domain can
    actually see, used to resolve the target class; a candidate whose target does
    not resolve is still emitted, flagged ``target_resolved: false``.

    ``domain`` qualifies the stable ``cluster_id`` so identically-named tables in
    different domains never collide.
    """
    candidates: list[dict[str, Any]] = []
    for projection in projections:
        by_role: dict[str, dict[str, list[str]]] = {}
        for col in columns:
            name = str(col.get("name", "") or "")
            if not name:
                continue
            match = _projection_column_match(name, projection)
            if match is None:
                continue
            kind, role = match
            by_role.setdefault(role, {}).setdefault(kind, []).append(name)

        target_uri = _resolve_projection_target(projection, closure_uris)
        concept = projection.target_concept or projection.id
        cardinality = projection.cardinality or "1:n"
        minimum = projection.min_complementary_parts

        for role in sorted(by_role):
            kinds = by_role[role]
            if len(kinds) < minimum:
                continue
            source_columns = sorted({c for cols in kinds.values() for c in cols})
            part_kinds = sorted(kinds)
            rel = _projection_relationship_name(role, projection)
            role_phrase = "" if role == "default" else f" under role '{role}'"
            if target_uri:
                target_phrase = f"Target class resolves to <{target_uri}> in this domain's closure."
            elif projection.target_candidates:
                target_phrase = (
                    "None of the projection's target candidates "
                    f"({', '.join(projection.target_candidates)}) are present in this "
                    "domain's import closure — confirm the target class during modeling."
                )
            else:
                target_phrase = (
                    "The projection declares no target candidates — confirm the target "
                    "class during modeling."
                )
            candidates.append(
                {
                    "type": "entity_projection_candidate",
                    "projection_id": projection.id,
                    "source_table": table_name,
                    "role": None if role == "default" else role,
                    "suggested_relationship": rel,
                    "target_concept": concept,
                    "target_class_uri": target_uri,
                    "target_resolved": target_uri is not None,
                    "source_columns": source_columns,
                    "part_kinds": part_kinds,
                    "cardinality": cardinality,
                    "cluster_id": _relationship_cluster_id(
                        domain,
                        table_name,
                        role,
                        concept,
                        cardinality,
                    ),
                    "requires_human_confirmation": True,
                    "rationale": (
                        f"{len(part_kinds)} complementary {concept} parts "
                        f"({', '.join(part_kinds)}){role_phrase}; consider modelling a "
                        f"'{rel}' {cardinality} relationship to a shared {concept} concept "
                        f"IN ADDITION to the scalar column mappings, rather than only "
                        f"scalar passthroughs. {target_phrase}"
                    ),
                }
            )
    return candidates


def _cluster_object_property_candidates(
    candidates: list[dict[str, Any]],
    *,
    domain: str = "",
) -> list[dict[str, Any]]:
    """Cluster per-column object-property candidates into one-per-relationship.

    proposal-quality: ``_build_object_property_candidate`` emits one candidate
    per downgraded column; several columns on the same table can legitimately
    contribute to the *same* relationship (e.g. two columns both evidencing a
    receipt location). This groups them by the stable dimensions — source
    table, suggested relationship (the semantic role/prefix for an object
    property), target concept, and cardinality — into a single cluster that
    carries all contributing columns, mirroring the address-cluster shape and
    giving the group the same stable, refresh-safe ``cluster_id``.
    """
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str, str]] = []
    for cand in candidates:
        key = (
            str(cand.get("source_table", "") or ""),
            str(cand.get("suggested_relationship", "") or ""),
            str(cand.get("target_concept", "") or ""),
            str(cand.get("cardinality", "") or ""),
        )
        group = groups.get(key)
        if group is None:
            group = dict(cand)
            group["source_columns"] = list(cand.get("source_columns", []) or [])
            groups[key] = group
            order.append(key)
        else:
            for col in cand.get("source_columns", []) or []:
                if col not in group["source_columns"]:
                    group["source_columns"].append(col)
            # target_resolved/target_class_uri are deterministic functions of
            # (ref_property, inventory), so identical across a group; keep the
            # first-seen value.

    merged: list[dict[str, Any]] = []
    for key in sorted(order):
        source_table, suggested_relationship, target_concept, cardinality = key
        group = groups[key]
        group["source_columns"] = sorted(group["source_columns"])
        group["cluster_id"] = _relationship_cluster_id(
            domain,
            source_table,
            suggested_relationship,
            target_concept,
            cardinality,
        )
        if len(group["source_columns"]) > 1:
            group["rationale"] = (
                f"{len(group['source_columns'])} scalar columns "
                f"({', '.join(group['source_columns'])}) were aligned to object "
                f"property '{suggested_relationship}'; modelled as a single "
                "relationship candidate carrying all contributing columns "
                "(proposal-quality)."
            )
        merged.append(group)
    return merged


def _review_column_alignment(
    *,
    column_name: str,
    data_type: str,
    ref_class: str,
    ref_property: str,
    confidence: float,
    label_index: dict[tuple[str | None, str], str],
    projections: Sequence[EntityProjection] = (),
) -> str | None:
    """Return a review reason when a column map is implausible, else ``None``.

    Deterministic; FLAGS (never changes) the mapping. Covers issue #167
    (projected-entity part columns force-fit onto unrelated scalars) and issue #168
    (boolean→identity, financial→identity, and weak-name + low-confidence maps).

    DD-188: the #167 rule needs to know what a part column looks like, which is
    pack vocabulary. *projections* supplies it; with none configured that rule is
    simply inert (the remaining #168 rules are structural and always apply).
    """
    if not ref_property:
        return None

    prop_label = _lookup_property_label(label_index, ref_class, ref_property)
    col_tokens = _tokenize_text(column_name)
    prop_tokens = _tokenize_text(ref_property) | _tokenize_text(prop_label)
    shared = col_tokens & prop_tokens
    is_identity = ref_property.lower() in _GENERIC_IDENTITY_PROPERTIES

    # #167 — projected-entity part columns. Mapping one to an unrelated scalar is
    # implausible; mapping it to a property flavoured like the projection is
    # plausible (and exempt from the generic low-confidence rule below, since
    # street↔address share no token).
    part_projection = next(
        (p for p in projections if _projection_column_match(column_name, p) is not None),
        None,
    )
    if part_projection is not None:
        if _is_projection_target_property(ref_property, [part_projection]):
            return None
        concept = part_projection.target_concept or part_projection.id
        return (
            f"{concept}-part column '{column_name}' mapped to unrelated property "
            f"'{ref_property}'; model a {concept} relationship / shared {concept} concept"
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


def _propose_alignments(
    analysis_dir: Path,
    sources_dir: Path,
    catalog_path: Path | None,
    output_dir: Path | None,
    model: str = DEFAULT_MODEL,
    domains_filter: list[str] | None = None,
    report=None,
    include_mapping_hints: bool = False,
    include_sample_values: bool = True,
    max_prompt_classes: int = MAX_REF_CLASSES_PER_PROMPT,
    retry_min_confidence: float = RETRY_MIN_CONFIDENCE,
    retry_min_mapped_ratio: float = RETRY_MIN_MAPPED_RATIO,
    max_workers: int = DEFAULT_MAX_WORKERS,
    force: bool = False,
    cost_warning: bool = False,
    cross_module: bool = False,
    accelerator: str | None = None,
    ref_models_dir: Path | None = None,
    custom_confidence_floor: float = CUSTOM_CONFIDENCE_FLOOR,
    emit_output: bool = True,
    allow_fallback_output: bool = False,
    generation_stats: dict[str, int] | None = None,
    conformance_artifact_path: Path | None = None,
    honour_table_exclusions: bool = True,
) -> tuple[list[Path], list[DomainAlignment]]:
    """Run alignment for all domains found in affinity reports.

    Args:
        analysis_dir: Directory containing *-affinity.yaml files.
        sources_dir: Directory containing source system subdirs with *.vocabulary.ttl.
        catalog_path: Path to the hub's catalog-v001.xml.
        output_dir: Where to write *-alignment.yaml files.
        model: LLM model name. Authoritative for this run: the caller (the CLI)
            owns model precedence (explicit ``--model`` > ``--high-accuracy``
            preset > ``KAIROS_AI_{ROLE}_MODEL`` > default), and the per-role
            provider config is never allowed to override it here.
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
            (required when *cross_module* is True). DD-188 (issue #531): also where
            the pack's ``entity-projections.yaml`` is read from. Without it — or
            with a pack that ships no such file — the entity-projection detector
            emits no relationship candidates and says so in the run output. There
            is no built-in vocabulary to fall back to, on purpose.
        allow_fallback_output: Alignment-reliability — a domain where *every*
            table produced ``fallback_only`` (no reference model to align
            against — the LLM was never even called) is skipped by default so a
            placeholder-only registry never masquerades as a real proposal.
            Pass True to explicitly opt into writing it anyway.
        generation_stats: Alignment-reliability — optional out-param populated
            with run-wide ``{"attempted", "semantic_success", "provider_failure"}``
            counts, for callers (the CLI) that want a summary without changing
            this function's return type.
        conformance_artifact_path: uri-anchor-contract — path to the hub's
            ``core-concepts-conformance.yaml`` (DD-090). When it resolves a
            table's affinity-derived ``likely_entity`` to exactly one confirmed
            concept URI, that URI wins over the model's own class pick/name
            similarity; when it names more than one, the table's anchor is
            deliberately left unresolved (a versioned ``unresolved_anchors``
            record is written instead of guessing — see
            ``unresolved_anchors.py``) and no property/custom-column claims are
            generated for it. Default ``None`` (or a missing/unreadable file)
            leaves this run's output byte-identical to before this feature.
        honour_table_exclusions: #528 follow-up — when True (default), tables the
            schema-catalogue screen recorded under ``excluded`` in
            ``table-anchors.yaml`` are not aligned. They describe another table's
            columns, so every claim made about them is a claim about metadata.
            Each one is reported with its evidence and recorded in the owning
            domain's ``excluded_tables`` block rather than silently dropped. Set
            False to align every affinity table regardless (the counterpart of
            ``anchor-tables --no-schema-catalogue-screen``, for when the screen
            has a false positive). A hub with no ``table-anchors.yaml`` has no
            exclusions to honour and is unaffected either way.

    Returns ``(written_paths, built_alignments)``. When *emit_output* is False the
    pipeline only builds and returns the in-memory :class:`DomainAlignment` objects
    (no domain-level skip, no files written); this is the testable/introspection
    path used by :func:`build_domain_alignments`.

    Raises:
        AlignmentTotalFailureError: every attempted table's semantic generation
            failed (100% ``provider_failure``) — nothing was written by the run
            (all writes are staged until the run-wide verdict is known).
    """
    if report is None:
        report = lambda msg, **kw: None  # noqa: E731

    # DD-070: resolve the accelerator import → module map for cross-module mode.
    # DD-181: declared cross-domain bridges, loaded once. Unlike the cross-module
    # property pool below, this needs no flag and no explicit accelerator — the
    # blueprint's own declarations are read wherever they are found.
    cross_domain_bridges: list[dict[str, Any]] = []
    bridge_accelerator: str | None = None
    if ref_models_dir is not None:
        # The pack must be resolved, not guessed: with several installed, globbing
        # takes the first alphabetically — `financial-services` ahead of
        # `logistics` — and silently returns another pack's bridges, or none.
        # Reuse the shared resolver (DD-125) so this agrees with validate/project.
        bridge_accelerator = accelerator
        if not bridge_accelerator:
            try:
                from .reference_modules import resolve_hub_accelerator

                bridge_accelerator = resolve_hub_accelerator(
                    explicit=None,
                    hub_root=_hub_root_from_catalog(catalog_path),
                    ref_models_dir=Path(ref_models_dir),
                    domain_hint=domains_filter or None,
                )
            except Exception:  # noqa: BLE001 - advisory; ambiguity must not fail a run
                bridge_accelerator = None
        if bridge_accelerator:
            cross_domain_bridges = load_cross_domain_bridges(
                Path(ref_models_dir), bridge_accelerator
            )
        if cross_domain_bridges:
            report(
                f"  🌉 {len(cross_domain_bridges)} declared cross-domain "
                f"relationship(s) from '{bridge_accelerator}'"
            )

    # DD-188 (issue #531): the entity-projection vocabulary is pack data, loaded
    # once here. When the pack ships none, the detector emits no candidates — the
    # toolkit carries no address/cargo/party token list to fall back to. Say so
    # out loud: a hub pinned to an older reference-models release loses these
    # advisory candidates until it upgrades, and that must be visible rather than
    # look like "this hub simply has no address columns".
    projection_config: ProjectionConfig = load_entity_projections(
        Path(ref_models_dir) if ref_models_dir is not None else None,
        bridge_accelerator,
    )
    projections = projection_config.projections
    if projections:
        report(
            f"  🧩 {len(projections)} entity projection(s) from "
            f"'{bridge_accelerator or '*'}': {', '.join(p.id for p in projections)}"
        )
    else:
        report(
            "  🧩 No entity-projections.yaml in the reference models — projection "
            "relationship candidates are disabled for this run (DD-188: the toolkit "
            "ships no built-in projection vocabulary)."
        )

    accelerator_uri_modules: dict[str, dict[str, Any]] = {}
    if cross_module:
        if not accelerator or not ref_models_dir:
            raise ValueError(
                "--cross-module requires an accelerator and a reference-models "
                "directory. Pass --accelerator <name> (and ensure "
                "ontology-reference-models/ is present)."
            )
        from .analyse_sources import load_accelerator_uri_modules

        accelerator_uri_modules = load_accelerator_uri_modules(Path(ref_models_dir), accelerator)
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

    # DD-185: regroup tables into their anchor-derived domains BEFORE the domain
    # filter, so a table moving into a filtered-in domain is included. This is
    # what makes affinity a prior rather than a constraint: a misplaced table is
    # aligned in the domain whose classes it actually needs.
    global_anchors = load_table_anchors(analysis_dir)
    anchor_counters = {"applied": 0, "low_confidence": 0, "outside_pool": 0}
    if global_anchors:
        report(f"  ⚓ {len(global_anchors)} global table anchor(s) loaded")
        domain_uris_by_id: dict[str, list[str]] = {}
        if ref_models_dir is not None and bridge_accelerator:
            domain_uris_by_id = {
                dom: list(meta.get("uris") or [])
                for dom, meta in load_data_domains(
                    Path(ref_models_dir), accelerator=bridge_accelerator
                ).items()
            }
        domain_tables, anchor_moves = regroup_by_anchor(
            domain_tables, global_anchors, domain_uris_by_id
        )
        for move in anchor_moves:
            report(
                f"  ⚓ {move['system']}.{move['table']}: {move['from'] or '(none)'} → "
                f"{move['to']} (anchored to {move['anchor']})"
            )

    # Apply domain filter
    if domains_filter:
        lower_filter = [d.lower() for d in domains_filter]
        domain_tables = {
            k: v for k, v in domain_tables.items() if any(f in k.lower() for f in lower_filter)
        }
        if not domain_tables:
            raise ValueError(
                f"No domains matched filter: {domains_filter}. "
                f"Available: {list(load_affinity_reports(analysis_dir).keys())}"
            )

    # #528 follow-up: honour the schema-catalogue screen. Alignment discovers its
    # work from the affinity reports, which are written before anchoring and know
    # nothing about it, so a table already judged "not business data at all" was
    # still aligned and its columns still landed in the registry as claims about
    # a reference class. That verdict lives in table-anchors.yaml; read it here,
    # once, so the exclusion is honoured at the point work is enumerated instead
    # of being filtered out again by every downstream stage.
    #
    # Removing a table changes this domain's affinity hash, so the domain-level
    # freshness skip below correctly rebuilds a registry written before the fix
    # rather than serving the stale one that still contains the excluded table.
    excluded_by_domain: dict[str, list[dict[str, str]]] = {}
    table_exclusions = load_excluded_tables(analysis_dir) if honour_table_exclusions else {}
    if table_exclusions:
        kept_tables: dict[str, list[dict[str, Any]]] = {}
        for domain_id, tables in domain_tables.items():
            keep: list[dict[str, Any]] = []
            for entry in tables:
                system = str(entry.get("system") or "")
                table = str(entry.get("table") or "")
                reason = table_exclusions.get((system, table))
                if reason is None:
                    keep.append(entry)
                    continue
                excluded_by_domain.setdefault(domain_id, []).append(
                    {"system": system, "table": table, "reason": reason}
                )
            if keep:
                kept_tables[domain_id] = keep
        domain_tables = kept_tables
    dropped = [(d, e) for d, entries in sorted(excluded_by_domain.items()) for e in entries]
    if dropped:
        # Reported the way anchoring reports its own screen: the count, then every
        # table with the evidence that excluded it. A table that simply stopped
        # appearing in an alignment file would be indistinguishable from a bug.
        report(
            f"  🚫 {len(dropped)} table(s) excluded from alignment by the "
            "schema-catalogue screen (they describe another table's columns, not "
            "business data):"
        )
        for domain_id, entry in dropped:
            report(f"       {entry['system']}.{entry['table']} [{domain_id}] — {entry['reason']}")
        report(
            "       recorded under 'excluded_tables' in each domain's alignment "
            "file; if one of these is real business data, re-run anchor-tables "
            "with --no-schema-catalogue-screen or record a table-grain "
            "disposition for it"
        )
    if not domain_tables:
        raise ValueError(
            "Every affinity table was excluded by the schema-catalogue screen "
            f"({len(dropped)} table(s)). Nothing was aligned and no file was "
            "written. Re-run 'anchor-tables --no-schema-catalogue-screen' if the "
            "screen is wrong about them."
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

    # Preflight (alignment-reliability): resolve the provider/endpoint/auth for
    # this role *before* any cost/fan-out, so a bad provider config surfaces
    # immediately instead of mid-run on the first table.  An unconfigured or
    # misconfigured provider raises ``AIProviderError`` (subclass of
    # ``EnvironmentError``) here — it must never silently fall through to a
    # heuristic or plausible-empty output (DD-159).
    #
    # Model precedence: the *caller-resolved* ``model`` is authoritative and is
    # never re-derived here. The CLI already applies the full precedence chain
    # (explicit ``--model`` > ``--high-accuracy`` preset > ``KAIROS_AI_
    # {ROLE}_MODEL`` > ``DEFAULT_MODEL`` — see ``propose_alignment_cmd``), so
    # reading the model back off the provider config would let the per-role env
    # override silently win over an explicitly pinned model. The provider config
    # is therefore consumed as endpoint/auth/preflight metadata only.
    #
    # ``get_ai_client`` (mocked directly in unit tests) performs the same
    # provider resolution internally and remains the source of truth for
    # constructing the client.
    provider_config = require_ai_provider(ROLE_ALIGNMENT, model=model, probe=False)
    if provider_config.model != model:
        report(
            f"  ℹ Per-role model override '{provider_config.model}' not "
            f"applied — the caller-resolved model '{model}' is "
            "authoritative.",
            level="verbose",
        )
    client = get_ai_client(model, role=ROLE_ALIGNMENT)
    report(f"  🔌 Provider: {provider_config.provider} — effective model: {model}")

    # uri-anchor-contract: built once for the whole run (the conformance
    # artifact is hub-wide, not per-domain). Missing/unreadable path -> empty
    # index -> every table falls through to the existing LLM/lexical path
    # unchanged.
    alias_index = load_confirmed_alias_index(conformance_artifact_path)
    if alias_index:
        report(
            f"  🔗 Confirmed anchors: {len(alias_index)} alias(es) from {conformance_artifact_path}"
        )

    if cost_warning:
        from ._cost import print_cost_warning

        total_tables = sum(len(v) for v in domain_tables.values())
        print_cost_warning(
            command="propose-alignment",
            table_count=total_tables,
            max_workers=max_workers,
            model=model,
            force=force,
            accuracy_sensitive=True,
        )

    # Per-table sidecar cache (CR-5 fine-grained layer); disabled with --force.
    cache = open_cache(analysis_dir, "propose-alignment", enabled=not force)

    output_files: list[Path] = []
    alignments: list[DomainAlignment] = []
    # Alignment-reliability: every filesystem effect of this run is *staged* here
    # in domain order and only committed once the run-wide semantic verdict is
    # known (see the total-failure check after the loop). Nothing may be written
    # while it is still possible that the run failed semantically end-to-end —
    # otherwise a domain that mixes ``provider_failure`` with ``fallback_only``
    # tables (neither group covering the whole domain, so no per-domain gate
    # fires) would be persisted just before ``AlignmentTotalFailureError``
    # states that nothing was written. Entries are either
    # ``{"kind": "cached", "path": ...}`` (a domain skipped by the freshness
    # cache — already on disk, untouched by this run) or
    # ``{"kind": "write", ...}`` (a pending registry + unresolved-anchors write).
    staged_outputs: list[dict[str, Any]] = []
    if emit_output:
        assert output_dir is not None
        output_dir.mkdir(parents=True, exist_ok=True)

    # Alignment-reliability — run-wide tallies. "Attempted" counts only tables
    # where a real LLM call path was taken (semantic_success or
    # provider_failure); fallback_only tables never called the LLM at all, so
    # they neither count as an attempt nor as a success.
    run_attempted = 0
    run_semantic_success = 0
    run_provider_failures = 0

    # DD-171: resolve the two knowledge inputs once for the whole run.
    class_cautions: dict[str, str] = {}
    if ref_models_dir is not None:
        try:
            from .conformance_judge import pattern_cautions

            class_cautions = pattern_cautions(None, Path(ref_models_dir))
        except Exception:  # noqa: BLE001 - advisory prompt context only
            class_cautions = {}
    glossary_terms = load_glossary_terms(Path(sources_dir).parent.parent)
    if class_cautions:
        report(f"  🧭 {len(class_cautions)} pattern-library caution(s) in scope")
    if glossary_terms:
        report(f"  📖 {len(glossary_terms)} business glossary term(s) in scope")

    domain_order = sorted(domain_tables.items())
    total_tables = sum(len(t) for t in domain_tables.values())
    tables_done = 0
    run_started = time.monotonic()

    # DD-184: one session id per invocation. Calls run concurrently across
    # threads, where a context-manager span would not reliably parent them, so
    # grouping uses the session mechanism the SDK provides for exactly this.
    trace_session_id = new_session_id("align")

    for domain_index, (domain_id, tables) in enumerate(domain_order, start=1):
        in_flight = min(max_workers, len(tables))
        report(
            f"  📐 Domain {domain_index}/{len(domain_order)}: {domain_id} "
            f"({len(tables)} table(s), {in_flight} in parallel)"
        )

        # Get domain URIs from first table entry
        domain_uris = tables[0].get("domain_uris", []) if tables else []

        affinity_hash = compute_affinity_hash((t["system"], t["table"]) for t in tables)

        # Issue #182: the params signature now always encodes the algorithm/prompt
        # contract version, the model, and the custom-confidence floor (plus the
        # cross-module pool when applicable) so a stale on-disk alignment from an
        # older toolkit version — or a different floor/model — never satisfies the
        # domain-level skip and silently serves pre-hardening output.
        params_payload: dict[str, Any] = {
            "algorithm_version": ALIGNMENT_ALGORITHM_VERSION,
            "model": model,
            "custom_confidence_floor": round(float(custom_confidence_floor), 4),
            # Issues #517/#520 — a pre-fix alignment answers a narrower question.
            "pool_contract": ALIGNMENT_POOL_CONTRACT,
        }
        if cross_module:
            # DD-070: cross-module results must not be reused for a home-only run.
            params_payload.update(
                {
                    "cross_module": True,
                    "accelerator": accelerator or "",
                    "accelerator_uris": sorted(accelerator_uri_modules.keys()),
                    "home_uris": sorted(domain_uris),
                }
            )
        params_hash = compute_entry_hash(params_payload)

        # CR-5: domain-level skip — reuse an existing claim registry whose freshness
        # hash already matches the current affinity set (unless --force). The
        # params hash must also match so an algorithm/model/floor change forces a
        # rebuild (issue #182). Only applies when emitting claims to disk.
        if emit_output and not force:
            out_path = output_dir / f"{domain_id}-alignment.yaml"
            if out_path.exists():
                existing_hash = _read_alignment_affinity_hash(out_path)
                if existing_hash and existing_hash == affinity_hash:
                    if _read_alignment_params_hash(out_path) == params_hash:
                        report(f"     ⏭  Up to date (affinity unchanged) — skipped {out_path.name}")
                        staged_outputs.append({"kind": "cached", "path": out_path})
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

        # DD-181: widen the anchor pool with classes this domain is *declared* to be
        # able to reference. On by default and unflagged: a bridge in the blueprint
        # is the authorisation, and requiring a CLI flag to honour it would mean the
        # default run ignores governance the hub already expressed.
        bridge_anchors = resolve_bridge_anchor_classes(
            bridge_anchor_classes(cross_domain_bridges, domain_id),
            catalog_path,
            exclude_uris={str(c.get("uri") or "") for c in ref_classes},
        )
        if bridge_anchors:
            owners = sorted({c["bridge_target_domain"] for c in bridge_anchors})
            report(
                f"     Cross-domain anchors: {len(bridge_anchors)} class(es) "
                f"via declared bridges to {', '.join(owners)}"
            )
            ref_classes = ref_classes + bridge_anchors

        # DD-185: a global anchor may only override to a class this domain can
        # actually see (home modules + declared bridges); anything else is a
        # boundary question for a human, not a silent reassignment.
        pool_class_names = {str(c.get("name") or "") for c in ref_classes}

        # DD-070: widened STEP-2 property pool spanning the whole accelerator.
        if cross_module:
            home_uri_set = set(domain_uris)
            property_ref_classes = extract_ref_model_inventory(
                sorted(accelerator_uri_modules.keys()),
                catalog_path,
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

        # DD-045: property-range index for deterministic transform hints.
        # F3 (toolkit-optimizations): also consumed by the object-property target
        # resolver, so it is built unconditionally (cheap, deterministic).
        range_index = _build_property_range_index(ref_classes)

        # F3: governed class name → URI, so the object-property resolver can tell a
        # resolvable target entity from an ungoverned/absent one.
        class_uri_by_name = _build_class_uri_index(ref_classes)

        # DD-188: the class URIs this domain can actually see, so an entity
        # projection's target_candidates resolve against the domain's own import
        # closure rather than against whatever the pack would prefer globally.
        projection_closure_uris = frozenset(class_uri_by_name.values())

        # DD-069: property-label index for the deterministic review pass (always
        # built — cheap, and the review flags are an always-on quality guard).
        review_label_index = _build_property_label_index(ref_classes)

        # Stable signature of the reference model for cache-key invalidation.
        ref_signature = compute_entry_hash(
            [
                [c.get("name", ""), [p.get("name", "") for p in c.get("properties", [])]]
                for c in ref_classes
            ]
        )
        align_params = {
            # Issue #182: algorithm/prompt-contract version invalidates per-table
            # cache entries when alignment output semantics change.
            "algorithm_version": ALIGNMENT_ALGORITHM_VERSION,
            "model": model,
            "custom_confidence_floor": round(float(custom_confidence_floor), 4),
            # Issues #517/#520 — see ALIGNMENT_POOL_CONTRACT.
            "pool_contract": ALIGNMENT_POOL_CONTRACT,
            "max_prompt_classes": max_prompt_classes,
            "retry_min_confidence": retry_min_confidence,
            "retry_min_mapped_ratio": retry_min_mapped_ratio,
            "ref_signature": ref_signature,
        }
        if cross_module:
            # DD-070: cross-module results must not collide with home-only ones.
            align_params["cross_module"] = True
            align_params["accelerator"] = accelerator or ""
            align_params["cross_module_signature"] = compute_entry_hash(
                [
                    [
                        c.get("ref_class_id", c.get("name", "")),
                        [p.get("name", "") for p in c.get("properties", [])],
                    ]
                    for c in property_ref_classes
                ]
            )

        alignment = DomainAlignment(
            domain=domain_id,
            domain_uris=domain_uris,
            generated_at=datetime.now(timezone.utc).isoformat(),
            model_used=model,
            affinity_sha256=affinity_hash,
            alignment_params_sha256=params_hash or None,
            excluded_tables=excluded_by_domain.get(domain_id, []),
        )

        # uri-anchor-contract: a previously-persisted "resolved" unresolved_anchor
        # decision (a human choosing a URI among what were once contradictory
        # confirmed aliases) must be honored on this and future runs — merge
        # tolerantly loads it (a missing/legacy/malformed file is never fatal;
        # backward-compatible loading diagnostics only).
        existing_anchors: list[UnresolvedAnchor] = []
        anchor_doc_path: Path | None = None
        if emit_output and output_dir is not None:
            anchor_doc_path = unresolved_anchors_path(output_dir, domain_id)
            existing_anchors, anchor_load_diagnostics = load_unresolved_anchors_doc(anchor_doc_path)
            for diag in anchor_load_diagnostics:
                report(f"     ⚠ {diag}", level="verbose")
        resolved_anchor_overrides: dict[str, str] = {
            a.id: a.resolved_uri
            for a in existing_anchors
            if a.status == "resolved" and a.resolved_uri
        }
        unresolved_records: list[UnresolvedAnchor] = []

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
                return {
                    "system": system,
                    "table": table,
                    "columns": [],
                    "result": None,
                    "likely_entity": tbl_info.get("likely_entity", ""),
                }

            likely_entity = tbl_info.get("likely_entity", "")
            indicative_columns = tbl_info.get("indicative_columns", [])

            # uri-anchor-contract: resolve the table's anchor from confirmed
            # discovery evidence *before* any name-similarity/LLM class
            # selection runs, so an explicit confirmed URI always wins.
            anchor_res = resolve_table_anchor(likely_entity, alias_index, ref_classes)
            anchor_id = unresolved_anchor_id(domain_id, system, table)
            if anchor_res.status == "ambiguous":
                # A human may have already resolved this exact ambiguity in a
                # prior run (see the "resolved" unresolved_anchor merge above)
                # — honor that decision rather than re-raising the same
                # ambiguity forever.
                prior_uri = resolved_anchor_overrides.get(anchor_id)
                if prior_uri and prior_uri in anchor_res.candidate_uris:
                    resolved_cls = next(
                        (c for c in ref_classes if str(c.get("uri", "")) == prior_uri),
                        None,
                    )
                    if resolved_cls is not None:
                        anchor_res = AnchorResolution(
                            status="confirmed",
                            resolved_uri=prior_uri,
                            resolved_name=str(resolved_cls.get("name", "")),
                            candidate_uris=(prior_uri,),
                            evidence=(
                                f"human-resolved unresolved_anchor {anchor_id} -> {prior_uri}",
                            ),
                        )

            if anchor_res.status == "ambiguous":
                # uri-anchor-contract: never silently pick the "nearest" class
                # here — no LLM call, no columns, so a table this evidently
                # ambiguous never produces a property claim. Not cached (like
                # provider_failure): must re-resolve fresh every run in case
                # the conformance artifact is corrected.
                return {
                    "system": system,
                    "table": table,
                    "columns": columns,
                    "result": {
                        "ref_class": "",
                        "ref_class_confidence": 0.0,
                        "ref_class_status": "unresolved",
                        "column_alignments": [],
                        "generation_outcome": OUTCOME_FALLBACK_ONLY,
                    },
                    "cache_key": None,
                    "from_cache": False,
                    "likely_entity": likely_entity,
                    "anchor_resolution": anchor_res,
                }

            anchor_override = anchor_res.resolved_name if anchor_res.status == "confirmed" else None

            # DD-185: fall back to the global anchor call's verdict. Applied only
            # above the confidence floor and only when the class is in this
            # domain's pool — recorded as status "anchored", never "confirmed".
            anchor_status = "confirmed"
            anchor_confidence: float | None = None
            if anchor_override is None and global_anchors:
                ga = global_anchors.get((system, table)) or {}
                ga_anchor = str(ga.get("anchor") or "")
                ga_conf = float(ga.get("confidence") or 0.0)
                if ga_anchor and ga_conf < ANCHOR_CONFIDENCE_FLOOR:
                    anchor_counters["low_confidence"] += 1
                elif ga_anchor and ga_anchor not in pool_class_names:
                    anchor_counters["outside_pool"] += 1
                    logger.info(
                        "Global anchor %s for %s.%s is outside domain '%s' pool; "
                        "not applied.", ga_anchor, system, table, domain_id,
                    )
                elif ga_anchor:
                    anchor_override = ga_anchor
                    anchor_status = "anchored"
                    anchor_confidence = ga_conf
                    anchor_counters["applied"] += 1

            cache_key = compute_entry_hash(
                {
                    "system": system,
                    "table": table,
                    "likely_entity": likely_entity,
                    "columns": [
                        {
                            "name": c.get("name"),
                            "type": c.get("data_type"),
                            "samples": c.get("samples", []),
                        }
                        for c in columns
                    ],
                    "params": align_params,
                    # uri-anchor-contract: a confirmed-anchor status change (evidence
                    # added/changed) must invalidate the per-table cache entry.
                    # DD-185: the status distinguishes human-confirmed from
                    # global-anchored, so switching between them re-runs the table.
                    "anchor_override": anchor_override or "",
                    "anchor_status": anchor_status if anchor_override else "",
                }
            )
            cached = cache.get(cache_key)
            if cached is not None:
                return {
                    "system": system,
                    "table": table,
                    "columns": columns,
                    "result": cached,
                    "cache_key": cache_key,
                    "from_cache": True,
                    "likely_entity": likely_entity,
                    "anchor_resolution": anchor_res,
                }

            shortlist_classes = _select_ref_classes_for_table(
                table,
                columns,
                ref_classes,
                likely_entity=likely_entity,
                indicative_columns=indicative_columns,
                max_classes=max_prompt_classes,
            )
            # Issue #517: the class a measurement belongs on is usually not the
            # anchor but a value object hanging off it, and the flat lexical
            # shortlist does not reach it. Expand from the anchor first so it gets
            # first claim on the budget.
            anchor_class_name = anchor_override or next(
                (
                    str(c.get("name") or "")
                    for c in shortlist_classes
                    if str(c.get("name") or "").lower() == str(likely_entity).lower()
                ),
                "",
            )
            try:
                if cross_module:
                    # DD-070: STEP 1 stays home-scoped; STEP 2 uses the widened
                    # accelerator pool. No full-inventory retry (cost guard).
                    prop_pool = _select_property_pool(
                        table,
                        columns,
                        property_ref_classes,
                        shortlist_classes,
                        indicative_columns=indicative_columns,
                    )
                    prop_pool = prop_pool + expand_value_object_pool(
                        prop_pool,
                        property_ref_classes,
                        anchor_class=anchor_class_name,
                    )
                    result = align_table(
                        client,
                        model,
                        table,
                        columns,
                        prop_pool,
                        likely_entity=likely_entity,
                        table_ref_classes=shortlist_classes,
                        anchor_override=anchor_override,
                        anchor_status=anchor_status,
                        anchor_confidence=anchor_confidence,
                        class_cautions=class_cautions,
                        glossary_terms=glossary_terms,
                        trace_session_id=trace_session_id,
                    )
                else:
                    value_objects = expand_value_object_pool(
                        shortlist_classes,
                        property_ref_classes,
                        anchor_class=anchor_class_name,
                    )
                    result = align_table(
                        client,
                        model,
                        table,
                        columns,
                        shortlist_classes + value_objects,
                        likely_entity=likely_entity,
                        # Value objects widen STEP 2 only: a tonnage class is a home
                        # for a column, never a home for a table. Left None when
                        # nothing was added, so those prompts are unchanged.
                        table_ref_classes=shortlist_classes if value_objects else None,
                        anchor_override=anchor_override,
                        anchor_status=anchor_status,
                        anchor_confidence=anchor_confidence,
                        class_cautions=class_cautions,
                        glossary_terms=glossary_terms,
                        trace_session_id=trace_session_id,
                    )
                    if len(shortlist_classes) < len(
                        ref_classes
                    ) and _should_retry_with_full_inventory(
                        result,
                        len(columns),
                        min_confidence=retry_min_confidence,
                        min_mapped_ratio=retry_min_mapped_ratio,
                    ):
                        full_result = align_table(
                            client,
                            model,
                            table,
                            columns,
                            ref_classes,
                            likely_entity=likely_entity,
                            anchor_override=anchor_override,
                            anchor_status=anchor_status,
                            anchor_confidence=anchor_confidence,
                            class_cautions=class_cautions,
                            glossary_terms=glossary_terms,
                            trace_session_id=trace_session_id,
                        )
                        if _alignment_result_score(
                            full_result, len(columns)
                        ) >= _alignment_result_score(result, len(columns)):
                            result = full_result
            except Exception as exc:  # noqa: BLE001 — isolate a single table failure
                logger.warning("Alignment failed for %s.%s: %s", system, table, exc)
                result = {
                    "ref_class": "",
                    "ref_class_confidence": 0.0,
                    "column_alignments": [],
                    "generation_outcome": OUTCOME_PROVIDER_FAILURE,
                    "generation_error": sanitize_provider_error(exc),
                }
            return {
                "system": system,
                "table": table,
                "columns": columns,
                "result": result,
                "cache_key": cache_key,
                "from_cache": False,
                "likely_entity": likely_entity,
                "anchor_resolution": anchor_res,
            }

        # Live progress. A full run is tens of minutes of silence otherwise, with no way
        # to tell a slow provider from a hung one, and no basis for deciding whether to
        # wait. map_concurrent already fires on_result as each table lands, so this costs
        # nothing but the print. Completion order is arrival order, not input order --
        # which is itself the clearest evidence that the tables really are running
        # concurrently rather than one after another.
        domain_started = time.monotonic()

        def _on_table_done(entry: dict[str, Any] | None, _total: int = len(tables)) -> None:
            nonlocal tables_done
            tables_done += 1
            if entry is None:
                return
            outcome = (entry.get("result") or {}).get("generation_outcome")
            mark = "✓" if outcome == OUTCOME_SEMANTIC_SUCCESS else "✗"
            if entry.get("from_cache"):
                mark = "•"
            mapped = len(
                [
                    c
                    for c in ((entry.get("result") or {}).get("column_alignments") or [])
                    if c.get("ref_property")
                ]
            )
            columns = len(entry.get("columns") or [])
            elapsed = time.monotonic() - domain_started
            report(
                f"     {mark} [{tables_done}/{total_tables}] {entry.get('table')} "
                f"— {mapped}/{columns} columns mapped ({elapsed:.0f}s)"
            )

        processed = map_concurrent(
            _process_table, tables, max_workers=max_workers, on_result=_on_table_done
        )
        report(
            f"     └ {domain_id} done in {time.monotonic() - domain_started:.0f}s "
            f"({tables_done}/{total_tables} tables, "
            f"{time.monotonic() - run_started:.0f}s elapsed)"
        )

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

            if (
                not entry.get("from_cache")
                and entry.get("cache_key")
                # Alignment-reliability: never persist a provider_failure result —
                # caching it would silently freeze a transient outage as
                # permanent "no match" output and suppress all future retries.
                and result.get("generation_outcome") != OUTCOME_PROVIDER_FAILURE
            ):
                cache.put(entry["cache_key"], result)

            # Build TableAlignment (deterministic; no LLM)
            col_alignments = []
            custom_cols = []
            address_hints: list[dict[str, Any]] = []
            # F3 (toolkit-optimizations): object-property relationship candidates
            # synthesized when a scalar column maps to an object property with no
            # resolvable governed target entity. Merged into rel_candidates below.
            objprop_candidates: list[dict[str, Any]] = []
            for ca in result.get("column_alignments", []):
                col_data_type = next(
                    (c["data_type"] for c in columns if c["name"] == ca["column"]),
                    "unknown",
                )
                if ca["alignment"] == "custom":
                    custom_cols.append(
                        _build_custom_column(
                            ca,
                            col_data_type,
                            confidence_floor=custom_confidence_floor,
                        )
                    )
                else:
                    ref_class_name = ca.get("ref_class", result.get("ref_class", ""))
                    col_obj = next((c for c in columns if c["name"] == ca["column"]), None)
                    column_alignment = ColumnAlignment(
                        column=ca["column"],
                        data_type=col_data_type,
                        ref_class=ref_class_name,
                        ref_property=ca["ref_property"],
                        alignment=ca["alignment"],
                        confidence=ca["confidence"],
                        rationale=ca.get("rationale", ""),
                    )
                    # DD-075: masked, default-on sample evidence for the mapper.
                    if col_obj is not None:
                        col_is_pii = is_pii_column(
                            col_obj.get("name"),
                            target_property=ca["ref_property"],
                            sample_values=col_obj.get("samples"),
                        )
                        evidence = _render_example_values(
                            col_obj.get("samples"),
                            is_pii=col_is_pii,
                            include=include_sample_values,
                        )
                        if evidence:
                            column_alignment.example_values = evidence
                    if include_mapping_hints and col_obj is not None:
                        prop_range = _lookup_property_range(
                            range_index, ref_class_name, ca["ref_property"]
                        )
                        hint = _transform_hint(col_obj, ca["ref_property"], prop_range)
                        column_alignment.transform_hint = hint["transform_hint"]
                        column_alignment.transform_confidence = hint["transform_confidence"]
                        column_alignment.requires_human_confirmation = hint[
                            "requires_human_confirmation"
                        ]
                        column_alignment.transform_rationale = hint["transform_rationale"]
                        # DD-075: advisory CAST-vs-samples compatibility note.
                        compat = _transform_compat_note(col_obj, prop_range)
                        if compat:
                            column_alignment.transform_compat = compat
                    # DD-069: deterministic plausibility/address review flag.
                    review_reason = _review_column_alignment(
                        column_name=ca["column"],
                        data_type=col_data_type,
                        ref_class=ref_class_name,
                        ref_property=ca["ref_property"],
                        confidence=ca["confidence"],
                        label_index=review_label_index,
                        projections=projections,
                    )
                    if review_reason:
                        column_alignment.review = True
                        column_alignment.review_reason = review_reason
                        if include_mapping_hints and _is_projection_part_column(
                            ca["column"], projections
                        ):
                            address_hints.append(
                                {
                                    "type": "address_candidate",
                                    "source_table": table,
                                    "source_column": ca["column"],
                                    "current_property": ca["ref_property"],
                                    "requires_human_confirmation": True,
                                    "rationale": review_reason,
                                }
                            )
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
                            acc = cross_module_acc.setdefault(
                                key,
                                {
                                    "ref_class": ref_class_name,
                                    "ref_module": meta["module"],
                                    "ref_module_uri": meta["source_uri"],
                                    "belongs_to_domains": list(domains),
                                    "source_columns": [],
                                },
                            )
                            acc["source_columns"].append(f"{system}.{table}.{ca['column']}")
                    # F3 (toolkit-optimizations), generalized by proposal-quality:
                    # a scalar column mapped to an object property must not count
                    # as a resolved scalar mapping when (a) the target entity does
                    # NOT resolve to a governed class (original F3 check), (b) the
                    # column is a technical/audit actor reference, (c) a
                    # specialized location property is selected without typed-role
                    # evidence, or (d) a non-location object property is selected
                    # without target/entity identifier evidence. Downgrade to a
                    # passthrough custom column and — except for the audit-actor
                    # case, which is passthrough-only per finding #9 — emit a
                    # relationship candidate, so the column keeps exactly one
                    # governed disposition (no double count). When none of these
                    # fire, the mapping is kept unchanged (byte-identical).
                    obj_target = _resolve_object_property_target(
                        ca["ref_property"],
                        ref_class_name,
                        range_index,
                        class_uri_by_name,
                    )
                    if obj_target is not None:
                        downgrade_reason = _object_relationship_downgrade_reason(
                            column=ca["column"],
                            data_type=col_data_type,
                            ref_property=ca["ref_property"],
                            target_resolved=bool(obj_target["target_resolved"]),
                        )
                        if downgrade_reason is not None:
                            custom_cols.append(
                                _build_object_property_passthrough(
                                    ca["column"],
                                    col_data_type,
                                    ca["ref_property"],
                                    obj_target,
                                    reason=downgrade_reason,
                                )
                            )
                            if downgrade_reason != "technical_actor":
                                objprop_candidates.append(
                                    _build_object_property_candidate(
                                        table,
                                        ca["column"],
                                        ca["ref_property"],
                                        obj_target,
                                        reason=downgrade_reason,
                                    )
                                )
                            continue
                    col_alignments.append(column_alignment)

            # F6: reconcile every source column against what the model returned.
            # Prompt truncation (MAX_COLUMNS_PER_PROMPT) or an omitting model can
            # drop columns before they reach the registry; materialize any
            # unaccounted column as a passthrough candidate so the governance gate
            # never reports a truncated registry as complete.
            # uri-anchor-contract: skipped entirely for an "unresolved" table —
            # there is no LLM result to reconcile against (the call never ran)
            # and every column would otherwise be materialized as a passthrough
            # claim against a table that has no resolved class anchor yet.
            is_unresolved_anchor = result.get("ref_class_status") == "unresolved"
            if not is_unresolved_anchor:
                accounted = {ca.column for ca in col_alignments}
                accounted |= {str(cc.get("column", "") or "") for cc in custom_cols}
                for col in columns:
                    cname = str(col.get("name", "") or "")
                    if cname and cname not in accounted:
                        custom_cols.append(_build_reconciled_passthrough(col))
                        accounted.add(cname)
            src_count, src_hash = _source_column_digest(columns)

            # DD-171: flag role-shaped proposals on a class the pattern library cautions
            # about. Runs here, after the class is resolved, because the caution is
            # keyed by class and only now is it known.
            _resolved_uri = next(
                (
                    str(c.get("uri") or "")
                    for c in ref_classes
                    if c.get("name") == result.get("ref_class")
                ),
                "",
            )
            flag_risky_proposals(
                custom_cols, class_cautions=class_cautions, ref_class_uri=_resolved_uri
            )
            # DD-179: the relational check no single-column rule can make — it
            # needs the whole table's mapping at once.
            consistency_flags = flag_role_collisions(
                columns, result.get("column_alignments", []) or []
            )
            for flag in consistency_flags:
                logger.info("Alignment consistency (%s.%s): %s", system, table, flag)

            ta = TableAlignment(
                system=system,
                table=table,
                ref_class=result.get("ref_class", ""),
                ref_class_confidence=result.get("ref_class_confidence", 0.0),
                columns=col_alignments,
                custom_columns=custom_cols,
                consistency_flags=consistency_flags,
                ref_class_status=result.get("ref_class_status", "matched"),
                rejected_ref_class=result.get("rejected_ref_class"),
                source_column_count=src_count,
                source_column_sha256=src_hash,
                likely_entity=str(entry.get("likely_entity", "") or ""),
                generation_outcome=result.get("generation_outcome", OUTCOME_SEMANTIC_SUCCESS),
                generation_error=result.get("generation_error"),
            )
            if ta.generation_outcome != OUTCOME_SEMANTIC_SUCCESS:
                ta.generation_provider = provider_config.provider
                ta.generation_model = model

            # uri-anchor-contract: attach the resolved/ambiguous anchor evidence
            # to the table, and — for "unresolved" — record a separate versioned
            # unresolved_anchor (never a claim) so the decision survives future
            # re-runs instead of being silently guessed away.
            anchor_res_entry: AnchorResolution | None = entry.get("anchor_resolution")
            if anchor_res_entry is not None and anchor_res_entry.status == "confirmed":
                ta.likely_entity_uri = anchor_res_entry.resolved_uri or ""
            elif anchor_res_entry is not None and anchor_res_entry.status == "ambiguous":
                ta.anchor_candidate_uris = list(anchor_res_entry.candidate_uris)
                unresolved_records.append(
                    UnresolvedAnchor(
                        id=unresolved_anchor_id(domain_id, system, table),
                        domain=domain_id,
                        system=system,
                        table=table,
                        likely_entity=str(entry.get("likely_entity", "") or ""),
                        candidate_uris=list(anchor_res_entry.candidate_uris),
                        reason=REASON_AMBIGUOUS_CONFIRMED_ALIAS,
                        evidence=list(anchor_res_entry.evidence),
                    )
                )

            if include_mapping_hints:
                ta.structural_hints = (
                    _detect_structural_hints(table, columns, ref_classes) + address_hints
                )
            # Issue #192 (Phase A1) → DD-188: deterministic, additive
            # relationship-candidate detection (no LLM, no cross-module widening),
            # driven entirely by the pack's entity-projection vocabulary — no pack
            # config, no candidates.
            # uri-anchor-contract / proposal-quality: an "unresolved" table has no
            # resolved class anchor — it must emit neither claims (already the
            # case above) nor relationship clusters, so URI-first resolution
            # always wins over a name-based guess at a relationship target.
            if is_unresolved_anchor:
                rel_candidates: list[dict[str, Any]] = []
            else:
                rel_candidates = _detect_projection_relationship_candidates(
                    table,
                    columns,
                    projections=projections,
                    closure_uris=projection_closure_uris,
                    domain=domain_id,
                )
                # F3, generalized (proposal-quality): cluster object-property
                # candidates by (source table, relationship, target, cardinality)
                # so several contributing columns collapse into one candidate
                # instead of one-per-column.
                rel_candidates = rel_candidates + _cluster_object_property_candidates(
                    objprop_candidates,
                    domain=domain_id,
                )
            if rel_candidates:
                ta.relationship_candidates = rel_candidates
            alignment.tables.append(ta)

            matched = len(col_alignments)
            custom = len(custom_cols)
            cache_marker = " (cached)" if entry.get("from_cache") else ""

            # Alignment-reliability: tally run-wide outcomes and keep a failed
            # table *visible* (not just in --verbose) rather than letting it
            # masquerade as an ordinary (if empty) semantic result.
            if ta.generation_outcome == OUTCOME_PROVIDER_FAILURE:
                run_attempted += 1
                run_provider_failures += 1
                report(
                    f"     ⚠ {system}.{table} → semantic generation FAILED: {ta.generation_error}"
                )
            elif ta.generation_outcome == OUTCOME_SEMANTIC_SUCCESS:
                run_attempted += 1
                run_semantic_success += 1

            report(
                f"     ├─ {system}.{table} → {ta.ref_class} "
                f"({matched} matched, {custom} custom){cache_marker}",
                level="verbose",
            )

        # WS1 (issue #182): domain-wide catch-all suppression — a suggested
        # property reused across many dissimilar custom columns is an unreliable
        # fallback sink (e.g. stageCode/customsID), not a real signal. Null those
        # suggestions before they reach the rollup or the YAML.
        all_custom = [cc for ta in alignment.tables for cc in ta.custom_columns]
        downgraded = _downgrade_catch_all_suggestions(all_custom)
        if downgraded:
            report(
                f"     🧹 Suppressed {downgraded} catch-all custom suggestion(s)",
                level="verbose",
            )

        # Build reference rollup (home-domain classes only — DD-070 keeps cross-
        # module matches in a separate section to avoid distorting coverage%).
        alignment.reference_rollup = _build_reference_rollup(alignment, ref_classes)

        # DD-070: emit cross-module matches, deterministically sorted.
        if cross_module_acc:
            matches = []
            for _key, m in cross_module_acc.items():
                matches.append(
                    {
                        "ref_class": m["ref_class"],
                        "ref_module": m["ref_module"],
                        "ref_module_uri": m["ref_module_uri"],
                        "belongs_to_domains": m["belongs_to_domains"],
                        "source_columns": sorted(m["source_columns"]),
                    }
                )
            alignment.cross_module_matches = sorted(
                matches, key=lambda r: (r["ref_module"], r["ref_class"])
            )
            report(f"     🔗 Cross-module matches: {len(alignment.cross_module_matches)} class(es)")

        # Stage output (Claim Registry — DD-094); committed after the loop.
        merged_anchors = merge_preserving_anchor_resolutions(unresolved_records, existing_anchors)
        alignment.unresolved_anchors = [a.to_dict() for a in merged_anchors]
        alignments.append(alignment)

        # Alignment-reliability — per-domain write gate. A domain where *every*
        # table failed the provider call has no trustworthy semantic content at
        # all: never overwrite an existing (possibly good) registry with it.
        # A domain where every table is fallback_only (no reference model to
        # align against — the LLM was never called) is a distinct, deliberate
        # "incomplete" case gated behind an explicit opt-in flag rather than a
        # hard block, since it may still be a useful placeholder once approved.
        domain_outcomes = [ta.generation_outcome for ta in alignment.tables]
        domain_total = len(domain_outcomes)
        domain_provider_failures = domain_outcomes.count(OUTCOME_PROVIDER_FAILURE)
        domain_fallback_only = domain_outcomes.count(OUTCOME_FALLBACK_ONLY)

        if emit_output:
            if domain_total and domain_provider_failures == domain_total:
                report(
                    f"     ⛔ Skipped writing {domain_id}: semantic generation "
                    f"failed for all {domain_total} table(s); any existing "
                    "claims file was left untouched."
                )
            elif (
                domain_total and domain_fallback_only == domain_total and not allow_fallback_output
            ):
                report(
                    f"     ⛔ Skipped writing {domain_id}: no reference model "
                    f"resolved for any of its {domain_total} table(s) "
                    "(fallback-only, incomplete). Pass --allow-fallback-output "
                    "to write it anyway."
                )
            else:
                staged_outputs.append(
                    {
                        "kind": "write",
                        "domain": domain_id,
                        "alignment": alignment,
                        "anchors": merged_anchors,
                        "anchor_path": anchor_doc_path,
                    }
                )

    if generation_stats is not None:
        generation_stats["attempted"] = run_attempted
        generation_stats["semantic_success"] = run_semantic_success
        generation_stats["provider_failure"] = run_provider_failures

    cache.flush()

    # Alignment-reliability: a total run failure must never be reported as
    # success — and must never leave a registry behind while claiming it wrote
    # nothing. Every write of this run is staged above and committed only below,
    # so raising here guarantees the on-disk state is exactly what it was before
    # the run (including for a domain that mixes provider_failure and
    # fallback_only tables, and for a fallback-only domain opted in via
    # --allow-fallback-output).
    if run_attempted and not run_semantic_success:
        raise AlignmentTotalFailureError(
            f"Semantic alignment failed for all {run_attempted} attempted "
            "table(s) — no provider call succeeded across the run. No claim "
            "registries were written; existing files (if any) were left "
            "untouched. See the per-table errors above."
        )

    # Commit the staged writes, in domain order, now that the run is known to
    # carry at least some real semantic content (or to have attempted nothing).
    for staged in staged_outputs:
        if staged["kind"] == "cached":
            output_files.append(staged["path"])
            continue
        out_path = write_alignment_output(staged["alignment"], output_dir, model=model)
        output_files.append(out_path)
        report(f"     ✓ Written: {out_path.name}")

        # uri-anchor-contract: write the versioned unresolved-anchors record
        # alongside the claims registry, only when there is something to say
        # (either this run found ambiguous anchors, or a prior run's file
        # already exists and must be preserved/updated rather than silently
        # orphaned).
        merged_anchors = staged["anchors"]
        anchor_doc_path = staged["anchor_path"]
        if merged_anchors and anchor_doc_path is not None:
            write_unresolved_anchors_doc(anchor_doc_path, staged["domain"], merged_anchors)
            open_count = sum(1 for a in merged_anchors if a.status == "open")
            report(
                f"     🧭 Unresolved anchors: {open_count} open, "
                f"{len(merged_anchors) - open_count} resolved "
                f"— {anchor_doc_path.name}"
            )

    if global_anchors:
        report(
            f"  ⚓ Anchor overrides: {anchor_counters['applied']} applied, "
            f"{anchor_counters['outside_pool']} outside domain pool, "
            f"{anchor_counters['low_confidence']} below confidence floor"
        )

    # DD-184: this is a short-lived CLI process; without an explicit flush the
    # buffered events are lost at exit and the run appears never to have happened.
    flush_tracing()
    return output_files, alignments


def run_propose_alignment(
    analysis_dir: Path,
    sources_dir: Path,
    catalog_path: Path | None,
    output_dir: Path,
    **kwargs: Any,
) -> list[Path]:
    """Run source alignment and write advisory ``*-alignment.yaml`` files."""
    kwargs.pop("emit_output", None)
    paths, _ = _propose_alignments(
        analysis_dir,
        sources_dir,
        catalog_path,
        output_dir,
        emit_output=True,
        **kwargs,
    )
    return paths


def build_domain_alignments(
    analysis_dir: Path,
    sources_dir: Path,
    catalog_path: Path | None,
    **kwargs: Any,
) -> list[DomainAlignment]:
    """Build the in-memory :class:`DomainAlignment` objects without writing.

    The pure pipeline behind :func:`run_propose_alignment`: runs affinity intake,
    LLM alignment, and the deterministic column/custom/review/cross-module passes,
    returning the rich alignment objects. No domain-level skip and no files are
    written, so callers (tests, introspection) can assert on the full alignment
    surface — including exploration metadata that the Claim Registry omits.
    """
    kwargs.pop("emit_output", None)
    _, alignments = _propose_alignments(
        analysis_dir,
        sources_dir,
        catalog_path,
        None,
        emit_output=False,
        **kwargs,
    )
    return alignments


def _read_alignment_affinity_hash(path: Path) -> str:
    """Return the affinity hash recorded in an advisory alignment."""
    return str(_read_alignment_metadata(path).get("affinity_sha256", "") or "")


def _read_alignment_params_hash(path: Path) -> str:
    """Return the algorithm-parameter hash recorded in an advisory alignment."""
    return str(_read_alignment_metadata(path).get("alignment_params_sha256", "") or "")


def _read_alignment_metadata(path: Path) -> dict[str, Any]:
    """Read an advisory alignment document tolerantly."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Reference rollup builder
# ---------------------------------------------------------------------------


def _build_reference_rollup(
    alignment: DomainAlignment,
    ref_classes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a reference-class-centric rollup from table-centric alignments.

    WS4 (issue #182): only properties that genuinely belong to a class's reference
    model are counted as matched, so ``coverage_pct`` can never exceed 100% (the
    previous code added *any* ``ref_property`` blindly, producing >100% coverage —
    a hallucination signal that misled the modeler). Properties matched against a
    class that does not declare them are recorded as ``hallucinated_properties`` and
    surfaced (count + capped sample) rather than silently normalized away.
    """
    #: Max hallucinated-property names retained per class for the surfaced sample.
    _MAX_HALLUCINATED_SAMPLE = 10
    class_data: dict[str, dict[str, Any]] = {}

    # Initialize from reference model
    for cls in ref_classes:
        cls_name = cls["name"]
        ref_props = {p["name"] for p in cls.get("properties", [])}
        class_data[cls_name] = {
            "ref_class": cls_name,
            "ref_label": cls.get("label", cls_name),
            "ref_props": ref_props,
            "ref_properties_total": len(ref_props),
            "matched_properties": set(),
            "hallucinated_properties": set(),
            "source_tables": [],
            "custom_extensions": [],
        }

    # Populate from alignments
    for ta in alignment.tables:
        # Track which tables feed each class
        primary_cls = ta.ref_class
        if primary_cls and primary_cls in class_data:
            class_data[primary_cls]["source_tables"].append(f"{ta.system}.{ta.table}")

        for ca in ta.columns:
            cls_name = ca.ref_class or primary_cls
            if cls_name not in class_data:
                continue
            if not ca.ref_property:
                continue
            cd = class_data[cls_name]
            if ca.ref_property in cd["ref_props"]:
                cd["matched_properties"].add(ca.ref_property)
            else:
                # A property mapped to a class that does not declare it — an
                # AI-hallucination signal. Count it, never inflate coverage.
                cd["hallucinated_properties"].add(ca.ref_property)

        for cc in ta.custom_columns:
            if primary_cls and primary_cls in class_data:
                class_data[primary_cls]["custom_extensions"].append(
                    {
                        "column": cc["column"],
                        "suggested_property": cc.get("suggested_property", ""),
                        "source": f"{ta.system}.{ta.table}",
                    }
                )

    # Convert to serializable list
    rollup = []
    for cls_name, data in class_data.items():
        matched = data["matched_properties"]
        total = data["ref_properties_total"]
        coverage = round(len(matched) / total * 100, 1) if total else 0.0
        hallucinated = sorted(data["hallucinated_properties"])
        entry = {
            "ref_class": cls_name,
            "ref_label": data["ref_label"],
            "ref_properties_total": total,
            "matched_properties": len(matched),
            "coverage_pct": coverage,
            "source_tables": data["source_tables"],
            "custom_extensions_count": len(data["custom_extensions"]),
        }
        if hallucinated:
            entry["hallucinated_properties_count"] = len(hallucinated)
            entry["hallucinated_properties"] = hallucinated[:_MAX_HALLUCINATED_SAMPLE]
        rollup.append(entry)

    return sorted(rollup, key=lambda r: r["coverage_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def alignment_to_dict(alignment: DomainAlignment) -> dict[str, Any]:
    """Build the serializable mapping for a domain alignment (pure).

    Extracted from :func:`write_alignment_output` so the same structure can feed
    both the (retired) alignment YAML writer and the Claim Registry converter
    (DD-094). Does not touch the filesystem and does not merge preserved
    dispositions — callers do that before serializing.
    """
    data: dict[str, Any] = {
        "schema_version": ALIGNMENT_HASH_SCHEMA_VERSION,
        # Issue #182: algorithm/prompt-contract version of the producing toolkit.
        "algorithm_version": alignment.algorithm_version,
        "domain": alignment.domain,
        "domain_uris": alignment.domain_uris,
        "generated_at": alignment.generated_at,
        "model_used": alignment.model_used,
        # DD-094: digest of the affinity (system, table) set for the freshness gate.
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
        # WS6 (issue #182): surface a non-clean anchor status so a hallucinated or
        # unanchored table is visible without re-running the LLM.
        if ta.ref_class_status and ta.ref_class_status != "matched":
            table_dict["ref_class_status"] = ta.ref_class_status
        if ta.rejected_ref_class:
            table_dict["rejected_ref_class"] = ta.rejected_ref_class
        # F6: persist the true source column count/hash (only when captured) so the
        # governance gate can detect columns dropped before the registry.
        if ta.source_column_count:
            table_dict["source_column_count"] = ta.source_column_count
        if ta.source_column_sha256:
            table_dict["source_column_sha256"] = ta.source_column_sha256
        # F2/F7: persist the candidate business entity so the grain-conflict detector
        # in alignment_to_registry can flag distinct-grain collapses onto one class.
        if ta.likely_entity:
            table_dict["likely_entity"] = ta.likely_entity
        # uri-anchor-contract: persist the confirmed-anchor URI (only when the
        # anchor was actually resolved from confirmed evidence) alongside the
        # display-only likely_entity, and the candidate URIs that made an
        # anchor ambiguous (only when it was).
        if ta.likely_entity_uri:
            table_dict["likely_entity_uri"] = ta.likely_entity_uri
        if ta.anchor_candidate_uris:
            table_dict["anchor_candidate_uris"] = list(ta.anchor_candidate_uris)
        # DD-179: relational consistency warnings, emitted only when a rule fired
        # so a clean table's output stays byte-identical.
        if ta.consistency_flags:
            table_dict["consistency_flags"] = list(ta.consistency_flags)
        # Alignment-reliability: emit the generation outcome + safe metadata only
        # when it is not the happy path, so a fully-successful run's output stays
        # byte-identical to before. ``generation_error`` is already sanitized.
        if ta.generation_outcome != OUTCOME_SEMANTIC_SUCCESS:
            table_dict["generation_outcome"] = ta.generation_outcome
            if ta.generation_provider:
                table_dict["generation_provider"] = ta.generation_provider
            if ta.generation_model:
                table_dict["generation_model"] = ta.generation_model
            if ta.generation_error:
                table_dict["generation_error"] = ta.generation_error
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
            # DD-075: emit sample evidence + compat note only when populated.
            if ca.example_values:
                col_dict["example_values"] = ca.example_values
            if ca.transform_compat is not None:
                col_dict["transform_compat"] = ca.transform_compat
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
        # Issue #192 (Phase A1): emit relationship candidates only when detected.
        if ta.relationship_candidates:
            table_dict["relationship_candidates"] = ta.relationship_candidates
        data["tables"].append(table_dict)

    # DD-070: emit cross-module sections only in cross-module mode (default unchanged)
    if alignment.alignment_params_sha256:
        data["alignment_params_sha256"] = alignment.alignment_params_sha256
    if alignment.cross_module_matches:
        data["cross_module_matches"] = alignment.cross_module_matches
    # #528 follow-up: an excluded table has to be auditable after the run, not
    # only in the console scrollback — emitted only when the screen actually
    # dropped something, so an unaffected domain's file is byte-identical.
    if alignment.excluded_tables:
        data["excluded_tables"] = alignment.excluded_tables

    return data


def write_alignment_output(
    alignment: DomainAlignment,
    output_dir: Path,
    *,
    model: str = "",
) -> Path:
    """Write the complete advisory alignment without creating governance state.

    The file carries an AI-attribution header (DD-178). Every mapping in it was
    proposed by a language model, and the YAML reads as settled fact once it is
    on disk — so the artifact states its own provenance and review status rather
    than relying on whoever opens it remembering how it was made.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{alignment.domain}-alignment.yaml"
    header = provenance_comment(
        "propose-alignment",
        extra=ai_attribution(
            model=model or resolve_role_model(ROLE_ALIGNMENT),
            role=ROLE_ALIGNMENT,
            seed=resolve_ai_seed(ROLE_ALIGNMENT),
            reasoning_effort=resolve_reasoning_effort(ROLE_ALIGNMENT),
        ),
        ai_generated=True,
    )
    target.write_text(
        header
        + yaml.safe_dump(alignment_to_dict(alignment), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return target
