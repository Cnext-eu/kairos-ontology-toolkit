# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic source-coverage gate (DD-061).

Direct coverage comes from source-to-domain SKOS mappings. Governed replacement
coverage additionally requires an approved source claim, a current contracted dbt
virtual source, an exact table mapping, and matching Silver routing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rdflib import RDF, Graph, Namespace, URIRef
from rdflib.namespace import SKOS

from .alignment_coverage import load_affinity_domain_tables

logger = logging.getLogger(__name__)

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
KAIROS_DBT = Namespace("https://kairos.cnext.eu/dbt-contract#")
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

_MATCH_PREDICATES = (
    SKOS.exactMatch,
    SKOS.closeMatch,
    SKOS.narrowMatch,
    SKOS.broadMatch,
    SKOS.relatedMatch,
)


@dataclass(frozen=True)
class MappingRecord:
    """One source-to-domain SKOS statement."""

    source_uri: str
    predicate_uri: str
    target_uri: str
    path: Path


@dataclass
class SourceTableRecord:
    """Canonical table URI(s) and all mapping-eligible URIs for an affinity key."""

    table_uris: set[str] = field(default_factory=set)
    all_uris: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ReplacementCoverageEvidence:
    """Proof surfaces used to grant governed replacement coverage."""

    source_table_iri: str
    claim_id: str
    target_class: str
    contract_model: str
    virtual_table_iri: str
    silver_source_ref: str


def collect_mapping_records(mappings_dir: Path) -> list[MappingRecord]:
    """Return structured SKOS mapping records from every parseable mapping file."""

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
                if not isinstance(subject, URIRef) or not isinstance(target, URIRef):
                    continue
                records.append(MappingRecord(str(subject), str(predicate), str(target), ttl))
    return records


def collect_mapped_subjects(mappings_dir: Path) -> set[str]:
    """Return subject URIs participating in any supported SKOS mapping."""

    return {record.source_uri for record in collect_mapping_records(mappings_dir)}


def _system_key(sources_dir: Path, vocab_file: Path) -> str:
    relative = vocab_file.relative_to(sources_dir)
    if len(relative.parts) > 1:
        return relative.parts[0]
    return vocab_file.stem.replace(".vocabulary", "")


def collect_source_table_records(
    sources_dir: Path,
) -> dict[tuple[str, str], SourceTableRecord]:
    """Index Bronze tables by affinity key while retaining canonical table IRIs."""

    result: dict[tuple[str, str], SourceTableRecord] = {}
    if not sources_dir or not sources_dir.is_dir():
        return result

    for vocab_file in sorted(sources_dir.rglob("*.vocabulary.ttl")):
        system = _system_key(sources_dir, vocab_file)
        graph = Graph()
        try:
            graph.parse(vocab_file, format="turtle")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not parse vocabulary %s: %s", vocab_file.name, exc)
            continue

        for table_uri in graph.subjects(RDF.type, KAIROS_BRONZE.SourceTable):
            table_name = str(
                graph.value(table_uri, KAIROS_BRONZE.tableName)
                or str(table_uri).split("#")[-1].split("/")[-1]
            )
            record = result.setdefault((system, table_name), SourceTableRecord())
            record.table_uris.add(str(table_uri))
            record.all_uris.add(str(table_uri))
            columns = set(graph.subjects(KAIROS_BRONZE.belongsToTable, table_uri))
            columns.update(graph.subjects(KAIROS_BRONZE.sourceTable, table_uri))
            record.all_uris.update(str(column) for column in columns)
    return result


def collect_source_tables(sources_dir: Path) -> dict[tuple[str, str], set[str]]:
    """Backward-compatible source table index including table and column URIs."""

    return {
        key: set(record.all_uris)
        for key, record in collect_source_table_records(sources_dir).items()
    }


@dataclass
class SourceCoverageReport:
    """Result of deterministic direct and governed-replacement coverage checks."""

    uncovered: dict[str, list[str]] = field(default_factory=dict)
    domain_counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    unresolved_domains: list[str] = field(default_factory=list)
    direct_counts: dict[str, int] = field(default_factory=dict)
    replacement_counts: dict[str, int] = field(default_factory=dict)
    diagnostics: dict[str, list[str]] = field(default_factory=dict)
    replacement_evidence: dict[str, list[ReplacementCoverageEvidence]] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        """Return whether any source is uncovered or a replacement invariant failed."""

        return any(self.uncovered.values()) or any(self.diagnostics.values())

    @property
    def total_uncovered(self) -> int:
        return sum(len(values) for values in self.uncovered.values())

    def coverage_pct(self, domain: str) -> float:
        covered, total = self.domain_counts.get(domain, (0, 0))
        return 100.0 * covered / total if total else 100.0


def _declared_replacement_iris(transforms_dir: Path) -> set[str]:
    declared: set[str] = set()
    if not transforms_dir.is_dir():
        return declared
    for path in sorted([*transforms_dir.rglob("*.yml"), *transforms_dir.rglob("*.yaml")]):
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
    """Load live replacement contracts only when replacement metadata is present."""

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


def _load_registry_claims(
    claims_dir: Path | None,
    domain: str,
) -> tuple[list[object], str | None]:
    if claims_dir is None:
        return [], None
    from .claim_registry import load_registry, registry_path

    path = registry_path(claims_dir, domain)
    if not path.is_file():
        return [], None
    registry = load_registry(path)
    if registry.domain != domain:
        return [], (
            f"claim registry {path} declares domain {registry.domain!r}, expected {domain!r}"
        )
    return list(registry.claims), None


def _matching_source_claims(
    claims: list[object],
    system: str,
    table: str,
    target_class: str,
) -> list[object]:
    matches: list[object] = []
    for claim in claims:
        if (
            claim.status != "approved"
            or claim.type not in {"class", "reference_data"}
            or claim.class_uri != target_class
        ):
            continue
        if any(
            evidence.type == "source_table"
            and evidence.system == system
            and evidence.table == table
            for evidence in claim.evidence_sources
        ):
            matches.append(claim)
    return matches


def _load_silver_source_refs(extensions_dir: Path | None) -> tuple[dict[str, set[str]], list[str]]:
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


def _replacement_failure(
    report: SourceCoverageReport,
    domain: str,
    system: str,
    table: str,
    message: str,
) -> None:
    report.diagnostics.setdefault(domain, []).append(f"{system}.{table}: {message}")


def check_source_coverage(
    *,
    analysis_dir: Path,
    sources_dir: Path,
    mappings_dir: Path,
    domains_filter: list[str] | None = None,
    claims_dir: Path | None = None,
    extensions_dir: Path | None = None,
    hub_root: Path | None = None,
    transforms_dir: Path | None = None,
) -> SourceCoverageReport:
    """Verify direct mappings or the complete governed replacement invariant."""

    report = SourceCoverageReport()
    domain_tables = load_affinity_domain_tables(analysis_dir)
    mappings = collect_mapping_records(mappings_dir)
    mapped_subjects = {record.source_uri for record in mappings}
    exact_targets: dict[str, set[str]] = {}
    for mapping in mappings:
        if mapping.predicate_uri == str(SKOS.exactMatch):
            exact_targets.setdefault(mapping.source_uri, set()).add(mapping.target_uri)
    source_tables = collect_source_table_records(sources_dir)

    lower_filter = [domain.lower() for domain in domains_filter] if domains_filter else None

    def in_scope(domain: str) -> bool:
        if lower_filter is None:
            return True
        return any(fragment in domain.lower() for fragment in lower_filter)

    applicable_source_iris = {
        table_iri
        for domain, expected in domain_tables.items()
        if in_scope(domain)
        for key in expected
        for table_iri in source_tables.get(key, SourceTableRecord()).table_uris
    }
    replacement_contracts, contract_errors, replacement_active = _load_replacement_contracts(
        hub_root=hub_root,
        transforms_dir=transforms_dir,
        sources_dir=sources_dir,
        applicable_source_iris=applicable_source_iris,
    )
    silver_refs, extension_errors = (
        _load_silver_source_refs(extensions_dir) if replacement_active else ({}, [])
    )
    global_errors = [*contract_errors, *extension_errors]

    for domain in sorted(domain_tables):
        if not in_scope(domain):
            continue
        expected = domain_tables[domain]
        claims, registry_error = _load_registry_claims(claims_dir, domain)
        if global_errors:
            report.diagnostics.setdefault(domain, []).extend(global_errors)
        approved_target_uris = {
            claim.identifying_uri()
            for claim in claims
            if claim.status == "approved" and claim.identifying_uri()
        }
        uncovered: list[str] = []
        direct_count = 0
        replacement_count = 0
        for system, table in sorted(expected):
            record = source_tables.get((system, table))
            direct = bool(record and record.all_uris & mapped_subjects)
            candidates = {
                contract
                for table_iri in (record.table_uris if record else ())
                for contract in replacement_contracts.get(table_iri, [])
            }
            candidate_claims = {
                contract: _matching_source_claims(claims, system, table, contract.target_class)
                for contract in candidates
            }
            domain_candidates = {
                contract: matching
                for contract, matching in candidate_claims.items()
                if len(matching) == 1
            }
            direct_in_domain = bool(
                record
                and any(
                    mapping.source_uri in record.all_uris
                    and mapping.target_uri in approved_target_uris
                    for mapping in mappings
                )
            )

            if direct and not domain_candidates:
                direct_count += 1
                continue
            if not direct and not candidates:
                uncovered.append(f"{system}.{table}")
                continue
            if global_errors:
                uncovered.append(f"{system}.{table}")
                continue
            if registry_error:
                uncovered.append(f"{system}.{table}")
                _replacement_failure(report, domain, system, table, registry_error)
                continue
            if not domain_candidates:
                uncovered.append(f"{system}.{table}")
                _replacement_failure(
                    report,
                    domain,
                    system,
                    table,
                    "requires exactly one approved source-table class claim matching "
                    "a declared contract target",
                )
                continue
            if direct_in_domain:
                uncovered.append(f"{system}.{table}")
                _replacement_failure(
                    report,
                    domain,
                    system,
                    table,
                    "source-authority conflict: direct and governed replacement mappings coexist",
                )
                continue

            contracts_by_target: dict[str, list[object]] = {}
            for contract in domain_candidates:
                contracts_by_target.setdefault(contract.target_class, []).append(contract)
            if any(len(group) > 1 for group in contracts_by_target.values()):
                uncovered.append(f"{system}.{table}")
                _replacement_failure(
                    report,
                    domain,
                    system,
                    table,
                    "multiple contracts claim replacement authority for the same target",
                )
                continue

            evidence: list[ReplacementCoverageEvidence] = []
            failure: str | None = None
            for contract, source_claims in domain_candidates.items():
                mapped_targets = exact_targets.get(contract.virtual_source_iri, set())
                if mapped_targets != {contract.target_class}:
                    failure = (
                        "virtual table requires one table-level skos:exactMatch to "
                        f"{contract.target_class}"
                    )
                    break
                target_refs = silver_refs.get(contract.target_class, set())
                if target_refs != {contract.name}:
                    failure = f"target class must declare silverSourceRef {contract.name!r}"
                    break
                source_iri = next(
                    table_iri
                    for table_iri in sorted(record.table_uris)
                    if contract in replacement_contracts.get(table_iri, [])
                )
                evidence.append(
                    ReplacementCoverageEvidence(
                        source_table_iri=source_iri,
                        claim_id=source_claims[0].id,
                        target_class=contract.target_class,
                        contract_model=contract.name,
                        virtual_table_iri=contract.virtual_source_iri,
                        silver_source_ref=contract.name,
                    )
                )
            if failure:
                uncovered.append(f"{system}.{table}")
                _replacement_failure(report, domain, system, table, failure)
                continue

            replacement_count += 1
            report.replacement_evidence.setdefault(domain, []).extend(evidence)

        covered = direct_count + replacement_count
        report.domain_counts[domain] = (covered, len(expected))
        report.direct_counts[domain] = direct_count
        report.replacement_counts[domain] = replacement_count
        if uncovered:
            report.uncovered[domain] = uncovered
        if covered == 0 and not any(key in source_tables for key in expected):
            report.unresolved_domains.append(domain)

    return report
