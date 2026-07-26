# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Synchronize custom dbt contracts to projection-compatible Bronze RDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping
from typing import Literal as TypingLiteral
from urllib.parse import quote

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, RDFS, XSD

from ._provenance import prepend_provenance, read_provenance_version, running_toolkit_version
from .dbt_contracts import DbtContractModel, discover_dbt_contracts
from .dbt_contract_identity import (
    ContractIdentityEvidence,
    contract_content_hash,
    identity_requirements,
    load_evidence,
)
from .source_catalog import SourceCatalogError, build_source_catalog

KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
KAIROS_DBT = Namespace("https://kairos.cnext.eu/dbt-contract#")

SyncState = TypingLiteral["missing", "stale", "unchanged"]
SyncAction = TypingLiteral["created", "updated", "would_create", "would_update", "none"]


class DbtContractSyncError(ValueError):
    """Raised when synchronization paths are unsafe or invalid."""


@dataclass(frozen=True)
class DbtContractSyncItem:
    """Synchronization result for one contracted dbt model."""

    model: str
    output_path: Path
    state: SyncState
    action: SyncAction
    prior_generator_version: str | None = None

    @property
    def has_drift(self) -> bool:
        """Return whether the output was missing or semantically stale."""

        return self.state != "unchanged"

    @property
    def written(self) -> bool:
        """Return whether synchronization wrote this output."""

        return self.action in {"created", "updated"}


@dataclass(frozen=True)
class DbtContractSyncReport:
    """Structured result for a complete dbt-contract synchronization."""

    transforms_dir: Path
    sources_dir: Path
    check: bool
    items: tuple[DbtContractSyncItem, ...] = ()
    running_toolkit_version: str = ""

    @property
    def has_drift(self) -> bool:
        """Return whether any generated vocabulary is missing or stale."""

        return any(item.has_drift for item in self.items)

    @property
    def written_count(self) -> int:
        """Return the number of files created or updated."""

        return sum(item.written for item in self.items)

    @property
    def unchanged_count(self) -> int:
        """Return the number of already-current files."""

        return sum(item.state == "unchanged" for item in self.items)


def legacy_column_iri(table_iri: str, column_name: str) -> URIRef:
    """Return the deprecated slash-delimited column IRI."""

    return URIRef(f"{table_iri}/{quote(column_name, safe='')}")


def column_iri(table_iri: str, column_name: str) -> URIRef:
    """Mint a Turtle PN_LOCAL-safe column IRI using the stable ``__`` separator."""

    encoded = "".join(
        chr(byte)
        if byte == 95 or 48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122
        else f"%{byte:02X}"
        for byte in column_name.encode("utf-8")
    )
    return URIRef(f"{table_iri}__{encoded}")


def build_dbt_contract_graph(
    contract: DbtContractModel,
    *,
    existing_column_iris: Mapping[str, URIRef] | None = None,
    evidence: ContractIdentityEvidence | None = None,
) -> Graph:
    """Build the established Kairos Bronze graph for one custom dbt contract."""

    graph = Graph()
    graph.bind("kairos-bronze", KAIROS_BRONZE)
    graph.bind("kairos-dbt", KAIROS_DBT)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)

    table = URIRef(contract.virtual_source_iri)
    system = URIRef(f"{contract.virtual_source_iri}/source-system")
    identity = URIRef(f"{contract.virtual_source_iri}/contract-identity")
    content_hash = contract_content_hash(contract)

    graph.add((system, RDF.type, KAIROS_BRONZE.SourceSystem))
    graph.add((system, RDFS.label, Literal(f"dbt contract: {contract.name}")))
    graph.add((system, KAIROS_BRONZE.connectionType, Literal("dbt")))
    graph.add((system, KAIROS_BRONZE.database, Literal("custom-transformations")))
    graph.add((system, KAIROS_BRONZE.schema, Literal("dbt")))
    graph.add((system, KAIROS_DBT.sourceKind, Literal("dbt-contract")))
    graph.add((system, KAIROS_DBT.modelRef, Literal(contract.name)))

    graph.add((table, RDF.type, KAIROS_BRONZE.SourceTable))
    graph.add((table, RDFS.label, Literal(contract.description)))
    graph.add((table, KAIROS_BRONZE.sourceSystem, system))
    graph.add((table, KAIROS_BRONZE.tableName, Literal(contract.name)))
    graph.add((table, KAIROS_BRONZE.primaryKeyColumns, Literal(" ".join(contract.grain_key))))
    graph.add((table, KAIROS_DBT.sourceKind, Literal("dbt-contract")))
    graph.add((table, KAIROS_DBT.modelRef, Literal(contract.name)))
    graph.add((table, KAIROS_DBT.targetClass, URIRef(contract.target_class)))
    for replacement in contract.replaces_sources:
        graph.add((table, KAIROS_DBT.replacesSource, URIRef(replacement.table_iri)))

    graph.add((identity, RDF.type, KAIROS_DBT.ContractIdentity))
    graph.add((identity, RDFS.label, Literal(f"Contract identity: {contract.name}")))
    graph.add((identity, KAIROS_DBT.modelRef, Literal(contract.name)))
    graph.add((identity, KAIROS_DBT.virtualTable, table))
    graph.add((identity, KAIROS_DBT.identityScope, Literal("contract-output")))
    graph.add((identity, KAIROS_DBT.contractContentHash, Literal(content_hash)))
    grain_list = BNode()
    Collection(
        graph,
        grain_list,
        [
            (existing_column_iris or {}).get(
                name, column_iri(contract.virtual_source_iri, name)
            )
            for name in contract.grain_key
        ],
    )
    graph.add((identity, KAIROS_DBT.orderedGrainColumns, grain_list))
    for requirement in identity_requirements(contract):
        graph.add((identity, KAIROS_DBT.requiredTest, Literal(requirement)))
    for replacement in contract.replaces_sources:
        graph.add((identity, KAIROS_DBT.replacesSource, URIRef(replacement.table_iri)))
    for role, column in contract.canonical_cdc_bindings:
        binding = BNode()
        graph.add((identity, KAIROS_DBT.canonicalCdcBinding, binding))
        graph.add((binding, RDF.type, KAIROS_DBT.CdcBinding))
        graph.add((binding, KAIROS_DBT.cdcRole, Literal(role)))
        graph.add(
            (
                binding,
                KAIROS_DBT.outputColumn,
                (existing_column_iris or {}).get(
                    column, column_iri(contract.virtual_source_iri, column)
                ),
            )
        )
    for decision in contract.decisions:
        graph.add((identity, KAIROS_DBT.decisionStatus, Literal(decision.status)))
        for item in decision.evidence:
            graph.add((identity, KAIROS_DBT.decisionEvidence, Literal(item.artifact)))
    verified = (
        evidence is not None
        and evidence.contract_content_hash == content_hash
        and set(identity_requirements(contract)).issubset(evidence.passed_requirements)
    )
    graph.add(
        (
            identity,
            KAIROS_DBT.verificationStatus,
            Literal("verified" if verified else "unverified"),
        )
    )
    if verified:
        graph.add((identity, KAIROS_DBT.evidenceInvocation, Literal(evidence.invocation_id)))
        graph.add((identity, KAIROS_DBT.evidenceContentHash, Literal(content_hash)))

    grain_key = set(contract.grain_key)
    for column in contract.columns:
        column_resource = (existing_column_iris or {}).get(
            column.name,
            column_iri(contract.virtual_source_iri, column.name),
        )
        is_key = column.name in grain_key
        nullable = not (is_key or column.not_null)
        graph.add((column_resource, RDF.type, KAIROS_BRONZE.SourceColumn))
        graph.add((column_resource, RDFS.label, Literal(column.description or column.name)))
        graph.add((column_resource, KAIROS_BRONZE.sourceTable, table))
        graph.add((column_resource, KAIROS_BRONZE.columnName, Literal(column.name)))
        graph.add((column_resource, KAIROS_BRONZE.dataType, Literal(column.data_type)))
        graph.add(
            (column_resource, KAIROS_BRONZE.nullable, Literal(nullable, datatype=XSD.boolean))
        )
        graph.add(
            (column_resource, KAIROS_BRONZE.isPrimaryKey, Literal(is_key, datatype=XSD.boolean))
        )
        graph.add((column_resource, KAIROS_DBT.modelRef, Literal(contract.name)))
    return graph


def _load_bronze_table_index(
    bronze_sources_dir: Path,
    generated_sources_dir: Path,
) -> dict[str, Path]:
    """Index canonical non-generated Bronze table IRIs."""

    if not bronze_sources_dir.is_dir():
        raise DbtContractSyncError(f"Bronze sources directory does not exist: {bronze_sources_dir}")

    try:
        catalog = build_source_catalog(
            bronze_sources_dir,
            generated_sources_dirs=(generated_sources_dir,),
        )
        catalog.require_consistent()
    except SourceCatalogError as exc:
        raise DbtContractSyncError(str(exc)) from exc
    generated_root = generated_sources_dir.resolve()
    return {
        table.table_iri: table.paths[0]
        for table in catalog.tables.values()
        if not table.generated
        and not any(path.is_relative_to(generated_root) for path in table.paths)
    }


def _validate_source_replacements(
    contracts: tuple[DbtContractModel, ...],
    bronze_sources_dir: Path,
    generated_sources_dir: Path,
) -> None:
    """Require every asserted replacement to reference a canonical Bronze table."""

    if not any(contract.replaces_sources for contract in contracts):
        return
    table_index = _load_bronze_table_index(bronze_sources_dir, generated_sources_dir)
    for contract in contracts:
        for replacement in contract.replaces_sources:
            if replacement.table_iri not in table_index:
                raise DbtContractSyncError(
                    f"Contract {contract.name!r} replaces unknown or generated Bronze "
                    f"SourceTable IRI {replacement.table_iri!r}"
                )


def _load_graph(path: Path) -> Graph | None:
    if not path.is_file():
        return None
    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception:
        return None
    return graph


def _serialize_graph(graph: Graph, model: str) -> str:
    body = graph.serialize(format="turtle")
    return prepend_provenance(
        body,
        "sync-dbt-contracts",
        extra={"Policy": "DD-072", "dbt model": model},
    )


def _managed_column_iris(graph: Graph | None, table: URIRef) -> dict[str, URIRef]:
    """Recover existing managed column identities so ordinary sync never remints them."""

    if graph is None:
        return {}
    result: dict[str, URIRef] = {}
    for resource in graph.subjects(RDF.type, KAIROS_BRONZE.SourceColumn):
        if not isinstance(resource, URIRef):
            continue
        if graph.value(resource, KAIROS_BRONZE.sourceTable) != table:
            continue
        name = graph.value(resource, KAIROS_BRONZE.columnName)
        if isinstance(name, Literal):
            result[str(name)] = resource
    return result


def sync_dbt_contracts(
    hub_root: Path,
    *,
    transforms_dir: Path | None = None,
    sources_dir: Path | None = None,
    bronze_sources_dir: Path | None = None,
    check: bool = False,
) -> DbtContractSyncReport:
    """Synchronize custom dbt contracts into generated Bronze vocabularies.

    Missing transform directories are a successful no-op for backward compatibility.
    In check mode no directories or files are written.
    """

    root = Path(hub_root).resolve()
    transforms = Path(transforms_dir or root / "integration" / "transforms" / "dbt").resolve()
    sources = Path(
        sources_dir or root / "integration" / "sources" / "custom-transformations"
    ).resolve()
    bronze_sources = Path(bronze_sources_dir or root / "integration" / "sources").resolve()
    toolkit_version = running_toolkit_version()
    if not transforms.is_relative_to(root):
        raise DbtContractSyncError(f"Transforms directory must be inside hub root {root}")
    if not sources.is_relative_to(root):
        raise DbtContractSyncError(f"Sources directory must be inside hub root {root}")
    if not bronze_sources.is_relative_to(root):
        raise DbtContractSyncError(f"Bronze sources directory must be inside hub root {root}")
    if not transforms.is_dir():
        return DbtContractSyncReport(transforms, sources, check, running_toolkit_version=toolkit_version)

    contracts = discover_dbt_contracts(transforms, root)
    evidence_by_model = {item.model: item for item in load_evidence(root)}
    _validate_source_replacements(contracts, bronze_sources, sources)
    items: list[DbtContractSyncItem] = []
    for contract in contracts:
        output_path = sources / f"{contract.name}.vocabulary.ttl"
        # Read the prior artifact's own provenance stamp (if any) *before* it is
        # potentially overwritten below, so drift reporting can show what actually
        # generated the existing file without inventing provenance it never had.
        prior_generator_version = (
            read_provenance_version(output_path.read_text(encoding="utf-8"))
            if output_path.is_file()
            else None
        )
        current = _load_graph(output_path)
        expected = build_dbt_contract_graph(
            contract,
            existing_column_iris=_managed_column_iris(
                current,
                URIRef(contract.virtual_source_iri),
            ),
            evidence=evidence_by_model.get(contract.name),
        )
        if current is not None and isomorphic(current, expected):
            items.append(
                DbtContractSyncItem(
                    contract.name, output_path, "unchanged", "none",
                    prior_generator_version=prior_generator_version,
                )
            )
            continue

        state: SyncState = "missing" if not output_path.exists() else "stale"
        if check:
            action: SyncAction = "would_create" if state == "missing" else "would_update"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(_serialize_graph(expected, contract.name), encoding="utf-8")
            action = "created" if state == "missing" else "updated"
        items.append(
            DbtContractSyncItem(
                contract.name, output_path, state, action,
                prior_generator_version=prior_generator_version,
            )
        )

    return DbtContractSyncReport(
        transforms, sources, check, tuple(items), running_toolkit_version=toolkit_version
    )
