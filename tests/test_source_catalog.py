# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for canonical Bronze source vocabulary discovery."""

from pathlib import Path

import pytest
from rdflib import RDF, Graph, Literal, URIRef

from kairos_ontology.core.source_catalog import (
    KAIROS_BRONZE,
    KAIROS_DBT,
    SourceCatalogError,
    build_source_catalog,
)


def _write_table(
    path: Path,
    *,
    table_iri: str,
    table_name: str,
    generated: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    graph = Graph()
    table = URIRef(table_iri)
    graph.add((table, RDF.type, KAIROS_BRONZE.SourceTable))
    graph.add((table, KAIROS_BRONZE.tableName, Literal(table_name)))
    if generated:
        graph.add((table, KAIROS_DBT.sourceKind, Literal("dbt-contract")))
    graph.serialize(path, format="turtle")


def test_generated_stem_collision_never_excludes_ordinary_system(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    _write_table(
        sources / "orders" / "orders.vocabulary.ttl",
        table_iri="https://example.com/source/orders#raw",
        table_name="raw_orders",
    )
    _write_table(
        sources / "custom-transformations" / "orders.vocabulary.ttl",
        table_iri="https://example.com/source/custom#orders",
        table_name="orders",
        generated=True,
    )

    catalog = build_source_catalog(sources)

    assert catalog.generated_report_stems() == set()


def test_distinct_iris_with_same_system_table_name_are_conflicting(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    _write_table(
        sources / "erp" / "one.vocabulary.ttl",
        table_iri="https://example.com/source/erp#orders-v1",
        table_name="orders",
    )
    _write_table(
        sources / "erp" / "two.vocabulary.ttl",
        table_iri="https://example.com/source/erp#orders-v2",
        table_name="orders",
    )

    catalog = build_source_catalog(sources)

    with pytest.raises(SourceCatalogError, match="defines table name"):
        catalog.require_consistent()


def test_malformed_managed_generated_file_still_excludes_legacy_report(
    tmp_path: Path,
) -> None:
    generated = (
        tmp_path
        / "sources"
        / "custom-transformations"
        / "int_orders.vocabulary.ttl"
    )
    generated.parent.mkdir(parents=True)
    generated.write_text("not valid turtle [", encoding="utf-8")

    catalog = build_source_catalog(tmp_path / "sources")

    assert catalog.generated_report_stems() == {"int_orders"}
    assert catalog.conflicts == []


def test_split_file_stem_is_superseded_by_directory_system(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    _write_table(
        sources / "qargo" / "qargo.vocabulary.ttl",
        table_iri="https://example.com/source/qargo#booking",
        table_name="booking",
    )
    _write_table(
        sources / "qargo" / "tables" / "shipment.vocabulary.ttl",
        table_iri="https://example.com/source/qargo#shipment",
        table_name="shipment",
    )

    catalog = build_source_catalog(sources)

    assert catalog.superseded_report_stems() == {"shipment"}
    assert catalog.excluded_affinity_systems() == {"shipment"}
