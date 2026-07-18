# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Synchronize custom dbt contracts to projection-compatible Bronze RDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal as TypingLiteral
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, RDFS, XSD

from ._provenance import prepend_provenance
from .dbt_contracts import DbtContractModel, discover_dbt_contracts
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


def _column_iri(table_iri: str, column_name: str) -> URIRef:
    return URIRef(f"{table_iri}/{quote(column_name, safe='')}")


def build_dbt_contract_graph(contract: DbtContractModel) -> Graph:
    """Build the established Kairos Bronze graph for one custom dbt contract."""

    graph = Graph()
    graph.bind("kairos-bronze", KAIROS_BRONZE)
    graph.bind("kairos-dbt", KAIROS_DBT)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)

    table = URIRef(contract.virtual_source_iri)
    system = URIRef(f"{contract.virtual_source_iri}/source-system")

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
    graph.add((table, KAIROS_BRONZE.primaryKeyColumns, Literal(" ".join(contract.natural_key))))
    graph.add((table, KAIROS_DBT.sourceKind, Literal("dbt-contract")))
    graph.add((table, KAIROS_DBT.modelRef, Literal(contract.name)))
    graph.add((table, KAIROS_DBT.targetClass, URIRef(contract.target_class)))
    for replacement in contract.replaces_sources:
        graph.add((table, KAIROS_DBT.replacesSource, URIRef(replacement.table_iri)))

    natural_key = set(contract.natural_key)
    for column in contract.columns:
        column_iri = _column_iri(contract.virtual_source_iri, column.name)
        is_key = column.name in natural_key
        graph.add((column_iri, RDF.type, KAIROS_BRONZE.SourceColumn))
        graph.add((column_iri, RDFS.label, Literal(column.description or column.name)))
        graph.add((column_iri, KAIROS_BRONZE.sourceTable, table))
        graph.add((column_iri, KAIROS_BRONZE.columnName, Literal(column.name)))
        graph.add((column_iri, KAIROS_BRONZE.dataType, Literal(column.data_type)))
        graph.add((column_iri, KAIROS_BRONZE.nullable, Literal(not is_key, datatype=XSD.boolean)))
        graph.add((column_iri, KAIROS_BRONZE.isPrimaryKey, Literal(is_key, datatype=XSD.boolean)))
        graph.add((column_iri, KAIROS_DBT.modelRef, Literal(contract.name)))
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
    if not transforms.is_relative_to(root):
        raise DbtContractSyncError(f"Transforms directory must be inside hub root {root}")
    if not sources.is_relative_to(root):
        raise DbtContractSyncError(f"Sources directory must be inside hub root {root}")
    if not bronze_sources.is_relative_to(root):
        raise DbtContractSyncError(f"Bronze sources directory must be inside hub root {root}")
    if not transforms.is_dir():
        return DbtContractSyncReport(transforms, sources, check)

    contracts = discover_dbt_contracts(transforms, root)
    _validate_source_replacements(contracts, bronze_sources, sources)
    items: list[DbtContractSyncItem] = []
    for contract in contracts:
        output_path = sources / f"{contract.name}.vocabulary.ttl"
        expected = build_dbt_contract_graph(contract)
        current = _load_graph(output_path)
        if current is not None and isomorphic(current, expected):
            items.append(DbtContractSyncItem(contract.name, output_path, "unchanged", "none"))
            continue

        state: SyncState = "missing" if not output_path.exists() else "stale"
        if check:
            action: SyncAction = "would_create" if state == "missing" else "would_update"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(_serialize_graph(expected, contract.name), encoding="utf-8")
            action = "created" if state == "missing" else "updated"
        items.append(DbtContractSyncItem(contract.name, output_path, state, action))

    return DbtContractSyncReport(transforms, sources, check, tuple(items))
