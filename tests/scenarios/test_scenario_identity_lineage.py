# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""End-to-end DD-108 identity and lineage scenarios."""

from __future__ import annotations

import json

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)

from .conftest import (
    EXTENSIONS_DIR,
    MAPPINGS_DIR,
    SHAPES_DIR,
    SOURCES_DIR,
    TEMPLATE_DIR,
)


EXT = Namespace("https://kairos.cnext.eu/ext#")
CLIENT = "https://acme.example/ontology/client#"
PREP_ADMIN = "https://acme.example/preparation/adminpulse#"
PREP_CRM = "https://acme.example/preparation/crmsystem#"
CLIENT_SOURCE_REFS = (
    f"{PREP_ADMIN}tblClientKey",
    f"{PREP_ADMIN}tblRelationKey",
    f"{PREP_CRM}customersKey",
)


def _clone(graph: Graph) -> Graph:
    result = Graph()
    for triple in graph:
        result.add(triple)
    return result


def _replace_literal(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    value: str,
) -> None:
    graph.remove((subject, predicate, None))
    graph.add((subject, predicate, Literal(value)))


def _generate_client(
    graph: Graph,
    namespace: str,
    classes: list[dict],
    *,
    platform: str = "fabric",
):
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="client",
        ontology_metadata={
            "iri": "https://acme.example/ontology/client",
            "version": "1.0.0",
        },
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=(
            EXTENSIONS_DIR / "client-gold-ext.ttl"
            if platform == "fabric"
            else None
        ),
        target_platform=platform,
    )


def _exact_equivalence_graph(client_ontology) -> tuple[Graph, str, list[dict]]:
    source_graph, namespace, classes = client_ontology
    graph = _clone(source_graph)
    client = URIRef(f"{CLIENT}Client")
    policy = URIRef(f"{CLIENT}ClientExactSources")
    _replace_literal(
        graph,
        client,
        EXT.identityStrategy,
        "deterministic-integration-key",
    )
    graph.remove((client, EXT.multiSourcePolicy, None))
    graph.add((client, EXT.multiSourcePolicy, policy))
    graph.add((policy, RDF.type, EXT.MultiSourcePolicy))
    values = {
        EXT.branchRelationship: "exactly-equivalent",
        EXT.normalizationPolicy: (
            "codes, currency, units, and timestamps normalized by approved exact rules"
        ),
        EXT.sourcePrecedence: f"declared-order:{','.join(CLIENT_SOURCE_REFS)}",
        EXT.attributeConflictPolicy: "quarantine",
        EXT.keyCollisionPolicy: "quarantine",
        EXT.branchDeletionPolicy: "delete-when-all-branches-deleted",
        EXT.branchLateArrivalPolicy: "reconcile-on-arrival",
        EXT.reconciliationTest: "client-exact-equivalence",
    }
    for predicate, value in values.items():
        graph.add((policy, predicate, Literal(value)))
    return graph, namespace, classes


def _identity(release: dict, model_name: str) -> dict:
    return next(
        item
        for item in release["identity_lineage"]
        if item["model_name"] == model_name
    )


def _silver_execution_sql(artifacts: dict, model_name: str) -> str:
    base = f"models/silver/client/{model_name}"
    return artifacts.get(f"{base}__dq_input.sql", artifacts[f"{base}.sql"])


def test_overlap_preserves_branch_identity_and_complete_contribution_lineage(
    client_dbt_artifacts,
):
    sql = _silver_execution_sql(client_dbt_artifacts, "client")
    reconciliation = client_dbt_artifacts[
        "models/silver/client/client__reconciliation.sql"
    ]
    contributions = client_dbt_artifacts[
        "models/silver/client/client__contributions.sql"
    ]
    assert "generate_surrogate_key(['_source_system', '_source_record_key'])" in sql
    assert "client_integration_key" not in sql
    assert "integration_key" not in reconciliation
    assert "_branch_identity_duplicate" in reconciliation
    assert "'retain-source-scoped-identities' as _collision_action" in reconciliation
    assert "'reconcile-on-arrival' as _late_arrival_action" in reconciliation

    for source_ref in CLIENT_SOURCE_REFS:
        assert source_ref in contributions
    assert "'driving' as _contribution_role" in contributions
    assert "'contributor' as _contribution_role" in contributions
    assert "_source_record_key" in contributions
    assert "_source_record_id" not in contributions


def test_release_and_schema_report_all_identity_and_timestamp_roles(
    client_dbt_artifacts,
):
    release = client_dbt_artifacts["__release_data__"]
    client = _identity(release, "client")
    assert {role["role"] for role in client["roles"]} == {
        "business-natural-key",
        "source-identity",
        "integration-identity",
        "mastered-identifier",
        "surrogate-join-key",
        "entity-iri",
    }
    assert client["source_identity_refs"] == sorted(CLIENT_SOURCE_REFS)
    assert not client["integration_key_emitted"]
    assert client["entity_instance_iri_policy"] == "emit"
    assert client["contribution_lineage"] == {
        "relation_name": "client__contributions",
        "parent_key_column": "client_sk",
        "source_system_column": "_source_system",
        "source_record_key_column": "_source_record_key",
        "source_role_column": "_contribution_role",
        "source_identity_ref_column": "_source_identity_ref",
    }

    timestamps = {item["column"]: item for item in client["timestamps"]}
    assert timestamps["_loaded_at"]["origin"] == "injected-run-clock"
    assert timestamps["_loaded_at"]["supplied"]
    assert timestamps["_source_updated_at"]["supplied"]
    assert timestamps["_ingested_at"]["supplied"]
    assert timestamps["_source_effective_at"]["supplied"]
    assert "_ingested_at" in _silver_execution_sql(client_dbt_artifacts, "client")

    schema = client_dbt_artifacts[
        "models/silver/client/_client__models.yml"
    ]
    assert 'identity_strategy: "business-key"' in schema
    assert 'identity_roles: "business-natural-key"' in schema
    assert 'identity_roles: "source-identity"' in schema
    assert "_source_record_id" not in schema


def test_projection_report_persists_identity_release_metadata(
    client_dbt_artifacts,
    tmp_path,
):
    from kairos_ontology.core.projector import ProjectionReport

    report = ProjectionReport(targets_requested=["dbt"])
    report.release_data["client"] = client_dbt_artifacts["__release_data__"]
    payload = json.loads(report.write(tmp_path).read_text(encoding="utf-8"))
    identity = _identity(payload["release_data"]["client"], "client")
    assert identity["identity_strategy"] == "business-key"
    assert identity["contribution_lineage"]["source_record_key_column"] == (
        "_source_record_key"
    )


def test_entity_instance_iri_emit_and_omit_are_physical_output_choices(
    client_dbt_artifacts,
):
    client_sql = _silver_execution_sql(client_dbt_artifacts, "client")
    pii_sql = client_dbt_artifacts["models/silver/client/client_pii.sql"]
    assert "client_iri" in client_sql
    assert "client_pii_iri" not in pii_sql
    pii = _identity(client_dbt_artifacts["__release_data__"], "client_pii")
    iri_role = next(role for role in pii["roles"] if role["role"] == "entity-iri")
    assert pii["entity_instance_iri_policy"] == "omit"
    assert not iri_role["emitted"]
    assert iri_role["columns"] == []


def test_disjoint_sources_report_actions_without_shared_integration_identity(
    invoice_dbt_artifacts,
):
    release = invoice_dbt_artifacts["__release_data__"]
    invoice = _identity(release, "invoice")
    assert invoice["multi_source"] == {
        "relationship": "disjoint",
        "exact_equivalence_approved": False,
        "normalization": "currency and timestamps normalized per branch",
        "precedence_mode": "not-applicable-disjoint",
        "ordered_sources": [],
        "conflict_action": "block",
        "collision_action": "retain-source-scoped-identities",
        "deletion_action": "retain-other-branches",
        "late_arrival_action": "reconcile-on-arrival",
        "reconciliation_tests": ["invoice-branch-and-union-reconciliation"],
    }
    sql = invoice_dbt_artifacts["models/silver/invoice/invoice.sql"]
    assert "invoice_integration_key" not in sql
    timestamps = {item["column"]: item for item in invoice["timestamps"]}
    assert timestamps["_source_updated_at"]["supplied"]
    assert timestamps["_source_effective_at"]["supplied"]
    assert timestamps["_ingested_at"]["supplied"]
    source_sql = invoice_dbt_artifacts[
        "models/silver/invoice/invoice__from_billing_pro__tbl_invoice.sql"
    ]
    assert "_source_updated_at" in source_sql
    assert "_source_effective_at" in source_sql
    assert "_ingested_at" in source_sql


def test_externally_mastered_identifier_is_routing_only(client_ontology):
    source_graph, namespace, classes = client_ontology
    graph = _clone(source_graph)
    entity = URIRef(f"{CLIENT}ClientType")
    _replace_literal(
        graph,
        entity,
        EXT.identityStrategy,
        "externally-mastered-identifier",
    )
    _replace_literal(graph, entity, EXT.keyScope, "enterprise")

    artifacts = _generate_client(graph, namespace, classes)
    sql = artifacts["models/silver/client/client_type.sql"]
    release = artifacts["__release_data__"]
    identity = _identity(release, "client_type")
    assert identity["mdm_routed"]
    assert identity["mastered_identifier_refs"] == ["type_code"]
    assert not identity["integration_key_emitted"]
    key_line = next(
        line for line in sql.splitlines() if " as client_type_sk" in line
    )
    assert "_source_system" in key_line
    assert "_source_record_key" in key_line
    assert "type_code" not in key_line
    assert release["mdm_routing"] == [
        {
            "entity_uri": f"{CLIENT}ClientType",
            "probabilistic_matching_owner": "kairos-mdm-runtime",
            "survivorship_owner": "kairos-mdm-runtime",
            "persistent_enterprise_identity_owner": "kairos-mdm-runtime",
            "merge_split_owner": "kairos-mdm-runtime",
        }
    ]


def test_surrogate_only_carries_reconciliation_limitation(client_ontology):
    source_graph, namespace, classes = client_ontology
    graph = _clone(source_graph)
    entity = URIRef(f"{CLIENT}ClientPII")
    _replace_literal(graph, entity, EXT.identityStrategy, "surrogate-only")
    graph.remove((entity, EXT.naturalKey, None))
    graph.add(
        (
            entity,
            EXT.reconciliationLimitation,
            Literal("No stable business key; reconcile only within the source record scope."),
        )
    )

    artifacts = _generate_client(graph, namespace, classes)
    identity = _identity(artifacts["__release_data__"], "client_pii")
    sql = artifacts["models/silver/client/client_pii.sql"]
    assert identity["identity_strategy"] == "surrogate-only"
    assert identity["natural_key_columns"] == []
    assert identity["reconciliation_limitation"].startswith("No stable business key")
    key_line = next(
        line for line in sql.splitlines() if " as client_pii_sk" in line
    )
    assert "_source_record_key" in key_line
    assert "client_id" not in key_line
    assert "tbl_client_pii." not in key_line
    assert "client_pii_iri" not in sql


def test_exact_equivalence_emits_integration_identity_on_each_adapter(client_ontology):
    graph, namespace, classes = _exact_equivalence_graph(client_ontology)
    logical_release = None
    for platform in ("fabric", "databricks"):
        artifacts = _generate_client(graph, namespace, classes, platform=platform)
        sql = _silver_execution_sql(artifacts, "client")
        reconciliation = artifacts[
            "models/silver/client/client__reconciliation.sql"
        ]
        identity = _identity(artifacts["__release_data__"], "client")
        assert "client_integration_key" in sql
        assert "conformance_ranked" in sql
        assert "partition by {{ dbt_utils.generate_surrogate_key(['client_id']) }}" in sql
        assert "client_integration_key" in reconciliation
        assert identity["integration_key_emitted"]
        assert identity["multi_source"]["exact_equivalence_approved"]
        assert identity["multi_source"]["ordered_sources"] == list(CLIENT_SOURCE_REFS)
        comparable = {
            "identity_strategy": identity["identity_strategy"],
            "roles": identity["roles"],
            "multi_source": identity["multi_source"],
            "driving_source": identity["driving_source"],
        }
        if logical_release is None:
            logical_release = comparable
        else:
            assert comparable == logical_release


def test_identity_authority_reaches_release_plan_and_gold_inputs(client_ontology):
    from kairos_ontology.core.projections.dbt import (
        DbtInputs,
        bind_sources,
        normalize_contract,
        plan_materialization,
        shape_project,
    )

    graph, namespace, classes = _exact_equivalence_graph(client_ontology)
    inputs = DbtInputs.from_call(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="client",
        ontology_metadata={
            "iri": "https://acme.example/ontology/client",
            "version": "1.0.0",
        },
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=EXTENSIONS_DIR / "client-gold-ext.ttl",
        target_platform="fabric",
    )
    contract = normalize_contract(bind_sources(inputs))
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    authority = dict(shaped.silver_registry.authorities)["client"]
    assert authority in plan.release.silver_authorities
    assert authority.entity_identity is contract.policy.identities[0]
    assert shaped.gold_product is not None
    gold_table = shaped.gold_product.tables[0]
    assert gold_table.source_model == authority.identity.model_name
    assert {column.name for column in gold_table.columns} == dict(
        shaped.silver_registry.columns
    )[gold_table.source_model]


def test_exact_equivalence_artifacts_are_deterministic(client_ontology):
    graph, namespace, classes = _exact_equivalence_graph(client_ontology)
    first = _generate_client(graph, namespace, classes)
    second = _generate_client(graph, namespace, classes)
    identity_paths = {
        path
        for path in first
        if path == "__release_data__"
        or path.endswith("client.sql")
        or "__contributions.sql" in path
        or "__reconciliation.sql" in path
        or path.endswith("_client__models.yml")
    }
    assert identity_paths
    assert {path: first[path] for path in identity_paths} == {
        path: second[path] for path in identity_paths
    }
