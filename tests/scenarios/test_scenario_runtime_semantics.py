# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""End-to-end DD-109 runtime scenarios for Fabric and Databricks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from rdflib import Graph, Literal, Namespace

from kairos_ontology.core.projections.dbt import PolicyNormalizationError
from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)


HUB = Path(__file__).parent / "acme-hub"
TEMPLATES = Path(__file__).parents[2] / "src" / "kairos_ontology" / "templates" / "dbt"
EXT = Namespace("https://kairos.cnext.eu/ext#")
CLIENT = Namespace("https://acme.example/ontology/client#")
INVOICE = Namespace("https://acme.example/ontology/invoice#")


def _generate(
    ontology,
    domain: str,
    *,
    adapter: str = "fabric",
    graph: Graph | None = None,
) -> dict:
    source_graph, namespace, classes = ontology
    peer_extensions = (
        [HUB / "model" / "extensions" / "client-silver-ext.ttl"]
        if domain == "invoice"
        else []
    )
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph or source_graph,
        template_dir=TEMPLATES,
        namespace=namespace,
        ontology_name=domain,
        ontology_metadata={
            "iri": f"https://acme.example/ontology/{domain}",
            "version": "1.0.0",
        },
        sources_dir=HUB / "integration" / "sources",
        mappings_dir=HUB / "model" / "mappings",
        gold_ext_path=(
            None
            if adapter == "databricks"
            else HUB / "model" / "extensions" / f"{domain}-gold-ext.ttl"
        ),
        silver_ext_path=(
            None
            if graph is not None
            else HUB / "model" / "extensions" / f"{domain}-silver-ext.ttl"
        ),
        peer_ext_paths=peer_extensions,
        target_platform=adapter,
    )


def _runtime(release: dict, model_name: str) -> dict:
    return next(
        item
        for item in release["runtime_semantics"]
        if item["model_name"] == model_name
    )


def _temporal(release: dict, property_uri: str) -> dict:
    return next(
        item
        for item in release["temporal_foreign_keys"]
        if item["property_uri"] == property_uri
    )


def test_scd1_scd2_runtime_uses_source_and_system_time_without_loaded_at_fallback(
    client_dbt_artifacts,
    invoice_dbt_artifacts,
):
    scd2 = client_dbt_artifacts["models/silver/client/client_pii.sql"]
    scd1 = invoice_dbt_artifacts["models/silver/invoice/invoice_tag.sql"]
    assert "silver dd-109 scd2 runtime" in scd2.lower()
    assert "_business_valid_from" in scd2
    assert "_system_from" in scd2
    assert "_source_effective_at" in scd2
    assert "_ingested_at" in scd2
    assert "_loaded_at as _business_valid_from" not in scd2
    assert "kairos_canonical_hash_v1" in scd2
    assert "kairos_row_hash" not in scd2
    assert "silver dd-109 scd1 runtime" in scd1.lower()
    assert "row_number() over" in scd1.lower()
    assert "_is_deleted" in scd1
    array_child = invoice_dbt_artifacts[
        "models/silver/invoice/invoice_line_tax.sql"
    ]
    assert 'unique_key=["_source_record_key", "_element_index"]' in array_child


def test_runtime_sql_exposes_replay_correction_delete_lookback_and_backfill(
    client_dbt_artifacts,
):
    sql = client_dbt_artifacts["models/silver/client/client_pii.sql"]
    assert "accepted_input" in sql
    assert "replay_deduplicated" in sql
    assert "contradictory_replay_ties" in sql
    assert "DD-109 contradictory exact replay tie" in sql
    assert "corrected_events" in sql
    assert "_kairos_correction_rank = 1" in sql
    assert "kairos_runtime_lookback_floor" in sql
    assert "kairos_full_rebuild" in sql
    assert "kairos_backfill_start" in sql
    assert "when _cdc_operation = 'delete' then 1" in sql
    assert "when _cdc_operation = 'soft-delete' then 1" in sql


def test_release_data_is_the_single_runtime_authority(client_dbt_artifacts):
    release = client_dbt_artifacts["__release_data__"]
    runtime = _runtime(release, "client_pii")
    assert runtime["rule_id"] == "DD-109"
    assert runtime["merge_identity"] == ["_source_record_key"]
    assert runtime["total_order"] == [
        "_source_effective_at",
        "_source_updated_at",
        "_ingested_at",
        "_cdc_sequence",
        "_source_record_key",
    ]
    assert runtime["time_basis"] == "load-history"
    assert runtime["hard_delete"] == "tombstone"
    assert runtime["soft_delete"] == "apply-operation"
    assert runtime["delete_semantics"] == {
        "captured_cdc_delete": "hard-delete",
        "hard_delete_disposition": "tombstone",
        "soft_delete_signal": "normalized-operation:soft-delete",
        "soft_delete_disposition": "tombstone",
        "snapshot_absence_detection": "unsupported-fail-closed",
    }
    assert runtime["replay"] == "idempotent-merge"
    assert runtime["backfill"] == "range-replay-approved"
    assert runtime["correction"] == "replace-by-total-order"
    assert runtime["hash"]["contract_version"] == "1"
    assert runtime["hash"]["algorithm"] == "SHA-256"
    assert runtime["hash"]["rule_id"] == "DD-109-hash"


def test_fact_runtime_policy_is_exposed_with_time_and_replay_actions(
    invoice_dbt_artifacts,
):
    facts = invoice_dbt_artifacts["__release_data__"]["fact_runtime_semantics"]
    invoice = next(item for item in facts if item["resource_uri"] == str(INVOICE.Invoice))
    assert invoice["fact_type"] == "transaction"
    assert invoice["dimension_version_binding"] == "as-of-invoice-date"
    assert invoice["merge_identity"] == ["_source_record_key"]
    assert invoice["source_effective_at"] == "_source_effective_at"
    assert invoice["replay"] == "idempotent-merge"
    assert invoice["correction"] == "replace-by-total-order"
    assert invoice["late_arrival"] == "reconcile-with-lookback"
    assert invoice["rule_id"] == "DD-109-fact-runtime"
    silver_runtime = _runtime(
        invoice_dbt_artifacts["__release_data__"],
        "invoice",
    )
    assert "client_sk" in silver_runtime["hash"]["columns"]
    assert "invoice_sk" not in silver_runtime["hash"]["columns"]


def test_temporal_fk_modes_boundaries_cardinality_and_actions_are_generated(
    client_dbt_artifacts,
    invoice_dbt_artifacts,
):
    invoice_release = invoice_dbt_artifacts["__release_data__"]
    issued_to = _temporal(invoice_release, str(INVOICE.issuedTo))
    assert issued_to == {
        "model_name": "invoice",
        "property_uri": str(INVOICE.issuedTo),
        "mode": "as-of",
        "interval": "closed-open",
        "time_zone": "UTC",
        "precision": "microsecond",
        "cardinality": "exactly-one",
        "missing_action": "quarantine",
        "ambiguous_action": "fail",
        "late_parent_action": "restate",
        "participates_in_change_detection": True,
        "rule_id": "DD-109-temporal-fk",
        "evidence": [
            str(INVOICE.issuedTo),
            "https://kairos.cnext.eu/ext#silverForeignKeyTemporalMode",
        ],
    }
    belongs = _temporal(invoice_release, str(INVOICE.belongsToInvoice))
    assert belongs["mode"] == "none"
    assert belongs["cardinality"] == "exactly-one"
    current = _temporal(
        client_dbt_artifacts["__release_data__"],
        str(CLIENT.isIdentifiedBy),
    )
    assert current["mode"] == "current"
    assert current["cardinality"] == "zero-or-one"


def test_as_of_join_is_half_open_and_never_forced_to_current(
    invoice_dbt_artifacts,
):
    branch = invoice_dbt_artifacts[
        "models/silver/invoice/invoice__from_billing_pro__tbl_invoice.sql"
    ]
    assert "_business_valid_from" in branch
    assert "_business_valid_to" in branch
    assert "CAST([tbl_invoice].[_source_effective_at] AS DATETIME2(6))" in branch
    assert "[client_ref].[is_current] = 1" not in branch
    assert "_match_count" in branch
    assert branch.count("as _source_record_key") == 1
    assert any(
        path.endswith("__fk_quarantine.sql")
        for path in invoice_dbt_artifacts
    )


def test_schema_consumes_runtime_authority_for_tests(
    client_dbt_artifacts,
    invoice_dbt_artifacts,
):
    client_schema = yaml.safe_load(
        client_dbt_artifacts["models/silver/client/_client__models.yml"]
    )
    pii = next(item for item in client_schema["models"] if item["name"] == "client_pii")
    names = {
        next(iter(test))
        for test in pii["data_tests"]
        if isinstance(test, dict)
    }
    assert {
        "kairos_runtime_total_order",
        "kairos_runtime_replay_idempotent",
        "kairos_runtime_one_current",
        "kairos_runtime_half_open_intervals",
    } <= names

    invoice_schema = yaml.safe_load(
        invoice_dbt_artifacts["models/silver/invoice/_invoice__models.yml"]
    )
    invoice = next(item for item in invoice_schema["models"] if item["name"] == "invoice")
    temporal_tests = [
        test["kairos_temporal_fk_cardinality"]
        for test in invoice["data_tests"]
        if "kairos_temporal_fk_cardinality" in test
    ]
    assert any(item["mode"] == "as-of" for item in temporal_tests)


@pytest.mark.parametrize("adapter", ["fabric", "databricks"])
def test_runtime_materialization_is_adapter_specific_and_deterministic(
    client_ontology,
    adapter,
):
    first = _generate(client_ontology, "client", adapter=adapter)
    second = _generate(client_ontology, "client", adapter=adapter)
    assert first == second
    sql = first["models/silver/client/client_pii.sql"]
    assert "kairos_canonical_hash_v1" in sql
    if adapter == "fabric":
        assert "DATETIME2(6)" in sql
        assert "`" not in sql
        assert "CAST('DD-109 contradictory exact replay tie' AS INTEGER)" in sql
    else:
        assert " AS TIMESTAMP" in sql
        assert "DATETIME2(6)" not in sql
        assert "[client_pii" not in sql
        assert "RAISE_ERROR('DD-109 contradictory exact replay tie')" in sql
        project = yaml.safe_load(first["dbt_project.yml"])
        assert project["on-run-start"] == ["SET TIME ZONE 'UTC'"]
        macro = first["macros/kairos_canonical_hash_v1.sql"]
        assert "TO_UTC_TIMESTAMP" not in macro
        assert "CAST({{ expression }} AS TIMESTAMP)" in macro
    capabilities = {
        item["capability"]: item["disposition"]
        for item in first["__release_data__"]["capabilities"]
    }
    assert capabilities["merge-upsert"] == "supported"
    assert capabilities["window-functions"] == "supported"
    assert capabilities["canonical-sha256-hash"] == "supported"


def test_missing_incremental_fact_fails_closed(client_ontology):
    source, _, _ = client_ontology
    graph = Graph()
    graph += source
    graph.remove((CLIENT.ClientPII, EXT.incrementalPolicy, None))
    with pytest.raises(
        PolicyNormalizationError,
        match="history.incremental-policy-missing",
    ):
        _generate(client_ontology, "client", graph=graph)


def test_unknown_member_and_retry_actions_are_not_silent(invoice_ontology):
    source, _, _ = invoice_ontology
    graph = Graph()
    graph += source
    graph.set((INVOICE.issuedTo, EXT.silverForeignKeyMissingPolicy, Literal("unknown-member")))
    graph.set((INVOICE.issuedTo, EXT.silverForeignKeyAmbiguousPolicy, Literal("retry")))
    artifacts = _generate(invoice_ontology, "invoice", graph=graph)
    branch = artifacts[
        "models/silver/invoice/invoice__from_billing_pro__tbl_invoice.sql"
    ]
    assert "COALESCE(client_ref.client_sk, '__KAIROS_UNKNOWN__')" in branch
    assert any(
        path.endswith("__fk_quarantine.sql")
        for path in artifacts
    )
    action = _temporal(artifacts["__release_data__"], str(INVOICE.issuedTo))
    assert action["missing_action"] == "unknown-member"
    assert action["ambiguous_action"] == "retry"


def test_scd2_append_correction_fails_closed_with_actionable_dd109_error(
    client_ontology,
):
    source, _, _ = client_ontology
    graph = Graph()
    graph += source
    policy = next(graph.objects(CLIENT.ClientPII, EXT.incrementalPolicy))
    graph.set((policy, EXT.correctionPolicy, Literal("append-correction")))
    with pytest.raises(
        PolicyNormalizationError,
        match="history.scd2-append-correction-unsupported.*DD-109",
    ):
        _generate(client_ontology, "client", graph=graph)


def test_unsupported_physical_snapshot_hard_delete_fails_closed(client_ontology):
    source, _, _ = client_ontology
    graph = Graph()
    graph += source
    policy = next(graph.objects(CLIENT.ClientPII, EXT.incrementalPolicy))
    graph.set((policy, EXT.hardDeletePolicy, Literal("apply-operation")))
    with pytest.raises(
        PolicyNormalizationError,
        match="history.hard-delete-action-unsupported.*captured CDC",
    ):
        _generate(client_ontology, "client", graph=graph)


def test_hard_ignore_and_soft_tombstone_render_distinct_runtime_actions(
    client_ontology,
):
    source, _, _ = client_ontology
    graph = Graph()
    graph += source
    policy = next(graph.objects(CLIENT.ClientPII, EXT.incrementalPolicy))
    graph.set((policy, EXT.hardDeletePolicy, Literal("ignore")))
    graph.set((policy, EXT.softDeletePolicy, Literal("tombstone")))
    artifacts = _generate(client_ontology, "client", graph=graph)
    sql = artifacts["models/silver/client/client_pii.sql"]
    assert "_cdc_operation <> 'delete'" in sql
    assert "_cdc_operation <> 'soft-delete'" not in sql
    runtime = _runtime(artifacts["__release_data__"], "client_pii")
    assert runtime["delete_semantics"]["hard_delete_disposition"] == "ignore"
    assert runtime["delete_semantics"]["soft_delete_disposition"] == "tombstone"
