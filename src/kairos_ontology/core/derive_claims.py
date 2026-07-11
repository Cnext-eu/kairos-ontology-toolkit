# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic multi-source evidence aggregation into candidate claims (DD-EL-5).

``derive-claims`` reduces hand-authoring of the Claim Registry by aggregating
**already-produced** evidence into ``proposed`` candidate claims. It is a pure,
AI-free enhancement on top of the working Slice 1/2 path and never blocks it.

The semantically-hard work is done *upstream*: ``analyse-sources`` (affinity) and
``propose-alignment`` (column→property) already resolve which class / property a
source maps to, and ``propose-alignment`` already writes
``model/claims/{domain}-claims.yaml``. This module is the deterministic
**merge/enrich** layer that joins those outputs with additional deterministic
evidence streams and attaches **multiple** ``evidence_sources`` per claim:

1. the existing claims registry (base — preserves prior candidates + curation),
2. ``analyse-sources`` affinity (``*-affinity.yaml``),
3. ``import-tmdl`` concept-mapping (``*-concept-mapping.yaml``),
4. SKOS mappings (``model/mappings/*.ttl``),
5. sample-derived signals (enum-candidate / FK-shape).

**C4 guard:** every derived/new claim is ``status: proposed`` — never
auto-``approved``. Human decisions survive re-runs via
:func:`claim_registry.merge_preserving_decisions`. Conflicting evidence is
*surfaced* (rationale notes / low confidence), never silently resolved.

A future opt-in ``--llm-reconcile`` pass (tie-breaking / rationale synthesis,
*with* a cost banner) is deliberately deferred to a later slice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .claim_registry import (
    Claim,
    ClaimRegistry,
    EvidenceSource,
    dump_registry,
    load_registry,
    merge_preserving_decisions,
)
from .migrate_claims import _slug
from ._cache import compute_entry_hash, open_cache
from ._concurrency import map_concurrent

logger = logging.getLogger(__name__)

#: Concept-mapping ``action`` (import-tmdl) → claim disposition hint. Only used
#: when creating a brand-new candidate; existing claims keep their disposition
#: (the C4 guard — TMDL evidence never silently re-dispositions a human's claim).
TMDL_ACTION_TO_DISPOSITION: dict[str, str] = {
    "use": "claim",
    "specialize": "specialize",
    "new_class": "gap",
    "skip": "skip",
}

#: A column with at most this many distinct sample values is flagged as an
#: enum candidate (reference-data / discriminator signal).
ENUM_MAX_DISTINCT = 8

#: Column-name suffixes that indicate a foreign-key / identifier shape.
_FK_SUFFIXES = ("id", "code", "key", "fk", "no", "nr")


# ---------------------------------------------------------------------------
# Stable claim ids (identical scheme to migrate_claims / propose_alignment)
# ---------------------------------------------------------------------------


def class_claim_id(domain: str, ref_class: str) -> str:
    """Stable id for a class claim (matches the alignment/migration scheme)."""
    return f"{domain}-{_slug(ref_class)}"


def property_claim_id(domain: str, ref_class: str, ref_property: str) -> str:
    """Stable id for a property claim (matches the alignment/migration scheme)."""
    return f"{domain}-{_slug(ref_class)}-{_slug(ref_property)}"


# ---------------------------------------------------------------------------
# Evidence model + result
# ---------------------------------------------------------------------------


@dataclass
class DeriveStats:
    """Per-domain summary of what an aggregation pass did (for CLI + tests)."""

    domain: str
    base_claims: int = 0
    new_claims: int = 0
    evidence_added: int = 0
    unrouted_tmdl: int = 0
    conflicts: int = 0
    affinity_tables: int = 0
    skos_links: int = 0

    @property
    def total_claims(self) -> int:
        return self.base_claims + self.new_claims


def _evidence_key(ev: EvidenceSource) -> tuple:
    return (ev.type, ev.system, ev.table, ev.column, ev.model, ev.measure, ev.note)


def _clone_claim(claim: Claim) -> Claim:
    """Return a structural copy with a fresh evidence list (no shared mutables)."""
    return Claim(
        id=claim.id,
        type=claim.type,
        status=claim.status,
        disposition=claim.disposition,
        origin=claim.origin,
        class_uri=claim.class_uri,
        property_uri=claim.property_uri,
        owner=claim.owner,
        evidence_sources=list(claim.evidence_sources),
        silver_impact=claim.silver_impact,
        rationale=claim.rationale,
        proposed_confidence=claim.proposed_confidence,
        superseded_by=claim.superseded_by,
    )


# ---------------------------------------------------------------------------
# Sample-derived signals
# ---------------------------------------------------------------------------


def detect_sample_signal(
    column: str, data_type: str | None, samples: list[str] | None
) -> str | None:
    """Return a deterministic ``sample_signal`` note for a column, or ``None``.

    Two deterministic signals are recognised:

    * **enum-candidate** — when concrete sample values are supplied and the
      distinct count is small (``<= ENUM_MAX_DISTINCT`` over at least two
      samples), the column likely encodes a reference-data / discriminator set.
    * **fk-shape** — a name-based fallback (works without samples): an
      identifier-shaped column name (``*id`` / ``*code`` / ``*key`` / ...).

    The enum signal takes precedence when both apply.
    """
    values = [str(v) for v in (samples or []) if str(v).strip()]
    if len(values) >= 2:
        distinct = len(set(values))
        if distinct <= ENUM_MAX_DISTINCT:
            return f"enum-candidate: {distinct} distinct sample value(s)"
    name = column.lower().rstrip("_")
    if any(name.endswith(suffix) for suffix in _FK_SUFFIXES) and name not in _FK_SUFFIXES:
        return "fk-shape: identifier-named column"
    return None


# ---------------------------------------------------------------------------
# Per-domain aggregation
# ---------------------------------------------------------------------------


def derive_claims_for_domain(
    domain: str,
    existing: ClaimRegistry,
    *,
    affinity_tables: list[dict[str, Any]] | None = None,
    tmdl_tables: list[dict[str, Any]] | None = None,
    skos_links: list[dict[str, Any]] | None = None,
    column_samples: dict[tuple[str, str, str], list[str]] | None = None,
) -> tuple[ClaimRegistry, DeriveStats]:
    """Aggregate evidence into a candidate registry for one domain (pure).

    Starts from a clone of ``existing`` so prior candidates and human-curated
    claims are never dropped, then enriches matching claims with new evidence and
    appends brand-new ``proposed`` candidates. Deterministic: evidence is
    de-duplicated and the claim list is returned sorted by id.

    The result is intended to be fed through
    :func:`claim_registry.merge_preserving_decisions` (against the same
    ``existing``) before writing, so decided claims keep their curated fields.
    """
    affinity_tables = affinity_tables or []
    tmdl_tables = tmdl_tables or []
    skos_links = skos_links or []
    column_samples = column_samples or {}

    stats = DeriveStats(domain=domain)

    # Working set keyed on stable id (clones, so we never mutate the input).
    claims: dict[str, Claim] = {}
    for claim in existing.claims:
        if claim.id:
            claims[claim.id] = _clone_claim(claim)
    stats.base_claims = len(claims)

    evidence_keys: dict[str, set[tuple]] = {
        cid: {_evidence_key(e) for e in c.evidence_sources} for cid, c in claims.items()
    }

    def add_evidence(cid: str, ev: EvidenceSource) -> bool:
        key = _evidence_key(ev)
        seen = evidence_keys.setdefault(cid, set())
        if key in seen:
            return False
        claims[cid].evidence_sources.append(ev)
        seen.add(key)
        stats.evidence_added += 1
        return True

    # Index: (system, table) -> ref_class, from coverage; and -> class claim ids,
    # from each claim's source_table evidence (the alignment/migration join key).
    table_to_ref_class: dict[tuple[str, str], str] = {}
    for syscov in existing.coverage:
        for tbl in syscov.tables:
            if tbl.ref_class:
                table_to_ref_class[(syscov.system, tbl.table)] = tbl.ref_class

    table_to_class_claims: dict[tuple[str, str], list[str]] = {}
    column_to_property_claims: dict[tuple[str, str, str], list[str]] = {}
    ref_class_to_class_claim: dict[str, str] = {}
    for cid, claim in claims.items():
        for ev in claim.evidence_sources:
            if ev.type == "source_table" and ev.system and ev.table:
                if claim.type in ("class", "reference_data"):
                    table_to_class_claims.setdefault((ev.system, ev.table), []).append(cid)
            elif ev.type == "source_column" and ev.system and ev.table and ev.column:
                if claim.type in ("property", "measure"):
                    column_to_property_claims.setdefault(
                        (ev.system, ev.table, ev.column), []
                    ).append(cid)
    for (system, table), ref_class in table_to_ref_class.items():
        cid = class_claim_id(domain, ref_class)
        if cid in claims:
            ref_class_to_class_claim[ref_class] = cid
            table_to_class_claims.setdefault((system, table), [])
            if cid not in table_to_class_claims[(system, table)]:
                table_to_class_claims[(system, table)].append(cid)

    # --- 1) Affinity ---------------------------------------------------------
    for tbl in affinity_tables:
        system = str(tbl.get("system", "") or "")
        table = str(tbl.get("table", "") or "")
        if not table:
            continue
        stats.affinity_tables += 1
        likely = str(tbl.get("likely_entity", "") or "")
        conf = tbl.get("confidence")
        note = f"likely_entity={likely}" if likely else "domain affinity"
        ev = EvidenceSource(type="affinity", system=system, table=table, note=note)
        targets = table_to_class_claims.get((system, table))
        if targets:
            for cid in targets:
                add_evidence(cid, ev)
        else:
            # Affinity-only table: no alignment anchor yet → new candidate.
            cid = f"{domain}-affinity-{_slug(system)}-{_slug(table)}"
            if cid not in claims:
                claims[cid] = Claim(
                    id=cid,
                    type="class",
                    status="proposed",
                    disposition="claim",
                    origin="imported",
                    rationale=(
                        "Derived from affinity: table has domain affinity but no "
                        "reference-model alignment anchor yet — run propose-alignment "
                        "or confirm a class."
                    ),
                    proposed_confidence=float(conf) if isinstance(conf, (int, float)) else None,
                    evidence_sources=[
                        EvidenceSource(type="source_table", system=system, table=table),
                    ],
                )
                evidence_keys[cid] = {_evidence_key(e) for e in claims[cid].evidence_sources}
                table_to_class_claims.setdefault((system, table), []).append(cid)
                stats.new_claims += 1
            add_evidence(cid, ev)

    # --- 2) TMDL concept-mapping --------------------------------------------
    for tbl in tmdl_tables:
        ref_match = str(tbl.get("reference_model_match", "") or "").strip()
        action = str(tbl.get("action", "") or "").strip()
        model_name = str(tbl.get("_model", "") or "") or None
        tmdl_name = str(tbl.get("tmdl_name", "") or "") or None
        note = f"action={action}" if action else "tmdl concept-mapping"
        ev = EvidenceSource(
            type="tmdl_concept_mapping", model=model_name, table=tmdl_name, note=note
        )
        cid = class_claim_id(domain, ref_match) if ref_match else None
        if cid and cid in claims:
            add_evidence(cid, ev)
            # Surface tension: TMDL says skip but the claim is set to materialize.
            if action == "skip" and claims[cid].disposition in ("claim", "specialize"):
                stats.conflicts += 1
                add_evidence(
                    cid,
                    EvidenceSource(
                        type="tmdl_concept_mapping",
                        model=model_name,
                        table=tmdl_name,
                        note="conflict: TMDL action=skip vs materializing disposition",
                    ),
                )
        elif action == "new_class" and ref_match:
            new_id = f"{domain}-tmdl-{_slug(ref_match)}"
            if new_id not in claims:
                claims[new_id] = Claim(
                    id=new_id,
                    type="class",
                    status="proposed",
                    disposition=TMDL_ACTION_TO_DISPOSITION.get(action, "gap"),
                    origin="imported",
                    rationale=(
                        f"Derived from TMDL: action '{action}' for "
                        f"'{ref_match}' — no reference-model anchor; confirm or model."
                    ),
                    evidence_sources=[ev],
                )
                evidence_keys[new_id] = {_evidence_key(ev)}
                stats.new_claims += 1
        else:
            stats.unrouted_tmdl += 1

    # --- 3) SKOS mappings ----------------------------------------------------
    for link in skos_links:
        target = str(link.get("target", "") or "")
        predicate = str(link.get("predicate", "") or "")
        system = str(link.get("system", "") or "")
        table = str(link.get("table", "") or "")
        column = str(link.get("column", "") or "")
        kind = link.get("kind")  # "class" | "property"
        note = f"predicate={predicate}" if predicate else "skos mapping"
        ev = EvidenceSource(
            type="skos_mapping",
            system=system or None,
            table=table or None,
            column=column or None,
            note=note,
        )
        matched = False
        if kind == "class" and target:
            cid = ref_class_to_class_claim.get(target) or class_claim_id(domain, target)
            if cid in claims:
                add_evidence(cid, ev)
                matched = True
        elif kind == "property" and target:
            # Match property claims whose id encodes this ref_property (id suffix).
            suffix = f"-{_slug(target)}"
            for cid in claims:
                if claims[cid].type in ("property", "measure") and cid.endswith(suffix):
                    add_evidence(cid, ev)
                    matched = True
        if matched:
            stats.skos_links += 1

    # --- 4) Sample-derived signals ------------------------------------------
    for (system, table, column), claim_ids in column_to_property_claims.items():
        data_type = None
        signal = detect_sample_signal(column, data_type, column_samples.get((system, table, column)))
        if not signal:
            continue
        ev = EvidenceSource(
            type="sample_signal", system=system, table=table, column=column, note=signal
        )
        for cid in claim_ids:
            add_evidence(cid, ev)

    ordered = sorted(claims.values(), key=lambda c: c.id)
    derived = ClaimRegistry(
        domain=existing.domain or domain,
        schema_version=existing.schema_version,
        generated_at=existing.generated_at,
        algorithm_version=existing.algorithm_version,
        freshness=existing.freshness,
        coverage=existing.coverage,
        claims=ordered,
    )
    return derived, stats


# ---------------------------------------------------------------------------
# Evidence loaders (deterministic file readers)
# ---------------------------------------------------------------------------


def load_affinity_by_domain(analysis_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Group ``*-affinity.yaml`` tables by primary ``domain`` (schema_version 2)."""
    by_domain: dict[str, list[dict[str, Any]]] = {}
    if not analysis_dir or not analysis_dir.is_dir():
        return by_domain
    for affinity_file in sorted(analysis_dir.glob("*-affinity.yaml")):
        try:
            data = yaml.safe_load(affinity_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read affinity %s: %s", affinity_file, exc)
            continue
        if not isinstance(data, dict) or data.get("schema_version") != 2:
            continue
        system = data.get("system", affinity_file.stem.replace("-affinity", ""))
        for tbl in data.get("tables", []) or []:
            domain = str(tbl.get("domain", "") or "")
            if not domain:
                continue
            by_domain.setdefault(domain, []).append({
                "system": system,
                "table": tbl.get("table", ""),
                "likely_entity": tbl.get("likely_entity", ""),
                "confidence": tbl.get("confidence"),
            })
    return by_domain


def load_tmdl_concept_mappings(tmdl_dir: Path) -> list[dict[str, Any]]:
    """Load every ``*-concept-mapping.yaml`` table (with its model name attached)."""
    tables: list[dict[str, Any]] = []
    if not tmdl_dir or not tmdl_dir.is_dir():
        return tables
    for mapping_file in sorted(tmdl_dir.glob("*-concept-mapping.yaml")):
        try:
            data = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read concept-mapping %s: %s", mapping_file, exc)
            continue
        if not isinstance(data, dict):
            continue
        model_name = str(data.get("model_name", "") or mapping_file.stem)
        for tbl in data.get("tables", []) or []:
            if not isinstance(tbl, dict):
                continue
            entry = dict(tbl)
            entry["_model"] = model_name
            tables.append(entry)
    return tables


#: SKOS match predicates that establish a source→domain link (source_coverage).
_SKOS_MATCH_PREDICATES = {
    "http://www.w3.org/2004/02/skos/core#exactMatch": "exactMatch",
    "http://www.w3.org/2004/02/skos/core#closeMatch": "closeMatch",
    "http://www.w3.org/2004/02/skos/core#narrowMatch": "narrowMatch",
    "http://www.w3.org/2004/02/skos/core#broadMatch": "broadMatch",
    "http://www.w3.org/2004/02/skos/core#relatedMatch": "relatedMatch",
}


def _decode_bronze_subject(uri: str) -> tuple[str, str, str]:
    """Decode a bronze subject URI into ``(system, table, column)``.

    Convention (see ``model/mappings/*.ttl``): the namespace's last path segment
    is the source system; the local name is ``Table`` (table-level) or
    ``Table_Column`` (column-level, split on the first underscore).
    """
    frag = uri.rsplit("#", 1)
    local = frag[1] if len(frag) == 2 else uri.rsplit("/", 1)[-1]
    base = frag[0] if len(frag) == 2 else uri.rsplit("/", 1)[0]
    system = base.rstrip("/").rsplit("/", 1)[-1]
    if "_" in local:
        table, column = local.split("_", 1)
    else:
        table, column = local, ""
    return system, table, column


def load_skos_links(mappings_dir: Path) -> list[dict[str, Any]]:
    """Parse ``model/mappings/*.ttl`` into source→domain SKOS link records.

    Each record: ``{system, table, column, target, kind, predicate}`` where
    ``kind`` is ``"property"`` when the subject is column-level (``Table_Column``)
    else ``"class"``. ``target`` is the domain concept's local name.
    """
    links: list[dict[str, Any]] = []
    if not mappings_dir or not mappings_dir.is_dir():
        return links
    ttl_files = sorted(mappings_dir.glob("*.ttl"))
    if not ttl_files:
        return links
    try:
        from rdflib import Graph, URIRef
    except Exception as exc:  # noqa: BLE001
        logger.warning("rdflib unavailable; skipping SKOS evidence: %s", exc)
        return links

    for ttl in ttl_files:
        graph = Graph()
        try:
            graph.parse(ttl, format="turtle")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not parse mapping %s: %s", ttl, exc)
            continue
        for pred_uri, pred_name in _SKOS_MATCH_PREDICATES.items():
            for subj, obj in graph.subject_objects(URIRef(pred_uri)):
                system, table, column = _decode_bronze_subject(str(subj))
                obj_str = str(obj)
                target = obj_str.rsplit("#", 1)[-1] if "#" in obj_str else obj_str.rsplit("/", 1)[-1]
                links.append({
                    "system": system,
                    "table": table,
                    "column": column,
                    "target": target,
                    "kind": "property" if column else "class",
                    "predicate": pred_name,
                })
    return links


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class DeriveReport:
    """Aggregate result across all processed domains."""

    domain_stats: list[DeriveStats] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)

    @property
    def total_evidence_added(self) -> int:
        return sum(s.evidence_added for s in self.domain_stats)

    @property
    def total_new_claims(self) -> int:
        return sum(s.new_claims for s in self.domain_stats)


def run_derive_claims(
    claims_dir: Path,
    *,
    analysis_dir: Path | None = None,
    mappings_dir: Path | None = None,
    tmdl_dir: Path | None = None,
    column_samples: dict[str, dict[tuple[str, str, str], list[str]]] | None = None,
    domains_filter: list[str] | None = None,
    max_workers: int = 8,
    force: bool = False,
    write: bool = True,
) -> DeriveReport:
    """Aggregate evidence into every domain's Claim Registry under ``claims_dir``.

    Reads each existing ``{domain}-claims.yaml`` (the base — typically produced by
    ``propose-alignment``), enriches it with affinity / TMDL / SKOS / sample
    evidence, and writes the merged registry back, preserving human decisions via
    :func:`claim_registry.merge_preserving_decisions`. All derived/new claims are
    ``proposed``.

    Parity with the AI pre-modeling commands: domains are aggregated through a
    bounded pool (``max_workers``; 1 = serial) and an unchanged domain is skipped
    via a sidecar cache keyed on its full evidence-input digest (``force``
    bypasses the cache). Aggregation is deterministic, so output is identical for
    any ``max_workers``.
    """
    report = DeriveReport()
    affinity_by_domain = load_affinity_by_domain(analysis_dir) if analysis_dir else {}
    tmdl_tables = load_tmdl_concept_mappings(tmdl_dir) if tmdl_dir else []
    skos_all = load_skos_links(mappings_dir) if mappings_dir else []
    column_samples = column_samples or {}

    registries = sorted(claims_dir.glob("*-claims.yaml")) if claims_dir.is_dir() else []
    filters = [f.strip().lower() for f in (domains_filter or []) if f.strip()]

    cache_dir = analysis_dir if (analysis_dir and analysis_dir.is_dir()) else claims_dir
    cache = open_cache(cache_dir, "derive-claims", enabled=not force)

    def _aggregate(reg_path: Path) -> tuple[DeriveStats, Path, ClaimRegistry] | None:
        domain = reg_path.name.replace("-claims.yaml", "")
        try:
            existing = load_registry(reg_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping unreadable registry %s: %s", reg_path, exc)
            return None
        derived, stats = derive_claims_for_domain(
            domain,
            existing,
            affinity_tables=affinity_by_domain.get(domain, []),
            tmdl_tables=tmdl_tables,
            skos_links=skos_all,
            column_samples=column_samples.get(domain),
        )
        merged = merge_preserving_decisions(derived, existing)
        return stats, reg_path, merged

    targets = [
        p for p in registries
        if not filters or any(f in p.name.replace("-claims.yaml", "").lower() for f in filters)
    ]
    results = map_concurrent(_aggregate, targets, max_workers=max_workers)

    for item in results:
        if item is None:
            continue
        stats, reg_path, merged = item
        report.domain_stats.append(stats)
        if not write:
            continue
        rendered = dump_registry(merged)
        key = compute_entry_hash({"domain": stats.domain, "output": rendered})
        if cache.get(key) is not None and reg_path.read_text(encoding="utf-8") == rendered:
            continue  # unchanged — skip the rewrite
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(rendered, encoding="utf-8")
        cache.put(key, True)
        report.written.append(reg_path)

    cache.flush()
    return report
