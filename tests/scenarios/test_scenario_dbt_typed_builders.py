# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""ACME semantic parity coverage for DD-110 gate 3b byte-free phases."""

from __future__ import annotations

import yaml


def _artifact(artifacts: dict[str, object], suffix: str) -> str:
    if suffix.startswith("/") and suffix.endswith(".sql"):
        evaluated_suffix = suffix.removesuffix(".sql") + "__dq_input.sql"
        evaluated = [
            value
            for key, value in artifacts.items()
            if key.endswith(evaluated_suffix) and isinstance(value, str)
        ]
        if evaluated:
            assert len(evaluated) == 1
            return evaluated[0]
    matches = [
        value for key, value in artifacts.items() if key.endswith(suffix) and isinstance(value, str)
    ]
    assert len(matches) == 1, f"Expected one {suffix!r}, found {len(matches)}"
    return matches[0]


def test_acme_client_invoice_logistics_artifacts_retain_semantics(
    client_dbt_artifacts,
    invoice_dbt_artifacts,
    logistics_dbt_artifacts,
):
    client_sql = _artifact(client_dbt_artifacts, "/client.sql")
    client_pii_sql = _artifact(client_dbt_artifacts, "/client_pii.sql")
    invoice_sql = _artifact(invoice_dbt_artifacts, "/invoice.sql")
    trade_party_sql = _artifact(logistics_dbt_artifacts, "/trade_party.sql")
    client_schema = yaml.safe_load(_artifact(client_dbt_artifacts, "__models.yml"))
    client_branch_sql = _artifact(
        client_dbt_artifacts,
        "client__from_admin_pulse__tbl_client__corporate_client.sql",
    )

    # DD-627: no inline `materialized=`; relies on dbt_project.yml cascade default.
    assert "materialized=" not in client_sql
    # DD-627 only drops the inline argument for non-runtime ENTITY/UNION models;
    # per-source SOURCE_BRANCH staging views still hardcode `materialized='view'`.
    assert "materialized='view'" in client_branch_sql
    assert "kairos_canonical_hash_v1" not in client_pii_sql
    assert "kairos_row_hash" not in client_pii_sql
    assert "union all" in invoice_sql.lower()
    assert "invoice_number" in invoice_sql
    assert "trade_party_sk" in trade_party_sql
    assert "_source_record_key" in trade_party_sql
    # DD-627: trade_party is a non-runtime UNION model, so it also drops the
    # inline `materialized=` argument in favor of the dbt_project.yml cascade.
    assert "materialized=" not in trade_party_sql
    assert client_schema["version"] == 2
    assert any(model["name"] == "client" for model in client_schema["models"])
