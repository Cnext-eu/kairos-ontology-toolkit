# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Governed contracted-source replacement coverage tests for issue #215."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml
from rdflib import RDF, Graph, Literal, URIRef
from rdflib.namespace import SKOS

from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    EvidenceSource,
    write_registry,
)
from kairos_ontology.core.dbt_contract_sync import KAIROS_BRONZE, sync_dbt_contracts
from kairos_ontology.core.source_coverage import KAIROS_EXT, check_source_coverage

SOURCE_TABLE = "https://example.com/source/adminpulse#tblRawParty"
VIRTUAL_TABLE = "https://example.com/source/custom#partyConformed"
TARGET_CLASS = "https://example.com/ont/party#Party"


def _write_graph(path: Path, graph: Graph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(path, format="turtle")


def _hub(tmp_path: Path) -> dict[str, Path]:
    hub = tmp_path / "hub"
    sources = hub / "integration" / "sources"
    analysis = sources / "_analysis"
    mappings = hub / "model" / "mappings"
    claims = hub / "model" / "claims"
    extensions = hub / "model" / "extensions"
    transforms = hub / "integration" / "transforms" / "dbt"
    model_dir = transforms / "models" / "intermediate"
    for path in (analysis, mappings, claims, extensions, model_dir):
        path.mkdir(parents=True, exist_ok=True)

    affinity = {
        "schema_version": 2,
        "system": "adminpulse",
        "tables": [{"table": "tblRawParty", "domain": "party"}],
    }
    (analysis / "adminpulse-affinity.yaml").write_text(
        yaml.safe_dump(affinity, sort_keys=False), encoding="utf-8"
    )

    source_graph = Graph()
    source_table = URIRef(SOURCE_TABLE)
    source_column = URIRef(f"{SOURCE_TABLE}/party_id")
    source_graph.add((source_table, RDF.type, KAIROS_BRONZE.SourceTable))
    source_graph.add((source_table, KAIROS_BRONZE.tableName, Literal("tblRawParty")))
    source_graph.add((source_column, RDF.type, KAIROS_BRONZE.SourceColumn))
    source_graph.add((source_column, KAIROS_BRONZE.sourceTable, source_table))
    source_graph.add((source_column, KAIROS_BRONZE.columnName, Literal("party_id")))
    _write_graph(sources / "adminpulse" / "adminpulse.vocabulary.ttl", source_graph)

    model = {
        "name": "int_party_conformed",
        "description": "One governed row per party.",
        "config": {"materialized": "table", "contract": {"enforced": True}},
        "meta": {
            "kairos": {
                "target_class": TARGET_CLASS,
                "virtual_source_iri": VIRTUAL_TABLE,
                "grain": "one row per party",
                "supported_adapters": ["fabric", "databricks"],
                "natural_key": ["party_id"],
                "required_packages": [],
                "required_macros": [],
                "replaces_sources": [{"table_iri": SOURCE_TABLE}],
            }
        },
        "columns": [{"name": "party_id", "data_type": "string"}],
    }
    properties = model_dir / "int_party_conformed.yml"
    properties.write_text(
        yaml.safe_dump({"version": 2, "models": [model]}, sort_keys=False),
        encoding="utf-8",
    )
    (model_dir / "int_party_conformed.sql").write_text(
        "select party_id from source_rows\n", encoding="utf-8"
    )

    mapping_graph = Graph()
    mapping_graph.add((URIRef(VIRTUAL_TABLE), SKOS.exactMatch, URIRef(TARGET_CLASS)))
    _write_graph(mappings / "custom-transformations" / "party.ttl", mapping_graph)

    extension_graph = Graph()
    extension_graph.add(
        (
            URIRef(TARGET_CLASS),
            KAIROS_EXT.silverSourceRef,
            Literal("int_party_conformed"),
        )
    )
    _write_graph(extensions / "party-silver-ext.ttl", extension_graph)

    registry = ClaimRegistry(
        domain="party",
        claims=[
            Claim(
                id="party-party",
                type="class",
                status="approved",
                disposition="claim",
                origin="imported",
                class_uri=TARGET_CLASS,
                evidence_sources=[
                    EvidenceSource(
                        type="source_table",
                        system="adminpulse",
                        table="tblRawParty",
                    )
                ],
            )
        ],
    )
    write_registry(registry, claims / "party-claims.yaml")
    sync_dbt_contracts(hub)
    return {
        "hub": hub,
        "sources": sources,
        "analysis": analysis,
        "mappings": mappings,
        "claims": claims,
        "extensions": extensions,
        "transforms": transforms,
        "properties": properties,
    }


def _check(paths: dict[str, Path]):
    return check_source_coverage(
        analysis_dir=paths["analysis"],
        sources_dir=paths["sources"],
        mappings_dir=paths["mappings"],
        claims_dir=paths["claims"],
        extensions_dir=paths["extensions"],
        hub_root=paths["hub"],
        transforms_dir=paths["transforms"],
    )


def test_governed_replacement_covers_wrong_grain_source(tmp_path: Path) -> None:
    paths = _hub(tmp_path)

    report = _check(paths)

    assert not report.is_blocking
    assert report.domain_counts["party"] == (1, 1)
    assert report.direct_counts["party"] == 0
    assert report.replacement_counts["party"] == 1
    evidence = report.replacement_evidence["party"][0]
    assert evidence.source_table_iri == SOURCE_TABLE
    assert evidence.contract_model == "int_party_conformed"


def test_weak_virtual_mapping_does_not_authorize_replacement(tmp_path: Path) -> None:
    paths = _hub(tmp_path)
    mapping = Graph()
    mapping.add((URIRef(VIRTUAL_TABLE), SKOS.closeMatch, URIRef(TARGET_CLASS)))
    _write_graph(paths["mappings"] / "custom-transformations" / "party.ttl", mapping)

    report = _check(paths)

    assert report.is_blocking
    assert "requires one table-level skos:exactMatch" in report.diagnostics["party"][0]


def test_column_only_mapping_does_not_authorize_replacement(tmp_path: Path) -> None:
    paths = _hub(tmp_path)
    mapping = Graph()
    mapping.add((URIRef(f"{VIRTUAL_TABLE}/party_id"), SKOS.exactMatch, URIRef(TARGET_CLASS)))
    _write_graph(paths["mappings"] / "custom-transformations" / "party.ttl", mapping)

    report = _check(paths)

    assert report.is_blocking
    assert "requires one table-level skos:exactMatch" in report.diagnostics["party"][0]


def test_literal_exact_match_target_does_not_authorize_replacement(
    tmp_path: Path,
) -> None:
    paths = _hub(tmp_path)
    mapping = Graph()
    mapping.add((URIRef(VIRTUAL_TABLE), SKOS.exactMatch, Literal(TARGET_CLASS)))
    _write_graph(paths["mappings"] / "custom-transformations" / "party.ttl", mapping)

    report = _check(paths)

    assert report.is_blocking
    assert "requires one table-level skos:exactMatch" in report.diagnostics["party"][0]


def test_claim_target_must_match_contract_target(tmp_path: Path) -> None:
    paths = _hub(tmp_path)
    registry = ClaimRegistry(
        domain="party",
        claims=[
            Claim(
                id="party-wrong",
                type="class",
                status="approved",
                class_uri="https://example.com/ont/party#OtherParty",
                evidence_sources=[
                    EvidenceSource(
                        type="source_table",
                        system="adminpulse",
                        table="tblRawParty",
                    )
                ],
            )
        ],
    )
    write_registry(registry, paths["claims"] / "party-claims.yaml")

    report = _check(paths)

    assert report.is_blocking
    assert "approved source-table class claim" in report.diagnostics["party"][0]


def test_claim_registry_declared_domain_must_match_checked_domain(
    tmp_path: Path,
) -> None:
    paths = _hub(tmp_path)
    registry = ClaimRegistry(
        domain="commercial",
        claims=[
            Claim(
                id="party-party",
                type="class",
                status="approved",
                class_uri=TARGET_CLASS,
                evidence_sources=[
                    EvidenceSource(
                        type="source_table",
                        system="adminpulse",
                        table="tblRawParty",
                    )
                ],
            )
        ],
    )
    write_registry(registry, paths["claims"] / "party-claims.yaml")

    report = _check(paths)

    assert report.is_blocking
    assert "declares domain 'commercial'" in report.diagnostics["party"][0]


def test_silver_source_ref_must_select_contract(tmp_path: Path) -> None:
    paths = _hub(tmp_path)
    extension = Graph()
    extension.add((URIRef(TARGET_CLASS), KAIROS_EXT.silverSourceRef, Literal("other_model")))
    _write_graph(paths["extensions"] / "party-silver-ext.ttl", extension)

    report = _check(paths)

    assert report.is_blocking
    assert "must declare silverSourceRef" in report.diagnostics["party"][0]


def test_direct_and_replacement_paths_are_a_blocking_conflict(tmp_path: Path) -> None:
    paths = _hub(tmp_path)
    mapping = Graph().parse(
        paths["mappings"] / "custom-transformations" / "party.ttl",
        format="turtle",
    )
    mapping.add((URIRef(SOURCE_TABLE), SKOS.exactMatch, URIRef(TARGET_CLASS)))
    _write_graph(paths["mappings"] / "custom-transformations" / "party.ttl", mapping)

    report = _check(paths)

    assert report.is_blocking
    assert report.domain_counts["party"] == (0, 1)
    assert "source-authority conflict" in report.diagnostics["party"][0]


def test_stale_contract_vocabulary_blocks_replacement(tmp_path: Path) -> None:
    paths = _hub(tmp_path)
    document = yaml.safe_load(paths["properties"].read_text(encoding="utf-8"))
    document["models"][0]["columns"].append({"name": "party_status", "data_type": "string"})
    paths["properties"].write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    report = _check(paths)

    assert report.is_blocking
    assert any("not synchronized" in diagnostic for diagnostic in report.diagnostics["party"])


def test_orphaned_virtual_vocabulary_never_grants_coverage(tmp_path: Path) -> None:
    paths = _hub(tmp_path)
    paths["properties"].unlink()
    (paths["transforms"] / "models" / "intermediate" / "int_party_conformed.sql").unlink()

    report = _check(paths)

    assert report.is_blocking
    assert report.uncovered["party"] == ["adminpulse.tblRawParty"]
    assert report.replacement_counts["party"] == 0


def test_multiple_replacement_contracts_are_a_blocking_conflict(tmp_path: Path) -> None:
    paths = _hub(tmp_path)
    document = yaml.safe_load(paths["properties"].read_text(encoding="utf-8"))
    alternative = copy.deepcopy(document["models"][0])
    alternative["name"] = "int_party_conformed_alternative"
    alternative["meta"]["kairos"]["virtual_source_iri"] = (
        "https://example.com/source/custom#partyConformedAlternative"
    )
    document["models"].append(alternative)
    paths["properties"].write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    (
        paths["transforms"] / "models" / "intermediate" / "int_party_conformed_alternative.sql"
    ).write_text("select party_id from source_rows\n", encoding="utf-8")
    sync_dbt_contracts(paths["hub"])

    report = _check(paths)

    assert report.is_blocking
    assert "multiple contracts claim replacement authority" in report.diagnostics["party"][0]


def test_filtered_unrelated_domain_does_not_run_replacement_preflight(
    tmp_path: Path,
) -> None:
    paths = _hub(tmp_path)
    commercial_table = URIRef("https://example.com/source/adminpulse#tblCommercial")
    source_path = paths["sources"] / "adminpulse" / "adminpulse.vocabulary.ttl"
    source_graph = Graph().parse(source_path, format="turtle")
    source_graph.add((commercial_table, RDF.type, KAIROS_BRONZE.SourceTable))
    source_graph.add((commercial_table, KAIROS_BRONZE.tableName, Literal("tblCommercial")))
    _write_graph(source_path, source_graph)
    (paths["analysis"] / "commercial-affinity.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "system": "adminpulse",
                "tables": [{"table": "tblCommercial", "domain": "commercial"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    mapping_path = paths["mappings"] / "custom-transformations" / "party.ttl"
    mapping = Graph().parse(mapping_path, format="turtle")
    mapping.add(
        (
            commercial_table,
            SKOS.exactMatch,
            URIRef("https://example.com/ont/commercial#Contract"),
        )
    )
    _write_graph(mapping_path, mapping)

    document = yaml.safe_load(paths["properties"].read_text(encoding="utf-8"))
    document["models"][0]["columns"].append({"name": "unsynchronized", "data_type": "string"})
    paths["properties"].write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    report = check_source_coverage(
        analysis_dir=paths["analysis"],
        sources_dir=paths["sources"],
        mappings_dir=paths["mappings"],
        domains_filter=["commercial"],
        claims_dir=paths["claims"],
        extensions_dir=paths["extensions"],
        hub_root=paths["hub"],
        transforms_dir=paths["transforms"],
    )

    assert not report.is_blocking
    assert report.domain_counts["commercial"] == (1, 1)
