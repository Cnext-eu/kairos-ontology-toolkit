# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""End-to-end scenario for governed advanced Bronze-to-Silver dbt logic."""

from pathlib import Path

import pytest
import yaml
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    EvidenceSource,
    write_registry,
)
from kairos_ontology.core.dbt_contract_sync import sync_dbt_contracts
from kairos_ontology.core.projector import run_projections
from kairos_ontology.core.source_coverage import check_source_coverage

BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
EXT = Namespace("https://kairos.cnext.eu/ext#")
KMAP = Namespace("https://kairos.cnext.eu/mapping#")
DOMAIN = Namespace("https://example.com/ontology/shipment#")
SOURCE = Namespace("https://example.com/source/transport#")
VIRTUAL = Namespace("https://example.com/source/custom/shipment")


def _write_graph(graph: Graph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(path, format="turtle")


def _create_hub(root: Path) -> Path:
    hub = root / "advanced-dbt-hub"

    ontology = Graph()
    ontology.add((URIRef("https://example.com/ontology/shipment"), RDF.type, OWL.Ontology))
    ontology.add((URIRef("https://example.com/ontology/shipment"), RDFS.label, Literal("Shipment")))
    ontology.add(
        (
            URIRef("https://example.com/ontology/shipment"),
            OWL.versionInfo,
            Literal("1.0.0"),
        )
    )
    ontology.add((DOMAIN.Shipment, RDF.type, OWL.Class))
    ontology.add((DOMAIN.Shipment, RDFS.label, Literal("Shipment")))
    ontology.add((DOMAIN.Shipment, RDFS.comment, Literal("A transported shipment.")))
    for prop, label, datatype in (
        (DOMAIN.shipmentId, "shipment ID", XSD.string),
        (DOMAIN.routeCode, "route code", XSD.string),
    ):
        ontology.add((prop, RDF.type, OWL.DatatypeProperty))
        ontology.add((prop, RDFS.label, Literal(label)))
        ontology.add((prop, RDFS.comment, Literal(f"The {label}.")))
        ontology.add((prop, RDFS.domain, DOMAIN.Shipment))
        ontology.add((prop, RDFS.range, datatype))
    ontology_path = hub / "model" / "ontologies" / "shipment.ttl"
    _write_graph(ontology, ontology_path)

    extension = Graph()
    extension.add((DOMAIN.Shipment, EXT.silverSourceRef, Literal("int_shipment_conformed")))
    extension.add((DOMAIN.Shipment, EXT.naturalKey, Literal("shipmentId")))
    _write_graph(extension, hub / "model" / "extensions" / "shipment-silver-ext.ttl")

    source = Graph()
    source.add((SOURCE.transport, RDF.type, BRONZE.SourceSystem))
    source.add((SOURCE.transport, RDFS.label, Literal("transport")))
    source.add((SOURCE.transport, BRONZE.database, Literal("bronze")))
    source.add((SOURCE.transport, BRONZE.schema, Literal("dbo")))
    for table, name in ((SOURCE.booking, "booking"), (SOURCE.stop, "stop")):
        source.add((table, RDF.type, BRONZE.SourceTable))
        source.add((table, RDFS.label, Literal(name)))
        source.add((table, BRONZE.sourceSystem, SOURCE.transport))
        source.add((table, BRONZE.tableName, Literal(name)))
    for column, table, name in (
        (SOURCE.booking_shipment_id, SOURCE.booking, "shipment_id"),
        (SOURCE.booking_route, SOURCE.booking, "route_code"),
        (SOURCE.stop_shipment_id, SOURCE.stop, "shipment_id"),
        (SOURCE.stop_route, SOURCE.stop, "route_code"),
        (SOURCE.stop_sequence, SOURCE.stop, "sequence"),
    ):
        source.add((column, RDF.type, BRONZE.SourceColumn))
        source.add((column, BRONZE.sourceTable, table))
        source.add((column, BRONZE.columnName, Literal(name)))
        source.add((column, BRONZE.dataType, Literal("string")))
    _write_graph(
        source,
        hub / "integration" / "sources" / "transport" / "transport.vocabulary.ttl",
    )

    mapping = Graph()
    virtual_table = URIRef(str(VIRTUAL))
    mapping.add((virtual_table, SKOS.exactMatch, DOMAIN.Shipment))
    mapping.add((virtual_table, KMAP.mappingType, Literal("direct")))
    mapping.add((URIRef(f"{VIRTUAL}/shipment_id"), SKOS.exactMatch, DOMAIN.shipmentId))
    mapping.add((URIRef(f"{VIRTUAL}/route_code"), SKOS.exactMatch, DOMAIN.routeCode))
    _write_graph(
        mapping,
        hub / "model" / "mappings" / "custom-transformations" / "shipment.ttl",
    )

    transforms = hub / "integration" / "transforms" / "dbt"
    model_dir = transforms / "models" / "intermediate"
    model_dir.mkdir(parents=True)
    (transforms / "tests").mkdir()
    (transforms / "macros").mkdir()
    (model_dir / "int_shipment_conformed.sql").write_text(
        """with ranked_stops as (
    select shipment_id, route_code,
           row_number() over (partition by shipment_id order by sequence) as route_rank
    from {{ source('transport', 'stop') }}
)
select b.shipment_id,
       coalesce(b.route_code, s.route_code) as route_code
from {{ source('transport', 'booking') }} b
left join ranked_stops s on b.shipment_id = s.shipment_id and s.route_rank = 1
""",
        encoding="utf-8",
    )
    (transforms / "tests" / "shipment_grain.sql").write_text(
        """select shipment_id
from {{ ref('int_shipment_conformed') }}
group by shipment_id
having count(*) > 1
""",
        encoding="utf-8",
    )
    contract = {
        "version": 2,
        "models": [
            {
                "name": "int_shipment_conformed",
                "description": "One conformed row per shipment.",
                "config": {
                    "materialized": "table",
                    "contract": {"enforced": True},
                },
                "meta": {
                    "kairos": {
                        "target_class": str(DOMAIN.Shipment),
                        "virtual_source_iri": str(VIRTUAL),
                        "grain": "one row per shipment",
                        "supported_adapters": ["fabric", "databricks"],
                        "natural_key": ["shipment_id"],
                        "required_packages": [],
                        "required_macros": [],
                        "replaces_sources": [
                            {"table_iri": str(SOURCE.booking)},
                            {"table_iri": str(SOURCE.stop)},
                        ],
                        "decisions": [
                            {
                                "id": "route-fallback",
                                "statement": "Use booking route, then the first stop route.",
                                "evidence": [
                                    {
                                        "artifact": "model/ontologies/shipment.ttl",
                                        "subject": str(DOMAIN.routeCode),
                                    }
                                ],
                                "confidence": "high",
                                "status": "developer_approved",
                                "approval": {
                                    "actor": "scenario-developer",
                                    "timestamp": "2026-07-18T12:00:00+00:00",
                                },
                                "implemented_by": {"model": "int_shipment_conformed"},
                                "verified_by": ["unit_test_route_fallback"],
                            }
                        ],
                    }
                },
                "columns": [
                    {"name": "shipment_id", "data_type": "string"},
                    {"name": "route_code", "data_type": "string"},
                ],
            }
        ],
        "unit_tests": [
            {
                "name": "unit_test_route_fallback",
                "model": "int_shipment_conformed",
                "given": [],
                "expect": {"rows": [{"shipment_id": "S1", "route_code": "R1"}]},
            }
        ],
    }
    (model_dir / "int_shipment_conformed.yml").write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )
    analysis = hub / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True)
    (analysis / "transport-affinity.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "system": "transport",
                "tables": [
                    {"table": "booking", "domain": "shipment"},
                    {"table": "stop", "domain": "shipment"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    write_registry(
        ClaimRegistry(
            domain="shipment",
            claims=[
                Claim(
                    id="shipment-shipment",
                    type="class",
                    status="approved",
                    disposition="claim",
                    class_uri=str(DOMAIN.Shipment),
                    evidence_sources=[
                        EvidenceSource(type="source_table", system="transport", table="booking"),
                        EvidenceSource(type="source_table", system="transport", table="stop"),
                    ],
                )
            ],
        ),
        hub / "model" / "claims" / "shipment-claims.yaml",
    )
    sync_dbt_contracts(hub)
    return hub


def test_wrong_grain_sources_are_covered_only_by_governed_replacement(
    tmp_path: Path,
) -> None:
    hub = _create_hub(tmp_path)

    report = check_source_coverage(
        analysis_dir=hub / "integration" / "sources" / "_analysis",
        sources_dir=hub / "integration" / "sources",
        mappings_dir=hub / "model" / "mappings",
        claims_dir=hub / "model" / "claims",
        extensions_dir=hub / "model" / "extensions",
        hub_root=hub,
    )

    assert not report.is_blocking
    assert report.domain_counts["shipment"] == (2, 2)
    assert report.direct_counts["shipment"] == 0
    assert report.replacement_counts["shipment"] == 2


@pytest.mark.parametrize(
    ("platform", "expected_type"),
    [("fabric", "VARCHAR"), ("databricks", "STRING")],
)
def test_advanced_transformation_projects_complete_package(
    tmp_path: Path,
    platform: str,
    expected_type: str,
) -> None:
    hub = _create_hub(tmp_path)
    output = tmp_path / f"output-{platform}"

    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "missing-catalog.xml",
        output_path=output,
        target="dbt",
        platform=platform,
    )

    project = output / "medallion" / "dbt"
    custom_sql = project / "models" / "intermediate" / "int_shipment_conformed.sql"
    wrapper = project / "models" / "silver" / "shipment" / "shipment.sql"
    assert custom_sql.is_file()
    assert "row_number() over" in custom_sql.read_text(encoding="utf-8")
    sources_yaml = project / "models" / "silver" / "_transport__sources.yml"
    assert "booking" in sources_yaml.read_text(encoding="utf-8")
    assert "stop" in sources_yaml.read_text(encoding="utf-8")
    wrapper_sql = wrapper.read_text(encoding="utf-8")
    assert "ref('int_shipment_conformed')" in wrapper_sql
    assert "source(" not in wrapper_sql
    schema = (project / "models" / "silver" / "shipment" / "_shipment__models.yml").read_text(
        encoding="utf-8"
    )
    assert expected_type in schema
    assert (project / "tests" / "shipment_grain.sql").is_file()
    assert "route-fallback" in (
        project / "models" / "intermediate" / "int_shipment_conformed.yml"
    ).read_text(encoding="utf-8")


def test_fabric_and_databricks_share_the_same_semantic_contract(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    contracts: dict[str, list[dict]] = {}

    for platform in ("fabric", "databricks"):
        output = tmp_path / f"conformance-{platform}"
        run_projections(
            ontologies_path=hub / "model" / "ontologies",
            catalog_path=hub / "missing-catalog.xml",
            output_path=output,
            target="dbt",
            platform=platform,
        )
        schema_path = (
            output
            / "medallion"
            / "dbt"
            / "models"
            / "silver"
            / "shipment"
            / "_shipment__models.yml"
        )
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        contracts[platform] = [
            {
                "name": model["name"],
                "columns": [
                    {
                        "name": column["name"],
                        "tests": column.get("tests", []),
                        "meta": {
                            key: value
                            for key, value in column.get("meta", {}).items()
                            if key != "data_type"
                        },
                    }
                    for column in model["columns"]
                ],
            }
            for model in schema["models"]
        ]

    assert contracts["fabric"] == contracts["databricks"]
