# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical deterministic completeness facts for governed source tables.

The Claim Registry remains the only governance authority.  This module joins the
committed affinity, registry, source, mapping, dbt-contract, and Silver-extension
surfaces into immutable per-domain/per-system/per-table facts.  Gate modules consume
these facts as views; proposal or conformance evidence never counts as a mapping.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import SKOS

from .claim_registry import Claim, ClaimRegistry, load_registry, registry_path
from .claim_registry import validate_registry, validation_errors
from .source_catalog import SourceCatalog, build_source_catalog

logger = logging.getLogger(__name__)

KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

_MATCH_PREDICATES = (
    SKOS.exactMatch,
    SKOS.closeMatch,
    SKOS.narrowMatch,
    SKOS.broadMatch,
    SKOS.relatedMatch,
)

#: Compatibility version for completeness evidence emitted by propose-alignment.
ALIGNMENT_HASH_SCHEMA_VERSION = 2
ALIGNMENT_ALGORITHM_VERSION = 2


@dataclass(frozen=True)
class AffinityAssignment:
    """One domain assignment for a source-system table."""

    domain: str
    system: str
    table: str
    total_columns: int = 0


@dataclass(frozen=True)
class MappingRecord:
    """One committed source-to-domain SKOS statement."""

    source_uri: str
    predicate_uri: str
    target_uri: str
    path: Path


@dataclass(frozen=True)
class SourceTableRecord:
    """Canonical source-table identity and all mapping-eligible IRIs."""

    table_uris: frozenset[str] = frozenset()
    all_uris: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RegistryTableCoverage:
    """The governed registry snapshot recorded for one source table."""

    total_columns: int
    mapped_columns: int
    custom_columns: int
    anchor_state: str
    ref_class: str | None
    source_column_count: int
    source_column_sha256: str | None


@dataclass(frozen=True)
class FreshnessFact:
    """Registry freshness evaluated against the current affinity assignment set."""

    state: str
    expected_affinity_sha256: str
    stored_affinity_sha256: str | None
    algorithm_version: int | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplacementCoverageEvidence:
    """Proof surfaces that authorize a governed source replacement."""

    source_table_iri: str
    claim_id: str
    target_class: str
    contract_model: str
    virtual_table_iri: str
    silver_source_ref: str


@dataclass(frozen=True)
class GovernedReplacementCoverage:
    """Whether a contracted dbt replacement fully covers a source table."""

    active: bool
    covered: bool
    evidence: tuple[ReplacementCoverageEvidence, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class MappingCoverage:
    """Mapping state derived only from committed SKOS and replacement evidence.

    ``state`` is ``direct``, ``governed_replacement``, ``unmapped``, or
    ``not_evaluated``.  A proposed claim, including a conformance-derived proposal,
    has no effect on ``direct``.
    """

    state: str
    direct: bool
    direct_in_registry_domain: bool
    replacement: GovernedReplacementCoverage
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GrainConflictFact:
    """A persisted registry grain-conflict signal needed by the claim gate."""

    ref_class: str
    candidate_entities: tuple[str, ...]


@dataclass(frozen=True)
class DomainCompleteness:
    """Committed registry and freshness information for one affinity domain."""

    domain: str
    registry_path: Path | None
    registry_exists: bool
    declared_domain: str | None
    load_error: str | None
    validation_errors: tuple[str, ...]
    claims: tuple[Claim, ...]
    grain_conflicts: tuple[GrainConflictFact, ...]
    freshness: FreshnessFact

    @property
    def is_valid(self) -> bool:
        """Return whether the registry loaded and passes structural validation."""

        return self.registry_exists and self.load_error is None and not self.validation_errors


@dataclass(frozen=True)
class TableCompletenessFact:
    """Canonical completeness fact for one assigned source table."""

    assignment: AffinityAssignment
    registry_coverage: RegistryTableCoverage | None
    source_table_iris: tuple[str, ...]
    source_uris: tuple[str, ...]
    mapping: MappingCoverage
    freshness: FreshnessFact

    @property
    def domain(self) -> str:
        """Return the assigned domain."""

        return self.assignment.domain

    @property
    def system(self) -> str:
        """Return the source-system key."""

        return self.assignment.system

    @property
    def table(self) -> str:
        """Return the source-table name."""

        return self.assignment.table


@dataclass(frozen=True)
class CompletenessFacts:
    """Immutable snapshot consumed by the claim and source-coverage evaluators."""

    tables: tuple[TableCompletenessFact, ...]
    domains: tuple[DomainCompleteness, ...]
    orphan_registries: tuple[DomainCompleteness, ...]
    mapping_evaluated: bool

    def tables_for_domain(self, domain: str) -> tuple[TableCompletenessFact, ...]:
        """Return deterministic facts assigned to *domain*."""

        return tuple(fact for fact in self.tables if fact.domain == domain)

    def domain_fact(self, domain: str) -> DomainCompleteness | None:
        """Return the registry/freshness fact for *domain*, if assigned."""

        return next((fact for fact in self.domains if fact.domain == domain), None)


def compute_affinity_hash(pairs: Iterable[tuple[str, str]]) -> str:
    """Return a deterministic SHA-256 over a domain's ``(system, table)`` set."""

    items = sorted({f"{system}\t{table}" for system, table in pairs})
    digest = hashlib.sha256()
    digest.update("\n".join(items).encode("utf-8"))
    return digest.hexdigest()


def load_affinity_assignments(
    analysis_dir: Path,
    *,
    excluded_systems: set[str] | None = None,
) -> tuple[AffinityAssignment, ...]:
    """Read schema-v2 affinity assignments from committed report files."""

    assignments: dict[tuple[str, str, str], AffinityAssignment] = {}
    if not analysis_dir.is_dir():
        return ()

    excluded = excluded_systems or set()
    for affinity_file in sorted(analysis_dir.glob("*-affinity.yaml")):
        try:
            with open(affinity_file, encoding="utf-8") as file:
                data = yaml.safe_load(file)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not read affinity file %s: %s", affinity_file, exc)
            continue
        if not isinstance(data, dict) or data.get("schema_version") != 2:
            logger.debug("Skipping %s (not schema_version 2)", affinity_file.name)
            continue

        system = str(data.get("system", affinity_file.stem.replace("-affinity", "")) or "")
        if system in excluded:
            logger.info("Skipping generated affinity report %s for system %s", affinity_file.name, system)
            continue
        for raw_table in data.get("tables", []):
            if not isinstance(raw_table, dict):
                continue
            domain = raw_table.get("domain", "")
            table = raw_table.get("table", "")
            if not domain or not table:
                continue
            try:
                total_columns = int(raw_table.get("total_columns", 0) or 0)
            except (TypeError, ValueError):
                total_columns = 0
            assignment = AffinityAssignment(
                domain=str(domain),
                system=system,
                table=str(table),
                total_columns=total_columns,
            )
            assignments[(assignment.domain, assignment.system, assignment.table)] = assignment

    return tuple(
        sorted(assignments.values(), key=lambda item: (item.domain, item.system, item.table))
    )


def load_affinity_domain_tables(
    analysis_dir: Path,
    *,
    excluded_systems: set[str] | None = None,
) -> dict[str, set[tuple[str, str]]]:
    """Map every domain to its assigned ``(system, table)`` set."""

    result: dict[str, set[tuple[str, str]]] = {}
    for assignment in load_affinity_assignments(
        analysis_dir,
        excluded_systems=excluded_systems,
    ):
        result.setdefault(assignment.domain, set()).add((assignment.system, assignment.table))
    return result


def load_affinity_domain_table_columns(
    analysis_dir: Path,
    *,
    excluded_systems: set[str] | None = None,
) -> dict[str, dict[tuple[str, str], int]]:
    """Map every domain to the affinity-recorded source-column counts."""

    result: dict[str, dict[tuple[str, str], int]] = {}
    for assignment in load_affinity_assignments(
        analysis_dir,
        excluded_systems=excluded_systems,
    ):
        result.setdefault(assignment.domain, {})[
            (assignment.system, assignment.table)
        ] = assignment.total_columns
    return result


def collect_mapping_records(mappings_dir: Path) -> list[MappingRecord]:
    """Return committed, mapping-eligible SKOS statements from mapping Turtle."""

    records: list[MappingRecord] = []
    if not mappings_dir or not mappings_dir.is_dir():
        return records

    for ttl in sorted(mappings_dir.rglob("*.ttl")):
        graph = Graph()
        try:
            graph.parse(ttl, format="turtle")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not parse mapping file %s: %s", ttl.name, exc)
            continue
        for predicate in _MATCH_PREDICATES:
            for subject, target in graph.subject_objects(predicate):
                if isinstance(subject, URIRef) and isinstance(target, URIRef):
                    records.append(MappingRecord(str(subject), str(predicate), str(target), ttl))
    return sorted(
        records,
        key=lambda record: (
            record.source_uri,
            record.predicate_uri,
            record.target_uri,
            str(record.path),
        ),
    )


def collect_mapped_subjects(mappings_dir: Path) -> set[str]:
    """Return source URIs participating in a committed supported SKOS mapping."""

    return {record.source_uri for record in collect_mapping_records(mappings_dir)}


def _source_table_records_from_catalog(
    catalog: SourceCatalog,
) -> dict[tuple[str, str], SourceTableRecord]:
    """Build the affinity-keyed source table index from one loaded catalog."""

    values: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
    for table in sorted(
        catalog.tables.values(),
        key=lambda item: (item.system, item.table_name, item.table_iri),
    ):
        table_uris, all_uris = values.setdefault((table.system, table.table_name), (set(), set()))
        table_uris.add(table.table_iri)
        all_uris.update(table.all_uris)
    return {
        key: SourceTableRecord(frozenset(table_uris), frozenset(all_uris))
        for key, (table_uris, all_uris) in values.items()
    }


def collect_source_table_records(
    sources_dir: Path,
) -> dict[tuple[str, str], SourceTableRecord]:
    """Index canonical Bronze tables by affinity key."""

    if not sources_dir or not sources_dir.is_dir():
        return {}
    return _source_table_records_from_catalog(build_source_catalog(sources_dir))


def collect_source_tables(sources_dir: Path) -> dict[tuple[str, str], set[str]]:
    """Return the backward-compatible source table/column URI index."""

    return {
        key: set(record.all_uris)
        for key, record in collect_source_table_records(sources_dir).items()
    }


def _registry_coverage(
    registry: ClaimRegistry,
) -> dict[tuple[str, str], RegistryTableCoverage]:
    """Extract the registry coverage records using existing last-entry semantics."""

    result: dict[tuple[str, str], RegistryTableCoverage] = {}
    for system_coverage in registry.coverage:
        for table_coverage in system_coverage.tables:
            if not system_coverage.system or not table_coverage.table:
                continue
            result[(system_coverage.system, table_coverage.table)] = RegistryTableCoverage(
                total_columns=int(table_coverage.total_columns or 0),
                mapped_columns=int(table_coverage.mapped_columns or 0),
                custom_columns=int(table_coverage.custom_columns or 0),
                anchor_state=table_coverage.anchor_state,
                ref_class=table_coverage.ref_class,
                source_column_count=int(table_coverage.source_column_count or 0),
                source_column_sha256=table_coverage.source_column_sha256,
            )
    return result


def _grain_conflicts(registry: ClaimRegistry) -> tuple[GrainConflictFact, ...]:
    """Extract only the persisted grain-conflict data required by the claim view."""

    conflicts: list[GrainConflictFact] = []
    for raw in registry.grain_conflicts:
        if not isinstance(raw, dict) or not raw.get("candidate_entities"):
            continue
        entities = raw.get("candidate_entities")
        if not isinstance(entities, list):
            continue
        conflicts.append(
            GrainConflictFact(
                ref_class=str(raw.get("ref_class", "") or ""),
                candidate_entities=tuple(str(entity) for entity in entities),
            )
        )
    return tuple(sorted(conflicts, key=lambda item: (item.ref_class, item.candidate_entities)))


def _freshness_fact(
    registry: ClaimRegistry | None,
    expected_pairs: Iterable[tuple[str, str]],
) -> FreshnessFact:
    """Evaluate registry freshness against the canonical affinity set."""

    expected_hash = compute_affinity_hash(expected_pairs)
    if registry is None:
        return FreshnessFact(
            state="unavailable",
            expected_affinity_sha256=expected_hash,
            stored_affinity_sha256=None,
            algorithm_version=None,
            reasons=("claim registry is missing",),
        )

    stored = registry.freshness.affinity_sha256
    version = registry.algorithm_version
    if not stored or (version or 0) < ALIGNMENT_ALGORITHM_VERSION:
        return FreshnessFact(
            state="unverifiable",
            expected_affinity_sha256=expected_hash,
            stored_affinity_sha256=stored,
            algorithm_version=version,
            reasons=("registry has no current verifiable affinity freshness metadata",),
        )
    if stored != expected_hash:
        return FreshnessFact(
            state="stale",
            expected_affinity_sha256=expected_hash,
            stored_affinity_sha256=stored,
            algorithm_version=version,
            reasons=("affinity assignment set changed since registry generation",),
        )
    return FreshnessFact(
        state="fresh",
        expected_affinity_sha256=expected_hash,
        stored_affinity_sha256=stored,
        algorithm_version=version,
    )


def _domain_registry_fact(
    claims_dir: Path | None,
    domain: str,
    expected_pairs: Iterable[tuple[str, str]],
    *,
    path: Path | None = None,
) -> tuple[DomainCompleteness, dict[tuple[str, str], RegistryTableCoverage]]:
    """Load one registry once and turn its relevant surfaces into immutable facts."""

    registry_file = path or (registry_path(claims_dir, domain) if claims_dir is not None else None)
    if registry_file is None or not registry_file.is_file():
        freshness = _freshness_fact(None, expected_pairs)
        return (
            DomainCompleteness(
                domain=domain,
                registry_path=registry_file,
                registry_exists=False,
                declared_domain=None,
                load_error=None,
                validation_errors=(),
                claims=(),
                grain_conflicts=(),
                freshness=freshness,
            ),
            {},
        )

    try:
        registry = load_registry(registry_file)
    except Exception as exc:  # pragma: no cover - exercised through gate view
        freshness = _freshness_fact(None, expected_pairs)
        return (
            DomainCompleteness(
                domain=domain,
                registry_path=registry_file,
                registry_exists=True,
                declared_domain=None,
                load_error=f"could not load registry: {exc}",
                validation_errors=(),
                claims=(),
                grain_conflicts=(),
                freshness=freshness,
            ),
            {},
        )

    errors = tuple(issue.message for issue in validation_errors(validate_registry(registry)))
    return (
        DomainCompleteness(
            domain=domain,
            registry_path=registry_file,
            registry_exists=True,
            declared_domain=registry.domain,
            load_error=None,
            validation_errors=errors,
            claims=tuple(registry.claims),
            grain_conflicts=_grain_conflicts(registry),
            freshness=_freshness_fact(registry, expected_pairs),
        ),
        _registry_coverage(registry),
    )


def _declared_replacement_iris(transforms_dir: Path) -> set[str]:
    """Read only declared source-replacement IRIs from dbt property files."""

    declared: set[str] = set()
    if not transforms_dir.is_dir():
        return declared
    paths = [*transforms_dir.rglob("*.yml"), *transforms_dir.rglob("*.yaml")]
    for path in sorted(paths):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict):
            continue
        for model in document.get("models", []):
            if not isinstance(model, dict):
                continue
            meta = model.get("meta")
            kairos = meta.get("kairos") if isinstance(meta, dict) else None
            replacements = kairos.get("replaces_sources") if isinstance(kairos, dict) else None
            if not isinstance(replacements, list):
                continue
            for replacement in replacements:
                if isinstance(replacement, dict) and isinstance(replacement.get("table_iri"), str):
                    declared.add(replacement["table_iri"])
    return declared


def _load_replacement_contracts(
    *,
    hub_root: Path | None,
    transforms_dir: Path | None,
    sources_dir: Path,
    applicable_source_iris: set[str],
) -> tuple[dict[str, list[object]], list[str], bool]:
    """Load live replacement contracts only when an applicable declaration exists."""

    if hub_root is None:
        return {}, [], False
    transforms = transforms_dir or hub_root / "integration" / "transforms" / "dbt"
    if not (_declared_replacement_iris(transforms) & applicable_source_iris):
        return {}, [], False

    from .dbt_contract_sync import sync_dbt_contracts
    from .dbt_contracts import discover_dbt_contracts

    try:
        sync_report = sync_dbt_contracts(
            hub_root,
            transforms_dir=transforms,
            bronze_sources_dir=sources_dir,
            check=True,
        )
        contracts = discover_dbt_contracts(transforms, hub_root)
    except ValueError as exc:
        return {}, [f"dbt contract preflight failed: {exc}"], True

    errors: list[str] = []
    if sync_report.has_drift:
        stale = ", ".join(
            f"{item.model} ({item.state})" for item in sync_report.items if item.has_drift
        )
        errors.append(
            f"custom dbt contract vocabularies are not synchronized: {stale or 'unknown drift'}"
        )

    by_source: dict[str, list[object]] = {}
    for contract in contracts:
        for replacement in contract.replaces_sources:
            by_source.setdefault(replacement.table_iri, []).append(contract)
    return by_source, errors, True


def _load_silver_source_refs(
    extensions_dir: Path | None,
) -> tuple[dict[str, set[str]], list[str]]:
    """Load target-class to selected Silver-source references."""

    refs: dict[str, set[str]] = {}
    errors: list[str] = []
    if extensions_dir is None or not extensions_dir.is_dir():
        return refs, errors
    for path in sorted(extensions_dir.rglob("*-silver-ext.ttl")):
        graph = Graph()
        try:
            graph.parse(path, format="turtle")
        except Exception as exc:
            errors.append(f"could not parse Silver extension {path}: {exc}")
            continue
        for target, source_ref in graph.subject_objects(KAIROS_EXT.silverSourceRef):
            refs.setdefault(str(target), set()).add(str(source_ref))
    return refs, errors


def _matching_source_claims(
    claims: Iterable[Claim],
    system: str,
    table: str,
    target_class: str,
) -> tuple[Claim, ...]:
    """Return approved class/reference-data claims evidencing one source table."""

    matches = [
        claim
        for claim in claims
        if claim.status == "approved"
        and claim.type in {"class", "reference_data"}
        and claim.class_uri == target_class
        and any(
            evidence.type == "source_table"
            and evidence.system == system
            and evidence.table == table
            for evidence in claim.evidence_sources
        )
    ]
    return tuple(matches)


def _in_scope(domain: str, domains_filter: list[str] | None) -> bool:
    """Apply the existing case-insensitive substring domain filter."""

    if not domains_filter:
        return True
    return any(fragment.lower() in domain.lower() for fragment in domains_filter)


def _mapping_coverage(
    assignment: AffinityAssignment,
    *,
    source_record: SourceTableRecord | None,
    mappings: tuple[MappingRecord, ...],
    mapped_subjects: set[str],
    contracts_by_source: dict[str, list[object]],
    replacement_active: bool,
    global_errors: tuple[str, ...],
    silver_refs: dict[str, set[str]],
    domain_registry: DomainCompleteness,
) -> MappingCoverage:
    """Compute the old source-coverage decision tree once for one table."""

    direct = bool(source_record and source_record.all_uris & mapped_subjects)
    record_table_iris = source_record.table_uris if source_record else frozenset()
    registry_error = domain_registry.load_error
    replacement_claims = domain_registry.claims
    if registry_error is None and (
        domain_registry.declared_domain is not None
        and domain_registry.declared_domain != assignment.domain
    ):
        registry_error = (
            f"claim registry {domain_registry.registry_path} declares domain "
            f"{domain_registry.declared_domain!r}, expected {assignment.domain!r}"
        )
        # Match the legacy source gate: a mismatched registry supplies neither
        # replacement candidates nor direct-authority targets.
        replacement_claims = ()

    candidate_by_key: dict[tuple[str, str, str], object] = {}
    for table_iri in sorted(record_table_iris):
        for contract in contracts_by_source.get(table_iri, []):
            candidate_by_key.setdefault(
                (contract.name, contract.target_class, contract.virtual_source_iri),
                contract,
            )
    candidates = tuple(
        candidate_by_key[key]
        for key in sorted(candidate_by_key)
    )
    candidate_claims = tuple(
        (contract, _matching_source_claims(
            replacement_claims,
            assignment.system,
            assignment.table,
            contract.target_class,
        ))
        for contract in candidates
    )
    domain_candidates = tuple(
        (contract, claims) for contract, claims in candidate_claims if len(claims) == 1
    )
    approved_target_uris = {
        claim.identifying_uri()
        for claim in replacement_claims
        if claim.status == "approved" and claim.identifying_uri()
    }
    direct_in_registry_domain = bool(
        source_record
        and any(
            record.source_uri in source_record.all_uris
            and record.target_uri in approved_target_uris
            for record in mappings
        )
    )
    inactive_replacement = GovernedReplacementCoverage(active=replacement_active, covered=False)

    if direct and not domain_candidates:
        return MappingCoverage(
            state="direct",
            direct=True,
            direct_in_registry_domain=direct_in_registry_domain,
            replacement=inactive_replacement,
            reasons=global_errors,
        )
    if not direct and not candidates:
        return MappingCoverage(
            state="unmapped",
            direct=False,
            direct_in_registry_domain=False,
            replacement=inactive_replacement,
            reasons=global_errors,
        )
    if global_errors:
        return MappingCoverage(
            state="unmapped",
            direct=direct,
            direct_in_registry_domain=direct_in_registry_domain,
            replacement=inactive_replacement,
            reasons=global_errors,
        )

    if registry_error:
        return MappingCoverage(
            state="unmapped",
            direct=direct,
            direct_in_registry_domain=direct_in_registry_domain,
            replacement=inactive_replacement,
            reasons=(registry_error,),
        )
    if not domain_candidates:
        reason = (
            "requires exactly one approved source-table class claim matching "
            "a declared contract target"
        )
        return MappingCoverage(
            state="unmapped",
            direct=direct,
            direct_in_registry_domain=direct_in_registry_domain,
            replacement=inactive_replacement,
            reasons=(reason,),
        )
    if direct_in_registry_domain:
        return MappingCoverage(
            state="unmapped",
            direct=direct,
            direct_in_registry_domain=True,
            replacement=inactive_replacement,
            reasons=("source-authority conflict: direct and governed replacement mappings coexist",),
        )

    by_target: dict[str, list[object]] = {}
    for contract, _claims in domain_candidates:
        by_target.setdefault(contract.target_class, []).append(contract)
    if any(len(group) > 1 for group in by_target.values()):
        return MappingCoverage(
            state="unmapped",
            direct=direct,
            direct_in_registry_domain=False,
            replacement=inactive_replacement,
            reasons=("multiple contracts claim replacement authority for the same target",),
        )

    evidence: list[ReplacementCoverageEvidence] = []
    for contract, matching_claims in domain_candidates:
        exact_targets = {
            record.target_uri
            for record in mappings
            if record.source_uri == contract.virtual_source_iri
            and record.predicate_uri == str(SKOS.exactMatch)
        }
        if exact_targets != {contract.target_class}:
            reason = (
                "virtual table requires one table-level skos:exactMatch to "
                f"{contract.target_class}"
            )
            replacement = GovernedReplacementCoverage(
                active=replacement_active,
                covered=False,
                reasons=(reason,),
            )
            return MappingCoverage(
                state="unmapped",
                direct=direct,
                direct_in_registry_domain=False,
                replacement=replacement,
                reasons=(reason,),
            )
        target_refs = silver_refs.get(contract.target_class, set())
        if target_refs != {contract.name}:
            reason = f"target class must declare silverSourceRef {contract.name!r}"
            replacement = GovernedReplacementCoverage(
                active=replacement_active,
                covered=False,
                reasons=(reason,),
            )
            return MappingCoverage(
                state="unmapped",
                direct=direct,
                direct_in_registry_domain=False,
                replacement=replacement,
                reasons=(reason,),
            )
        source_iri = next(
            table_iri
            for table_iri in sorted(record_table_iris)
            if contract in contracts_by_source.get(table_iri, [])
        )
        evidence.append(
            ReplacementCoverageEvidence(
                source_table_iri=source_iri,
                claim_id=matching_claims[0].id,
                target_class=contract.target_class,
                contract_model=contract.name,
                virtual_table_iri=contract.virtual_source_iri,
                silver_source_ref=contract.name,
            )
        )

    replacement = GovernedReplacementCoverage(
        active=replacement_active,
        covered=True,
        evidence=tuple(evidence),
    )
    return MappingCoverage(
        state="governed_replacement",
        direct=direct,
        direct_in_registry_domain=False,
        replacement=replacement,
    )


def compute_completeness_facts(
    *,
    analysis_dir: Path,
    claims_dir: Path | None = None,
    sources_dir: Path | None = None,
    mappings_dir: Path | None = None,
    domains_filter: list[str] | None = None,
    extensions_dir: Path | None = None,
    hub_root: Path | None = None,
    transforms_dir: Path | None = None,
    excluded_affinity_systems: set[str] | None = None,
) -> CompletenessFacts:
    """Compute the one canonical completeness snapshot from committed inputs.

    Mapping coverage is evaluated only when both *sources_dir* and *mappings_dir*
    are provided.  This lets the claim view use the same model without pretending
    that absent mapping inputs are complete.
    """

    source_catalog = build_source_catalog(sources_dir) if sources_dir is not None else None
    effective_excluded = (
        set(excluded_affinity_systems)
        if excluded_affinity_systems is not None
        else source_catalog.excluded_affinity_systems() if source_catalog is not None else set()
    )
    assignments = tuple(
        assignment
        for assignment in load_affinity_assignments(
            analysis_dir,
            excluded_systems=effective_excluded,
        )
        if _in_scope(assignment.domain, domains_filter)
    )
    by_domain: dict[str, list[AffinityAssignment]] = {}
    for assignment in assignments:
        by_domain.setdefault(assignment.domain, []).append(assignment)

    domains: list[DomainCompleteness] = []
    coverage_by_domain: dict[str, dict[tuple[str, str], RegistryTableCoverage]] = {}
    for domain in sorted(by_domain):
        expected_pairs = [
            (assignment.system, assignment.table) for assignment in by_domain[domain]
        ]
        domain_fact, coverage = _domain_registry_fact(claims_dir, domain, expected_pairs)
        domains.append(domain_fact)
        coverage_by_domain[domain] = coverage
    domain_by_name = {fact.domain: fact for fact in domains}

    orphan_registries: list[DomainCompleteness] = []
    if claims_dir is not None and claims_dir.is_dir():
        for claims_file in sorted(claims_dir.glob("*-claims.yaml")):
            domain = claims_file.name.removesuffix("-claims.yaml")
            if domain in by_domain or not _in_scope(domain, domains_filter):
                continue
            orphan, _unused = _domain_registry_fact(
                claims_dir,
                domain,
                (),
                path=claims_file,
            )
            orphan_registries.append(orphan)

    source_records = (
        _source_table_records_from_catalog(source_catalog)
        if source_catalog is not None
        else {}
    )
    mapping_evaluated = sources_dir is not None and mappings_dir is not None
    tables: list[TableCompletenessFact] = []
    if not mapping_evaluated:
        not_evaluated = MappingCoverage(
            state="not_evaluated",
            direct=False,
            direct_in_registry_domain=False,
            replacement=GovernedReplacementCoverage(active=False, covered=False),
        )
        for assignment in assignments:
            source_record = source_records.get((assignment.system, assignment.table))
            domain = domain_by_name[assignment.domain]
            tables.append(
                TableCompletenessFact(
                    assignment=assignment,
                    registry_coverage=coverage_by_domain[assignment.domain].get(
                        (assignment.system, assignment.table)
                    ),
                    source_table_iris=tuple(sorted(source_record.table_uris))
                    if source_record
                    else (),
                    source_uris=tuple(sorted(source_record.all_uris)) if source_record else (),
                    mapping=not_evaluated,
                    freshness=domain.freshness,
                )
            )
        return CompletenessFacts(
            tables=tuple(tables),
            domains=tuple(domains),
            orphan_registries=tuple(orphan_registries),
            mapping_evaluated=False,
        )

    mappings = tuple(collect_mapping_records(mappings_dir))
    mapped_subjects = {record.source_uri for record in mappings}
    applicable_source_iris = {
        table_iri
        for assignment in assignments
        for table_iri in source_records.get(
            (assignment.system, assignment.table),
            SourceTableRecord(),
        ).table_uris
    }
    contracts_by_source, contract_errors, replacement_active = _load_replacement_contracts(
        hub_root=hub_root,
        transforms_dir=transforms_dir,
        sources_dir=sources_dir,
        applicable_source_iris=applicable_source_iris,
    )
    silver_refs, extension_errors = (
        _load_silver_source_refs(extensions_dir) if replacement_active else ({}, [])
    )
    catalog_errors = tuple(
        f"source catalog preflight failed: {error}"
        for error in (source_catalog.conflicts if source_catalog is not None else [])
    )
    global_errors = (*catalog_errors, *contract_errors, *extension_errors)

    for assignment in assignments:
        source_record = source_records.get((assignment.system, assignment.table))
        domain = domain_by_name[assignment.domain]
        mapping = _mapping_coverage(
            assignment,
            source_record=source_record,
            mappings=mappings,
            mapped_subjects=mapped_subjects,
            contracts_by_source=contracts_by_source,
            replacement_active=replacement_active,
            global_errors=global_errors,
            silver_refs=silver_refs,
            domain_registry=domain,
        )
        tables.append(
            TableCompletenessFact(
                assignment=assignment,
                registry_coverage=coverage_by_domain[assignment.domain].get(
                    (assignment.system, assignment.table)
                ),
                source_table_iris=tuple(sorted(source_record.table_uris))
                if source_record
                else (),
                source_uris=tuple(sorted(source_record.all_uris)) if source_record else (),
                mapping=mapping,
                freshness=domain.freshness,
            )
        )

    return CompletenessFacts(
        tables=tuple(sorted(tables, key=lambda fact: (fact.domain, fact.system, fact.table))),
        domains=tuple(domains),
        orphan_registries=tuple(orphan_registries),
        mapping_evaluated=True,
    )
