# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology domain-coverage`` core logic (issue #393).

Real, live evidence motivated this: a hub can have several fully authored domain
ontologies with zero active ``owl:imports`` in ``_master.ttl`` -- every prior
domain-authoring pass reported "``_master.ttl`` unchanged" as if that were
expected, when it is actually a real gap (a domain that is modeled, bound, and
validated but unreachable from the hub's single ontology entry point).

This module reports, per data domain, the union of:
  - whether the domain is listed in the resolved accelerator's blueprint
    (``data-domains.yaml``, via :func:`kairos_ontology.core.analyse_sources.load_data_domains`),
  - whether it has an authored domain ontology TTL under ``model/ontologies/``
    (via :func:`kairos_ontology.core.hub_inspection._ontology_domains`),
  - whether it has at least one EntityBinding
    (via :func:`kairos_ontology.core.hub_inspection._binding_domains`),
  - whether its declared ontology IRI is a live ``owl:imports`` in ``_master.ttl``
    (via :func:`kairos_ontology.core.master_ontology.list_active_master_imports`),
  - how many discovered **source tables** have affinity to the domain, read from the
    persisted ``integration/sources/_analysis/*-affinity.yaml`` reports (DD-160).

The source-affinity column (issue #496/#498, DD-160) is what turns this table from
"what did we author?" into "what did we author *versus what the source data needs*?".
A domain the blueprint deferred, that nevertheless has source tables assigned to it, is
real business data with nowhere to land -- the deterministic signal that the domain should
be modeled/bound rather than deferred. Before DD-160 the affinity analysis and the binding
inventory both existed but were never joined, so the gap was invisible to everything except
a hand-written report.

This is advisory only: it never fails a hub, and there is no ``--strict`` mode
(deliberately deferred -- see issue #393 suggestion #5, also deferred).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from .analyse_sources import load_data_domains
from .catalog_utils import _declared_ontology_iri
from .hub_inspection import _binding_domains, _ontology_domains
from .master_ontology import list_active_master_imports

#: v1: the coverage table (accelerator + domains rows).
#: v2 (issue #418, DD-157): the CLI JSON envelope gains an optional ``explain`` payload
#: (``--explain <domain>``: owns/does_not_own/blueprint imports) and an optional ``owns``
#: payload (``--owns <ClassName>``: inventory-backed reverse ownership lookup), and an
#: optional ``owns_batch`` payload (``--owns A,B,C``: multi-class batch lookup, issue
#: #439). The base ``domains`` rows are unchanged.
#: v3 (issue #496/#498, DD-160): each ``domains`` row gains ``source_tables``,
#: ``source_tables_secondary`` and ``status``; the envelope
#: gains a top-level ``unassigned_source_tables`` array (tables the affinity pass could
#: not assign to any domain -- previously dropped on the floor entirely).
SCHEMA_VERSION = 3

#: ``DomainCoverageRow.status`` values. Deterministic verdicts derived from the join of
#: source affinity x authored ontology x authored bindings.
STATUS_BOUND = "bound"
STATUS_DEFERRED = "deferred"
STATUS_NOT_MODELED = "not-modeled"
STATUS_NO_ELIGIBLE_SOURCES = "no-eligible-sources"

#: Human-readable meaning of each status, reused by the CLI renderer and by
#: ``kairos-ontology next`` so the two can never drift.
STATUS_DESCRIPTIONS: dict[str, str] = {
    STATUS_BOUND: "has at least one EntityBinding",
    STATUS_DEFERRED: (
        "source tables are assigned to this domain but nothing is bound -- real data "
        "with nowhere to land; model/bind it rather than deferring it"
    ),
    STATUS_NOT_MODELED: (
        "source tables are assigned to this domain but no domain ontology TTL exists -- "
        "candidate domain to add"
    ),
    STATUS_NO_ELIGIBLE_SOURCES: "no source table is assigned to this domain",
}


@dataclass(frozen=True)
class DomainCoverageRow:
    """One domain's coverage across blueprint, authoring, binding, import, and sources."""

    domain: str
    in_blueprint: Optional[bool]  # None => "n/a" (no accelerator pack installed at all)
    modeled: bool
    bound: bool
    imported: bool
    #: Source tables whose *primary* affinity domain is this one. ``None`` when no
    #: affinity reports were available at all (distinct from a real zero).
    source_tables: Optional[int] = None
    #: Source tables listing this domain under ``secondary_domains``.
    source_tables_secondary: Optional[int] = None
    #: One of the ``STATUS_*`` constants, or ``None`` when no affinity evidence exists
    #: (a verdict without source evidence would be a guess).
    status: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "in_blueprint": self.in_blueprint,
            "modeled": self.modeled,
            "bound": self.bound,
            "imported": self.imported,
            "source_tables": self.source_tables,
            "source_tables_secondary": self.source_tables_secondary,
            "status": self.status,
        }


@dataclass(frozen=True)
class UnassignedSourceTable:
    """A discovered source table the affinity pass could not assign to any domain.

    Before DD-160 these were dropped silently: ``analyse_sources`` blanks ``domain``
    whenever the LLM assignment fails, and every downstream consumer skipped rows with an
    empty domain, so the table appeared in no artifact at all. Surfacing them is the whole
    point -- an unassigned table is the strongest "the ontology has no home for this"
    signal the toolkit can produce without another model call.
    """

    system: str
    table: str
    total_columns: int
    likely_entity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "table": self.table,
            "total_columns": self.total_columns,
            "likely_entity": self.likely_entity,
        }


@dataclass(frozen=True)
class DomainCoverageReport:
    """Full domain-coverage table plus the accelerator it was resolved against."""

    accelerator: Optional[str]
    rows: tuple[DomainCoverageRow, ...]
    unassigned_source_tables: tuple[UnassignedSourceTable, ...] = ()
    #: False when no ``*-affinity.yaml`` was found, so consumers can say "run
    #: analyse-sources first" instead of reporting a misleading zero.
    has_affinity_evidence: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "accelerator": self.accelerator,
            "domains": [row.to_dict() for row in self.rows],
            "has_affinity_evidence": self.has_affinity_evidence,
            "unassigned_source_tables": [t.to_dict() for t in self.unassigned_source_tables],
        }


def _normalize_iri(iri: str) -> str:
    return iri.rstrip("/")


@dataclass(frozen=True)
class SourceAffinityEvidence:
    """Per-domain source-table counts plus the tables no domain claimed."""

    found_reports: bool
    primary: dict[str, int]
    secondary: dict[str, int]
    unassigned: tuple[UnassignedSourceTable, ...]


def load_source_affinity(analysis_dir: Optional[Path]) -> SourceAffinityEvidence:
    """Count source tables per domain from persisted ``*-affinity.yaml`` reports.

    Deliberately a *separate* reader from
    :func:`kairos_ontology.core.propose_alignment.load_affinity_reports`: that one groups
    tables for alignment and must skip unassigned rows (there is no domain to pick
    candidate classes from), whereas this one exists precisely to keep them. Reading the
    persisted artifact means this stays deterministic and offline -- the LLM ran once, at
    ``analyse-sources`` time.

    Unreadable or wrong-schema files are skipped with a debug log rather than raising:
    ``domain-coverage`` is advisory and must never fail a hub.
    """
    primary: dict[str, int] = {}
    secondary: dict[str, int] = {}
    unassigned: list[UnassignedSourceTable] = []
    found = False

    if analysis_dir is None or not Path(analysis_dir).is_dir():
        return SourceAffinityEvidence(False, primary, secondary, ())

    for affinity_file in sorted(Path(analysis_dir).glob("*-affinity.yaml")):
        try:
            with open(affinity_file, encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except Exception:  # defensive: a corrupt report must not break the table
            continue
        if not isinstance(data, dict) or data.get("schema_version") != 2:
            continue

        found = True
        system = data.get("system") or affinity_file.stem.replace("-affinity", "")
        for table in data.get("tables") or []:
            if not isinstance(table, dict):
                continue
            domain = (table.get("domain") or "").strip()
            if not domain:
                unassigned.append(
                    UnassignedSourceTable(
                        system=str(system),
                        table=str(table.get("table", "")),
                        total_columns=int(table.get("total_columns") or 0),
                        likely_entity=str(table.get("likely_entity") or ""),
                    )
                )
                continue
            primary[domain] = primary.get(domain, 0) + 1
            for extra in table.get("secondary_domains") or []:
                if not isinstance(extra, dict):
                    continue
                extra_domain = (extra.get("domain") or "").strip()
                if extra_domain:
                    secondary[extra_domain] = secondary.get(extra_domain, 0) + 1

    unassigned.sort(key=lambda t: (t.system, t.table))
    return SourceAffinityEvidence(found, primary, secondary, tuple(unassigned))


def load_source_affinity_tables(analysis_dir: Optional[Path]) -> dict[str, dict[str, Any]]:
    """Return ``{table name: {primary, secondary, likely_entity, system}}`` from affinity.

    The per-table view of :func:`load_source_affinity`, kept separate because consumers
    want either the per-domain counts or the per-table detail, never both.
    """
    tables: dict[str, dict[str, Any]] = {}
    if analysis_dir is None or not Path(analysis_dir).is_dir():
        return tables
    for affinity_file in sorted(Path(analysis_dir).glob("*-affinity.yaml")):
        try:
            with open(affinity_file, encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("schema_version") != 2:
            continue
        system = data.get("system") or affinity_file.stem.replace("-affinity", "")
        for table in data.get("tables") or []:
            if not isinstance(table, dict) or not table.get("table"):
                continue
            secondary = tuple(
                (entry.get("domain") or "").strip()
                for entry in (table.get("secondary_domains") or [])
                if isinstance(entry, dict) and (entry.get("domain") or "").strip()
            )
            tables[str(table["table"])] = {
                "system": str(system),
                "primary": (table.get("domain") or "").strip(),
                "secondary": secondary,
                "likely_entity": str(table.get("likely_entity") or ""),
            }
    return tables


def _classify(*, bound: bool, modeled: bool, source_tables: int) -> str:
    """Derive one domain's status from the affinity x ontology x binding join.

    Deliberately does NOT try to say whether a modeled domain's classes are *bindable*
    (i.e. carry datatype properties). Answering that needs the DD-103 semantic index per
    domain, which this always-exit-0 advisory table must not pull in, and
    ``plan-sources`` already warns about a zero-datatype target class at the moment the
    author actually picks one (#484).
    """
    if bound:
        return STATUS_BOUND
    if source_tables == 0:
        return STATUS_NO_ELIGIBLE_SOURCES
    if not modeled:
        return STATUS_NOT_MODELED
    return STATUS_DEFERRED


def build_domain_coverage_report(
    *,
    ontologies_dir: Path,
    bindings_dir: Path,
    master_path: Path,
    ref_models_dir: Optional[Path],
    accelerator: Optional[str],
    analysis_dir: Optional[Path] = None,
) -> DomainCoverageReport:
    """Build the domain-coverage report for one hub.

    ``accelerator`` is the already-resolved accelerator id (or ``None`` when no
    accelerator pack is installed at all) -- resolution/ambiguity handling is the
    CLI layer's responsibility (mirroring ``check-inventory``'s precedent), not
    this function's.

    ``analysis_dir`` points at ``integration/sources/_analysis/`` (DD-160). When it is
    ``None`` or holds no affinity reports, the source columns stay ``None`` and no status
    is derived -- an absent report is reported as absent, never as "zero source tables".
    """
    blueprint_domains: dict[str, dict[str, Any]] = {}
    if accelerator and ref_models_dir is not None and Path(ref_models_dir).is_dir():
        blueprint_domains = load_data_domains(Path(ref_models_dir), accelerator=accelerator)

    ontology_domains, unreadable_domains = _ontology_domains(ontologies_dir)
    modeled_domains = ontology_domains | unreadable_domains

    binding_counts, _tier_counts = _binding_domains(bindings_dir)
    bound_domains = set(binding_counts)

    active_master_imports: set[str] = set()
    if master_path.is_file():
        try:
            active_master_imports = {
                _normalize_iri(iri) for iri in list_active_master_imports(master_path)
            }
        except Exception:  # defensive: a malformed _master.ttl must never crash this report
            active_master_imports = set()

    affinity = load_source_affinity(analysis_dir)

    # A domain that only source affinity knows about is still a real domain -- it is
    # precisely the "candidate domain to add" case, so it must widen the row set.
    all_domains = sorted(
        set(blueprint_domains) | modeled_domains | bound_domains | set(affinity.primary)
    )

    rows: list[DomainCoverageRow] = []
    for name in all_domains:
        in_blueprint = None if accelerator is None else name in blueprint_domains
        modeled = name in modeled_domains
        bound = name in bound_domains

        imported = False
        if name in ontology_domains:  # only a readable file can have a declared IRI
            ttl_path = ontologies_dir / f"{name}.ttl"
            try:
                declared_iri = _declared_ontology_iri(ttl_path)
            except Exception:  # defensive: a parse-broken domain TTL is reported elsewhere
                declared_iri = None
            if declared_iri:
                imported = _normalize_iri(declared_iri) in active_master_imports

        source_tables = affinity.primary.get(name, 0) if affinity.found_reports else None
        secondary_tables = affinity.secondary.get(name, 0) if affinity.found_reports else None
        status = (
            _classify(bound=bound, modeled=modeled, source_tables=source_tables or 0)
            if affinity.found_reports
            else None
        )

        rows.append(
            DomainCoverageRow(
                domain=name,
                in_blueprint=in_blueprint,
                modeled=modeled,
                bound=bound,
                imported=imported,
                source_tables=source_tables,
                source_tables_secondary=secondary_tables,
                status=status,
            )
        )

    return DomainCoverageReport(
        accelerator=accelerator,
        rows=tuple(rows),
        unassigned_source_tables=affinity.unassigned,
        has_affinity_evidence=affinity.found_reports,
    )


# --------------------------------------------------------------------------------------
# Domain ownership surfacing (issue #418, DD-157)
# --------------------------------------------------------------------------------------


def load_domain_ownership(
    *,
    ref_models_dir: Optional[Path],
    accelerator: Optional[str],
) -> dict[str, dict[str, Any]]:
    """Return the blueprint's per-domain ownership metadata, or ``{}`` when unavailable.

    Thin guard around :func:`load_data_domains` for the ``--explain`` surface: a hub
    with no accelerator pack (or no resolvable ``data-domains.yaml``) yields an empty
    mapping so the CLI can print a clean informational message and exit 0.
    """
    if not accelerator or ref_models_dir is None or not Path(ref_models_dir).is_dir():
        return {}
    return load_data_domains(Path(ref_models_dir), accelerator=accelerator)


@dataclass(frozen=True)
class ClassOwnershipRow:
    """One (class, asserting module) pair found in the materialized inventories.

    ``module_id`` is ``None`` when the asserting ontology is not a managed
    reference-module profile (e.g. a hub-authored class); ``domains`` is empty when
    the module is managed but no blueprint domain activates it.
    """

    class_name: str
    class_uri: str
    source_identity: str
    module_id: Optional[str]
    domains: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_name": self.class_name,
            "class_uri": self.class_uri,
            "source_identity": self.source_identity,
            "module_id": self.module_id,
            "domains": list(self.domains),
        }


@dataclass(frozen=True)
class ClassOwnershipLookup:
    """Result of the ``--owns <ClassName>`` reverse lookup (issue #418, DD-157)."""

    class_name: str
    inventories_present: bool
    rows: tuple[ClassOwnershipRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_name": self.class_name,
            "inventories_present": self.inventories_present,
            "matches": [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class ClassOwnershipBatch:
    """Result of a multi-class ``--owns A,B,C`` reverse lookup (issue #439).

    Additive to the single-name ``owns`` payload (issue #418); does not redefine
    ``ClassOwnershipLookup`` or bump ``SCHEMA_VERSION``.
    """

    class_names: tuple[str, ...]
    inventories_present: bool
    rows: tuple[ClassOwnershipRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_names": list(self.class_names),
            "inventories_present": self.inventories_present,
            "matches": [row.to_dict() for row in self.rows],
        }


def _load_inventory_files(inventory_dir: Path) -> list[Path]:
    """Return sorted inventory YAML files, or ``[]`` when the directory is absent."""
    return (
        sorted(Path(inventory_dir).glob("*-inventory.yaml"))
        if Path(inventory_dir).is_dir()
        else []
    )


def _load_module_ownership(
    ref_models_dir: Optional[Path], accelerator: Optional[str]
) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Return ``(alias_to_module, domains_by_module)`` from the accelerator blueprint."""
    from .reference_modules import load_accelerator_module_config

    alias_to_module: dict[str, str] = {}
    domains_by_module: dict[str, set[str]] = {}
    if ref_models_dir is not None and Path(ref_models_dir).is_dir():
        try:
            config = load_accelerator_module_config(Path(ref_models_dir), accelerator)
        except Exception:  # defensive: a broken blueprint must not crash an advisory lookup
            config = None
        if config is not None:
            for profile in config.profiles:
                for alias in (profile.ontology_iri, profile.catalog_uri):
                    if alias:
                        alias_to_module.setdefault(alias.rstrip("#/"), profile.id)
            for activation in config.domains:
                for module_id in activation.module_ids:
                    domains_by_module.setdefault(module_id, set()).add(activation.domain)
    return alias_to_module, domains_by_module


def _ownership_row(
    cls: dict[str, Any],
    alias_to_module: dict[str, str],
    domains_by_module: dict[str, set[str]],
) -> ClassOwnershipRow:
    name = str(cls.get("name") or "")
    uri = str(cls.get("uri") or "")
    provenance = cls.get("provenance")
    source_identity = (
        str(provenance.get("source_identity") or "")
        if isinstance(provenance, dict)
        else ""
    )
    module_id = alias_to_module.get(source_identity.rstrip("#/"))
    owned_by = (
        tuple(sorted(domains_by_module.get(module_id, ()))) if module_id else ()
    )
    return ClassOwnershipRow(
        class_name=name,
        class_uri=uri,
        source_identity=source_identity,
        module_id=module_id,
        domains=owned_by,
    )


def lookup_class_ownership(
    *,
    class_name: str,
    inventory_dir: Path,
    ref_models_dir: Optional[Path],
    accelerator: Optional[str],
) -> ClassOwnershipLookup:
    """Reverse-lookup which blueprint domain(s) own a class name (issue #418, DD-157).

    Deliberately cheap — no closure parsing: reads the already-materialized
    ``referencemodels-unpacked/*-inventory.yaml`` files, whose classes each carry
    ``provenance.source_identity`` (the asserting module's ontology IRI), maps that IRI
    to a managed module profile via
    :func:`~kairos_ontology.core.reference_modules.load_accelerator_module_config`
    (matching both ``ontology_iri`` and ``catalog_uri``, hash-namespace legacy forms
    included), then to the owning domain(s) via the blueprint's data-domain activations.
    Ownership can be plural — a module assigned to several domains yields all of them.

    Matching on the class *name* is case-insensitive. Unreadable inventories are
    skipped defensively. Rows are deduplicated on ``(class_uri, source_identity)``
    because every module inventory repeats its whole closure.
    """
    batch = lookup_class_ownership_batch(
        class_names={class_name},
        inventory_dir=inventory_dir,
        ref_models_dir=ref_models_dir,
        accelerator=accelerator,
    )
    return ClassOwnershipLookup(
        class_name=class_name,
        inventories_present=batch.inventories_present,
        rows=batch.rows,
    )


def lookup_class_ownership_batch(
    *,
    class_names: Iterable[str],
    inventory_dir: Path,
    ref_models_dir: Optional[Path],
    accelerator: Optional[str],
) -> ClassOwnershipBatch:
    """Reverse-lookup ownership for a **set** of class names in one corpus scan.

    Issue #439 — batch companion to :func:`lookup_class_ownership`. The inventory
    corpus is scanned exactly once; classes matching any requested name
    (case-insensitive) are collected. Rows are deduplicated on
    ``(class_uri, source_identity)`` across the entire batch because every module
    inventory repeats its whole closure.
    """
    wanted = {name.strip().lower() for name in class_names if name and name.strip()}
    ordered_names = tuple(sorted(wanted))

    inventory_files = _load_inventory_files(inventory_dir)
    if not inventory_files:
        return ClassOwnershipBatch(
            class_names=ordered_names, inventories_present=False, rows=()
        )

    alias_to_module, domains_by_module = _load_module_ownership(
        ref_models_dir, accelerator
    )

    seen: set[tuple[str, str]] = set()
    rows: list[ClassOwnershipRow] = []
    for inventory_path in inventory_files:
        try:
            data = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
        except Exception:  # defensive: check-inventory owns inventory health reporting
            continue
        if not isinstance(data, dict):
            continue
        for cls in data.get("classes", ()) or ():
            if not isinstance(cls, dict):
                continue
            name = str(cls.get("name") or "")
            if name.lower() not in wanted:
                continue
            row = _ownership_row(cls, alias_to_module, domains_by_module)
            key = (row.class_uri, row.source_identity)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    rows.sort(key=lambda r: (r.class_uri, r.source_identity))
    return ClassOwnershipBatch(
        class_names=ordered_names, inventories_present=True, rows=tuple(rows)
    )
