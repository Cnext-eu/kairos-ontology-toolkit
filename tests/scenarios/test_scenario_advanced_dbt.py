# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""End-to-end scenario for governed advanced Bronze-to-Silver dbt logic."""

import hashlib
import json
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
from kairos_ontology.core.dbt_contract_sync import (
    column_iri,
    legacy_column_iri,
    sync_dbt_contracts,
)
from kairos_ontology.core.dbt_contract_identity import (
    ContractIdentityEvidenceError,
    capture_dbt_run_results,
)
from kairos_ontology.core.dbt_contracts import discover_dbt_contracts
from kairos_ontology.core.projection_readiness import check_projection
from kairos_ontology.core.projector import ProjectionRunError, run_projections
from kairos_ontology.core.source_coverage import check_source_coverage
from kairos_ontology.core.transformation_candidates import (
    evaluate_transformation_readiness,
)

BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
EXT = Namespace("https://kairos.cnext.eu/ext#")
KMAP = Namespace("https://kairos.cnext.eu/mapping#")
DOMAIN = Namespace("https://example.com/ontology/shipment#")
SOURCE = Namespace("https://example.com/source/transport#")
VIRTUAL = Namespace("https://example.com/source/custom/shipment")


def _write_graph(graph: Graph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(path, format="turtle")


def _create_hub(
    root: Path,
    *,
    supported_adapters: list[str] | None = None,
    legacy_column_iris: bool = False,
) -> Path:
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
    table_mapping = URIRef(f"{VIRTUAL}/mapping/table")
    mapping.add((table_mapping, RDF.type, KMAP.TableMapping))
    mapping.add((table_mapping, KMAP.sourceTable, virtual_table))
    mapping.add((table_mapping, KMAP.targetClass, DOMAIN.Shipment))
    mapping.add((table_mapping, KMAP.mappingType, Literal("direct")))
    mapping.add((table_mapping, KMAP.matchType, Literal("exactMatch")))
    for name, target in (
        ("shipment_id", DOMAIN.shipmentId),
        ("route_code", DOMAIN.routeCode),
    ):
        source_column = (
            legacy_column_iri(str(VIRTUAL), name)
            if legacy_column_iris
            else column_iri(str(VIRTUAL), name)
        )
        mapping_resource = URIRef(f"{VIRTUAL}/mapping/{name}")
        mapping.add((source_column, SKOS.exactMatch, target))
        mapping.add((mapping_resource, RDF.type, KMAP.ColumnMapping))
        mapping.add((mapping_resource, KMAP.sourceColumn, source_column))
        mapping.add((mapping_resource, KMAP.targetProperty, target))
        mapping.add((mapping_resource, KMAP.matchType, Literal("exactMatch")))
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
                        "supported_adapters": supported_adapters or ["fabric", "databricks"],
                        "grain_key": ["shipment_id"],
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
                    {
                        "name": "shipment_id",
                        "data_type": "string",
                        "data_tests": ["not_null", "unique"],
                    },
                    {
                        "name": "route_code",
                        "data_type": "string",
                        "data_tests": ["not_null"],
                    },
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
    sync_report = sync_dbt_contracts(hub)
    if legacy_column_iris:
        vocabulary = sync_report.items[0].output_path
        virtual_graph = Graph().parse(vocabulary, format="turtle")
        replacements = {
            resource: legacy_column_iri(
                str(virtual_graph.value(resource, BRONZE.sourceTable)),
                str(virtual_graph.value(resource, BRONZE.columnName)),
            )
            for resource in virtual_graph.subjects(RDF.type, BRONZE.SourceColumn)
        }
        for subject, predicate, object_ in tuple(virtual_graph):
            virtual_graph.remove((subject, predicate, object_))
            virtual_graph.add(
                (
                    replacements.get(subject, subject),
                    predicate,
                    replacements.get(object_, object_),
                )
            )
        virtual_graph.serialize(vocabulary, format="turtle")
        assert sync_dbt_contracts(hub).items[0].state == "unchanged"
    return hub


def _bind_contract_identity(hub: Path) -> URIRef:
    path = hub / "model" / "extensions" / "shipment-silver-ext.ttl"
    graph = Graph().parse(path, format="turtle")
    identity = URIRef(f"{VIRTUAL}/contract-identity")
    graph.add((DOMAIN.Shipment, EXT.businessGrain, Literal("one row per shipment")))
    graph.add(
        (DOMAIN.Shipment, EXT.identityStrategy, Literal("source-scoped-immutable-key"))
    )
    graph.add((DOMAIN.Shipment, EXT.entityInstanceIriPolicy, Literal("emit")))
    graph.add((DOMAIN.Shipment, EXT.keyScope, Literal("source-table")))
    graph.add((DOMAIN.Shipment, EXT.sourceIdentity, identity))
    graph.add((DOMAIN.Shipment, EXT.changeDetectionStrategy, Literal("compare-columns")))
    graph.add((DOMAIN.Shipment, EXT.lineagePolicy, Literal("source-record")))
    graph.serialize(path, format="turtle")
    return identity


def _identity_artifacts(hub: Path) -> tuple[dict, dict]:
    contract = discover_dbt_contracts(
        hub / "integration" / "transforms" / "dbt", hub
    )[0]
    transforms = hub / "integration" / "transforms" / "dbt"
    properties = yaml.safe_load(contract.properties_path.read_text(encoding="utf-8"))
    model_definition = properties["models"][0]
    model_id = "model.pkg.int_shipment_conformed"
    invocation_metadata = {
        "invocation_id": "warehouse-run-123",
        "generated_at": "2026-07-26",
        "dbt_version": "1.10.0",
        "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json",
    }
    manifest = {
        "metadata": invocation_metadata,
        "unit_tests": {
            "unit_test.pkg.int_shipment_conformed.unit_test_route_fallback": {
                **properties["unit_tests"][0],
                "resource_type": "unit_test",
                "unique_id": (
                    "unit_test.pkg.int_shipment_conformed.unit_test_route_fallback"
                ),
            }
        },
        "nodes": {
            model_id: {
                "resource_type": "model",
                "name": "int_shipment_conformed",
                "unique_id": model_id,
                "original_file_path": "models/intermediate/int_shipment_conformed.sql",
                "raw_code": contract.sql_path.read_text(encoding="utf-8"),
                "checksum": {
                    "name": "sha256",
                    "checksum": hashlib.sha256(
                        contract.sql_path.read_text(encoding="utf-8").encode("utf-8")
                    ).hexdigest(),
                },
                "description": model_definition["description"],
                "meta": model_definition["meta"],
                "config": model_definition["config"],
                "constraints": [],
                "columns": {
                    column["name"]: {
                        "name": column["name"],
                        "description": column.get("description", ""),
                        "data_type": column["data_type"],
                        "meta": column.get("meta", {}),
                        "constraints": column.get("constraints", []),
                    }
                    for column in model_definition["columns"]
                },
            },
            "test.pkg.unique_int_shipment_conformed_shipment_id": {
                "resource_type": "test",
                "column_name": "shipment_id",
                "attached_node": model_id,
                "depends_on": {"nodes": [model_id]},
                "test_metadata": {
                    "name": "unique",
                    "kwargs": {
                        "model": "{{ get_where_subquery(ref('int_shipment_conformed')) }}",
                        "column_name": "shipment_id",
                    },
                },
            },
            "test.pkg.not_null_int_shipment_conformed_shipment_id": {
                "resource_type": "test",
                "column_name": "shipment_id",
                "attached_node": model_id,
                "depends_on": {"nodes": [model_id]},
                "test_metadata": {
                    "name": "not_null",
                    "kwargs": {
                        "model": "{{ get_where_subquery(ref('int_shipment_conformed')) }}",
                        "column_name": "shipment_id",
                    },
                },
            },
            "test.pkg.not_null_int_shipment_conformed_route_code": {
                "resource_type": "test",
                "column_name": "route_code",
                "attached_node": model_id,
                "depends_on": {"nodes": [model_id]},
                "test_metadata": {
                    "name": "not_null",
                    "kwargs": {
                        "model": "{{ get_where_subquery(ref('int_shipment_conformed')) }}",
                        "column_name": "route_code",
                    },
                },
            },
            "test.pkg.shipment_grain": {
                "resource_type": "test",
                "name": "shipment_grain",
                "unique_id": "test.pkg.shipment_grain",
                "original_file_path": "tests/shipment_grain.sql",
                "raw_code": (transforms / "tests" / "shipment_grain.sql").read_text(
                    encoding="utf-8"
                ),
                "checksum": {
                    "name": "sha256",
                    "checksum": hashlib.sha256(
                        (transforms / "tests" / "shipment_grain.sql")
                        .read_text(encoding="utf-8")
                        .encode("utf-8")
                    ).hexdigest(),
                },
                "depends_on": {"nodes": [model_id]},
            },
        }
    }
    run_metadata = {
        **invocation_metadata,
        "dbt_schema_version": "https://schemas.getdbt.com/dbt/run-results/v6.json",
    }
    run_results = {
        "metadata": run_metadata,
        "results": [
            {"unique_id": unique_id, "status": "pass"}
            for unique_id in manifest["nodes"]
            if unique_id.startswith("test.")
        ],
    }
    return run_results, manifest


def _write_identity_artifacts(
    hub: Path, run_results: dict, manifest: dict
) -> tuple[Path, Path]:
    target = hub / "dbt-actual-results"
    target.mkdir(exist_ok=True)
    manifest_path = target / "manifest.json"
    results_path = target / "run_results.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    results_path.write_text(json.dumps(run_results), encoding="utf-8")
    return results_path, manifest_path


def _capture_passing_identity_evidence(hub: Path) -> None:
    run_results, manifest = _identity_artifacts(hub)
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)
    capture_dbt_run_results(hub, results_path, manifest_path)
    sync_dbt_contracts(hub)


def test_contract_identity_requires_actual_current_passing_evidence(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    identity = _bind_contract_identity(hub)
    vocabulary = (
        hub
        / "integration"
        / "sources"
        / "custom-transformations"
        / "int_shipment_conformed.vocabulary.ttl"
    )
    graph = Graph().parse(vocabulary, format="turtle")
    assert (identity, RDF.type, Namespace("https://kairos.cnext.eu/dbt-contract#").ContractIdentity) in graph

    readiness = check_projection(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "missing-catalog.xml",
        output_path=tmp_path / "check-only",
        target="dbt",
        namespace=None,
        platform="fabric",
        emit_aspirational_stubs=False,
        degraded=False,
        ref_models_dir=None,
        accelerator=None,
    )
    assert readiness.ready
    assert any(
        item["rule_id"] == "DD-108-contract-identity"
        and item["blocking"] is False
        for item in readiness.diagnostics
    )

    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "missing-catalog.xml",
        output_path=tmp_path / "declared-only",
        target="dbt",
        platform="fabric",
    )
    release_review = json.loads(
        (
            tmp_path
            / "declared-only"
            / "medallion"
            / "dbt"
            / "metadata"
            / "shipment-release-review.json"
        ).read_text(encoding="utf-8")
    )
    assert release_review["mode"] == "review-only"
    assert any(
        issue["code"] == "identity.contract-unverified"
        for issue in release_review["policy_issues"]
    )
    with pytest.raises(ProjectionRunError, match="Strict release blocked"):
        run_projections(
            ontologies_path=hub / "model" / "ontologies",
            catalog_path=hub / "missing-catalog.xml",
            output_path=tmp_path / "declared-only-strict",
            target="dbt",
            platform="fabric",
            strict=True,
        )

    _capture_passing_identity_evidence(hub)
    verified_graph = Graph().parse(vocabulary, format="turtle")
    dbt = Namespace("https://kairos.cnext.eu/dbt-contract#")
    assert verified_graph.value(identity, dbt.identityScope) == Literal("contract-output")
    assert verified_graph.value(identity, dbt.verificationStatus) == Literal("verified")
    assert verified_graph.value(identity, dbt.evidenceContentHash) == verified_graph.value(
        identity, dbt.contractContentHash
    )
    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "missing-catalog.xml",
        output_path=tmp_path / "verified",
        target="dbt",
        platform="fabric",
    )

    sql = (
        hub
        / "integration"
        / "transforms"
        / "dbt"
        / "models"
        / "intermediate"
        / "int_shipment_conformed.sql"
    )
    sql.write_text(sql.read_text(encoding="utf-8") + "\n-- changed contract SQL\n", encoding="utf-8")
    sync_dbt_contracts(hub)
    stale_graph = Graph().parse(vocabulary, format="turtle")
    assert stale_graph.value(identity, dbt.verificationStatus) == Literal("unverified")
    assert stale_graph.value(identity, dbt.evidenceContentHash) is None
    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "missing-catalog.xml",
        output_path=tmp_path / "stale",
        target="dbt",
        platform="fabric",
    )


def test_contract_identity_rejects_stale_sql_artifacts(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    run_results, manifest = _identity_artifacts(hub)
    sql = (
        hub
        / "integration"
        / "transforms"
        / "dbt"
        / "models"
        / "intermediate"
        / "int_shipment_conformed.sql"
    )
    sql.write_text(sql.read_text(encoding="utf-8") + "\n-- changed after dbt run\n", encoding="utf-8")
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)

    with pytest.raises(ContractIdentityEvidenceError, match="raw_code does not match"):
        capture_dbt_run_results(hub, results_path, manifest_path)


def test_contract_identity_rejects_stale_yaml_and_tests(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    run_results, manifest = _identity_artifacts(hub)
    properties = (
        hub
        / "integration"
        / "transforms"
        / "dbt"
        / "models"
        / "intermediate"
        / "int_shipment_conformed.yml"
    )
    document = yaml.safe_load(properties.read_text(encoding="utf-8"))
    document["unit_tests"][0]["expect"]["rows"][0]["route_code"] = "CHANGED"
    properties.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)

    with pytest.raises(ContractIdentityEvidenceError, match="unit-test definitions"):
        capture_dbt_run_results(hub, results_path, manifest_path)


def test_contract_identity_rejects_mismatched_invocations(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    run_results, manifest = _identity_artifacts(hub)
    manifest["metadata"]["invocation_id"] = "different-run"
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)

    with pytest.raises(ContractIdentityEvidenceError, match="invocation mismatch"):
        capture_dbt_run_results(hub, results_path, manifest_path)


def test_contract_identity_rejects_missing_provenance_metadata(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    run_results, manifest = _identity_artifacts(hub)
    manifest.pop("metadata")
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)

    with pytest.raises(ContractIdentityEvidenceError, match="manifest.json lacks metadata"):
        capture_dbt_run_results(hub, results_path, manifest_path)


def test_contract_identity_rejects_missing_model_node(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    run_results, manifest = _identity_artifacts(hub)
    manifest["nodes"].pop("model.pkg.int_shipment_conformed")
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)

    with pytest.raises(ContractIdentityEvidenceError, match="exactly one matching model node"):
        capture_dbt_run_results(hub, results_path, manifest_path)


def test_contract_identity_rejects_wrong_manifest_model(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    run_results, manifest = _identity_artifacts(hub)
    manifest["nodes"]["model.pkg.int_shipment_conformed"]["original_file_path"] = (
        "models/other/int_shipment_conformed.sql"
    )
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)

    with pytest.raises(ContractIdentityEvidenceError, match="wrong original_file_path"):
        capture_dbt_run_results(hub, results_path, manifest_path)


def test_contract_identity_rejects_stale_model_yaml_semantics(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    run_results, manifest = _identity_artifacts(hub)
    properties = (
        hub
        / "integration"
        / "transforms"
        / "dbt"
        / "models"
        / "intermediate"
        / "int_shipment_conformed.yml"
    )
    document = yaml.safe_load(properties.read_text(encoding="utf-8"))
    document["models"][0]["description"] = "Changed after dbt parsed the project."
    properties.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)

    with pytest.raises(ContractIdentityEvidenceError, match="manifest description is stale"):
        capture_dbt_run_results(hub, results_path, manifest_path)


def test_contract_identity_rejects_stale_generic_tests(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    run_results, manifest = _identity_artifacts(hub)
    properties = (
        hub
        / "integration"
        / "transforms"
        / "dbt"
        / "models"
        / "intermediate"
        / "int_shipment_conformed.yml"
    )
    document = yaml.safe_load(properties.read_text(encoding="utf-8"))
    document["models"][0]["columns"][0]["data_tests"].remove("unique")
    properties.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)

    with pytest.raises(ContractIdentityEvidenceError, match="not declared"):
        capture_dbt_run_results(hub, results_path, manifest_path)


def test_contract_identity_accepts_standard_v12_artifacts(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    run_results, manifest = _identity_artifacts(hub)
    results_path, manifest_path = _write_identity_artifacts(hub, run_results, manifest)

    output = capture_dbt_run_results(hub, results_path, manifest_path)

    assert output.is_file()
    assert "kairos_content_fingerprints" not in manifest["metadata"]


def test_existing_contract_is_checked_with_empty_candidate_inventory(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    inventory = hub / "model" / "planning" / "dbt-transformations" / "candidates.yaml"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(
        "schema_version: 1\nprojection_authority: false\nroots: []\ncandidates: []\n",
        encoding="utf-8",
    )

    report = evaluate_transformation_readiness(hub, stage="mapping")

    # DD-119: unverified contract-output identity alone is release-only evidence; it
    # never blocks mapping readiness, though it must remain visible for review.
    assert report.is_blocking is False
    assert report.candidates[0].id == "contract:int_shipment_conformed"
    assert "identity.contract-unverified" in report.candidates[0].reasons[0]

    release_report = evaluate_transformation_readiness(hub, stage="release")
    assert release_report.is_blocking
    assert "identity.contract-unverified" in release_report.candidates[0].reasons[0]


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


def test_virtual_vocabulary_preserves_contract_nullability(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path)
    vocabulary = (
        hub
        / "integration"
        / "sources"
        / "custom-transformations"
        / "int_shipment_conformed.vocabulary.ttl"
    )
    graph = Graph().parse(vocabulary, format="turtle")

    shipment_id = column_iri(str(VIRTUAL), "shipment_id")
    route_code = column_iri(str(VIRTUAL), "route_code")
    assert graph.value(shipment_id, BRONZE.nullable).toPython() is False
    assert graph.value(route_code, BRONZE.nullable).toPython() is False


def test_single_adapter_contract_rejects_other_projection(tmp_path: Path) -> None:
    hub = _create_hub(tmp_path, supported_adapters=["fabric"])

    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "missing-catalog.xml",
        output_path=tmp_path / "fabric-output",
        target="dbt",
        platform="fabric",
    )
    with pytest.raises(ProjectionRunError, match="dbt projection failed"):
        run_projections(
            ontologies_path=hub / "model" / "ontologies",
            catalog_path=hub / "missing-catalog.xml",
            output_path=tmp_path / "databricks-output",
            target="dbt",
            platform="databricks",
        )


def test_existing_legacy_virtual_vocabulary_and_mapping_still_project(
    tmp_path: Path,
) -> None:
    hub = _create_hub(tmp_path, legacy_column_iris=True)
    output = tmp_path / "legacy-output"

    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "missing-catalog.xml",
        output_path=output,
        target="dbt",
        platform="fabric",
    )

    assert (
        output / "medallion" / "dbt" / "models" / "silver" / "shipment" / "shipment.sql"
    ).is_file()


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
                            if key not in {"data_type", "physical_type"}
                        },
                    }
                    for column in model["columns"]
                ],
            }
            for model in schema["models"]
        ]

    assert contracts["fabric"] == contracts["databricks"]
