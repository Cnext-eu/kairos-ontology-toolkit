# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""ACME scenario coverage for executable DQ routing and review-only release facts."""


def test_client_dq_quarantine_is_explicit_and_normal_model_is_filtered(
    client_dbt_artifacts,
):
    input_path = "models/silver/client/client__dq_input.sql"
    accepted_path = "models/silver/client/client.sql"
    quarantine_path = "models/silver/client/client__dq_quarantine.sql"

    assert input_path in client_dbt_artifacts
    assert accepted_path in client_dbt_artifacts
    assert quarantine_path in client_dbt_artifacts
    assert "replay_deduplicated" in client_dbt_artifacts[input_path]
    assert "not exists" in client_dbt_artifacts[accepted_path]
    quarantine = client_dbt_artifacts[quarantine_path]
    assert "source_record_key" in quarantine
    assert "client.timeline-order" in quarantine
    assert "source_identity_ref" in quarantine
    assert "quarantined_at" in quarantine


def test_client_dq_emits_result_test_schema_and_review_metadata(
    client_dbt_artifacts,
):
    release = client_dbt_artifacts["__release_data__"]
    rule = next(
        item
        for item in release["dq_rules"]
        if item["rule_id"] == "client.timeline-order"
    )

    assert rule["category"] == "business"
    assert rule["action"] == "quarantine"
    assert rule["result_status"] == "not-evaluated"
    assert rule["result_artifact"] in client_dbt_artifacts
    assert rule["test_artifact"] in client_dbt_artifacts
    assert rule["quarantine_artifact"] in client_dbt_artifacts
    assert (
        "contracts/dq-runtime-result-contract.schema.json"
        in client_dbt_artifacts
    )
    assert release["mode"] == "review-only"
    assert release["release_ready"] is False
