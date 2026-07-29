# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario parity for the shared DD-110 Silver authority."""

from __future__ import annotations

import json

import pytest
import yaml


@pytest.mark.parametrize(
    ("domain", "fixture_name"),
    (
        ("client", "client_dbt_artifacts"),
        ("invoice", "invoice_dbt_artifacts"),
        ("logistics", "logistics_dbt_artifacts"),
    ),
)
def test_scenario_emits_passing_parity_manifest(
    domain,
    fixture_name,
    request,
):
    artifacts = request.getfixturevalue(fixture_name)
    manifest = json.loads(artifacts[f"metadata/{domain}-silver-parity.json"])

    assert manifest["authority"] == "SilverModelSpec"
    assert manifest["status"] == "pass"
    assert manifest["errors"] == []
    assert manifest["models"]
    assert all(model["fields"] for model in manifest["models"])


def test_client_sql_yaml_and_ddl_have_identical_final_columns(client_dbt_artifacts):
    manifest = json.loads(client_dbt_artifacts["metadata/client-silver-parity.json"])
    schema = yaml.safe_load(client_dbt_artifacts["models/silver/client/_client__models.yml"])
    schema_columns = {
        model["name"]: [column["name"] for column in model["columns"]] for model in schema["models"]
    }
    ddl = client_dbt_artifacts["analyses/client/client-ddl.sql"]

    for model in manifest["models"]:
        if model["model_name"] not in schema_columns:
            continue
        expected = model["columns"]
        sql = client_dbt_artifacts[model["representations"]["dbt_sql"]["path"]]
        marker = json.dumps(expected, separators=(",", ":"))
        assert f"-- DD-110-COLUMNS: {marker}" in sql
        assert f"-- DD-110-COLUMNS: {marker}" in ddl
        assert schema_columns[model["model_name"]] == expected


def test_structural_fks_do_not_infer_runtime_links(invoice_dbt_artifacts):
    metadata = json.loads(invoice_dbt_artifacts["metadata/invoice-silver-constraints.json"])
    constraints = [
        constraint for model in metadata["models"] for constraint in model["constraints"]
    ]
    links = [link for model in metadata["models"] for link in model["relation_links"]]

    assert any(
        constraint["kind"] == "foreign-key"
        and constraint["temporal_mode"] in {"current", "as-of", "none"}
        for constraint in constraints
    )
    assert all(constraint["enforced"] is False for constraint in constraints)
    assert links == []


def test_erd_uses_only_emitted_models_and_temporal_annotations(
    invoice_dbt_artifacts,
):
    metadata = json.loads(invoice_dbt_artifacts["metadata/invoice-silver-constraints.json"])
    emitted = {model["model_name"].upper() for model in metadata["models"]}
    erd = invoice_dbt_artifacts["docs/diagrams/invoice/invoice-erd.mmd"]

    assert erd.startswith("erDiagram\n")
    assert "temporal=" in erd
    for line in erd.splitlines():
        if "||--o{" not in line:
            continue
        left, remainder = line.strip().split(" ||--o{ ", 1)
        right = remainder.split(" :", 1)[0]
        assert left in emitted
        assert right in emitted
