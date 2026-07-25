# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Logical-spec builder tests retained by DD-110 gate 3b."""

from __future__ import annotations

import dataclasses

import pytest

from kairos_ontology.core.projections.dbt.builders import (
    build_silver_model,
    build_silver_registry,
    freeze_value,
    outcome_from_context,
    schema_model_from_context,
)
from kairos_ontology.core.projections.dbt.gold_specs import (
    DimensionalGoldSpec,
    GoldTableSpec,
)
from kairos_ontology.core.projections.dbt.specs import (
    ColumnSpec,
    ForeignKeySpec,
    FrozenMapping,
    ModelIdentity,
    ModelOutcome,
    SchemaModelSpec,
    ScdSpec,
    SilverModelOutcome,
    SilverModelSpec,
    SilverRegistry,
    SilverModelKind,
)


@pytest.mark.parametrize(
    "record_type",
    [
        ColumnSpec,
        ForeignKeySpec,
        DimensionalGoldSpec,
        GoldTableSpec,
        ModelIdentity,
        SchemaModelSpec,
        ScdSpec,
        SilverModelOutcome,
        SilverModelSpec,
        SilverRegistry,
    ],
)
def test_logical_records_are_frozen_slotted_dataclasses(record_type):
    assert dataclasses.is_dataclass(record_type)
    assert record_type.__dataclass_params__.frozen is True
    assert "__slots__" in record_type.__dict__


def test_nested_template_values_are_deeply_immutable():
    frozen = freeze_value(
        {"relationships": {"to": "ref('client')", "fields": ["client_sk"]}}
    )
    assert isinstance(frozen, FrozenMapping)
    with pytest.raises(dataclasses.FrozenInstanceError):
        frozen.entries = ()  # type: ignore[misc]
    assert isinstance(frozen.entries[0][1], FrozenMapping)


def test_silver_builder_commits_structure_without_parallel_scd_authority():
    identity = ModelIdentity(
        class_name="Invoice",
        class_uri="https://example.test/Invoice",
        model_name="invoice",
        domain_name="invoice",
        schema_name="silver_invoice",
        artifact_path="models/silver/invoice/invoice.sql",
        outcome=ModelOutcome.GENERATED,
    )
    spec = build_silver_model(
        identity=identity,
        kind=SilverModelKind.ENTITY,
        columns=[
            {"expression": "InvoiceId", "target_name": "invoice_id"},
            {
                "expression": "client.client_sk",
                "target_name": "client_sk",
                "include_in_change_detection": False,
            },
        ],
        sources=[
            {
                "source_name": "billing_pro",
                "table_name": "invoice",
                "alias": "invoice",
            }
        ],
        joins=[
            {
                "type": "left",
                "ref": "{{ ref('client') }}",
                "alias": "client",
                "condition": "invoice.ClientId = client.client_id",
                "fk_column": "client_sk",
            }
        ],
        materialization="incremental",
        unique_key=["invoice_sk", "valid_from"],
    )

    assert spec.columns[1].include_in_change_detection is False
    assert spec.sources[0].source_name == "billing_pro"
    assert spec.joins[0].fk_column == "client_sk"
    assert spec.materialization_intent.kind == "incremental"
    assert spec.materialization_intent.unique_key == ("invoice_sk", "valid_from")
    assert not hasattr(spec, "scd")


def test_schema_builder_freezes_tests_and_preserves_order():
    source = {
        "name": "client",
        "description": "Client",
        "meta": {"ontology_class": "Client"},
        "columns": [
            {
                "name": "client_sk",
                "description": "Surrogate key",
                "meta": {"is_pk": "true"},
                "tests": [
                    "not_null",
                    {"unique": {"config": {"where": "is_current = 1"}}},
                ],
            },
            {
                "name": "country_code",
                "description": "Country",
                "meta": {},
                "tests": [{"accepted_values": {"values": ["BE", "NL"]}}],
            },
        ],
        "grain_columns": ["_source_system", "client_id"],
        "source_identity_columns": ["_source_system", "_source_record_key"],
        "grain_where": "is_current = 1",
    }
    spec = schema_model_from_context(source)
    source["columns"].reverse()

    assert tuple(column.name for column in spec.columns) == ("client_sk", "country_code")
    assert len(spec.columns[0].tests) == 2
    assert spec.grain_columns == ("_source_system", "client_id")
    assert spec.grain_where == "is_current = 1"


def _outcome(
    class_name: str,
    class_uri: str,
    *,
    model_name: str = "",
    columns: tuple[str, ...] = (),
    skipped: bool = False,
    reason: str | None = None,
) -> SilverModelOutcome:
    return outcome_from_context(
        {
            "class_name": class_name,
            "class_uri": class_uri,
            "model_name": model_name,
            "column_names": list(columns),
            "skipped": skipped,
            "skip_reason": reason,
        }
    )


def test_model_outcomes_and_registry_are_deterministic():
    generated = _outcome(
        "Client",
        "https://example.test/Client",
        model_name="client",
        columns=("client_sk", "client_id"),
    )
    skipped = _outcome(
        "Prospect",
        "https://example.test/Prospect",
        skipped=True,
        reason="No bronze mapping found",
    )
    folded = _outcome(
        "CorporateClient",
        "https://example.test/CorporateClient",
        skipped=True,
        reason="S3 discriminator subclass of Client",
    )
    relations = (("https://example.test/Client", "https://example.test/Party"),)

    registry = build_silver_registry((skipped, generated, folded), relations)
    reversed_registry = build_silver_registry((folded, generated, skipped), relations)

    assert skipped.identity.outcome is ModelOutcome.SKIPPED
    assert folded.identity.outcome is ModelOutcome.FOLDED
    assert registry == reversed_registry
    assert registry.names == (
        ("https://example.test/Client", "client"),
        ("https://example.test/Party", "client"),
    )
    assert registry.columns == (("client", frozenset({"client_sk", "client_id"})),)


def test_registry_records_ambiguous_parents_in_sorted_order():
    outcomes = (
        _outcome("Order", "urn:Order", model_name="order"),
        _outcome("Return", "urn:Return", model_name="return"),
    )
    registry = build_silver_registry(
        outcomes,
        (("urn:Return", "urn:Transaction"), ("urn:Order", "urn:Transaction")),
    )
    assert registry.ambiguous_parents == (
        ("urn:Transaction", ("order", "return")),
    )
    assert ("urn:Transaction", "order") not in registry.names


def test_registry_uses_actual_materialized_columns_and_version():
    outcome = _outcome(
        "Client",
        "urn:Client",
        model_name="client",
        columns=("stale_column",),
    )
    model = SilverModelSpec(
        identity=outcome.identity,
        kind=SilverModelKind.ENTITY,
        columns=(ColumnSpec("client_id"), ColumnSpec("client_name")),
    )

    registry = build_silver_registry(
        (outcome,),
        (),
        ontology_version="2.0",
        materialized_models=(model,),
    )

    assert registry.columns == (
        ("client", frozenset({"client_id", "client_name"})),
    )
    assert registry.versions == (("client", "2.0"),)
