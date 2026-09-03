# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-110 Silver physical-plan, renderer, parity, and boundary tests."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from rdflib import Graph

from kairos_ontology.core.projections.dbt import (
    bind_sources,
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from kairos_ontology.core.projections.dbt.materialize import _bounded_identifier
from kairos_ontology.core.projections.dbt.specs import (
    SchemaKind,
)
from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)
from kairos_ontology.core.projections.medallion_silver_projector import (
    SilverParityError,
    generate_silver_artifacts,
    validate_parity_manifest,
)
from tests.test_dbt_phases import TEMPLATE_DIR, _client_inputs


def _run(inputs=None):
    bound = bind_sources(inputs or _client_inputs())
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    return contract, shaped, plan, render_project(shaped, plan)


@pytest.mark.parametrize("adapter", ("fabric-warehouse", "databricks"))
def test_both_adapters_use_exact_shared_column_order_and_types(adapter):
    contract, shaped, plan, artifacts = _run(
        replace(
            _client_inputs(),
            target_platform=adapter,
            gold_extension=(_client_inputs().gold_extension if adapter == "fabric-warehouse" else None),
        )
    )
    assert contract.project.target_platform == adapter
    assert plan.silver is not None
    manifest = json.loads(artifacts[plan.silver.parity_artifact_path])
    assert manifest["status"] == "pass"

    specs = {model.identity.model_name: model for model in shaped.silver_models}
    for physical in plan.silver.models:
        assert [column.name for column in physical.columns] == [
            column.name for column in specs[physical.model_name].columns
        ]
        assert all(column.physical_type for column in physical.columns)
        assert all(column.canonical_type for column in physical.columns)


def test_schema_yaml_uses_spec_columns_physical_types_nullability_and_defaults():
    contract, shaped, _, _ = _run()
    target = next(
        model for model in shaped.silver_models if model.identity.model_name == "client_type"
    )
    changed_columns = tuple(
        (
            replace(
                column,
                nullable=False,
                default_expression="'UNKNOWN'",
            )
            if column.name == "type_label"
            else column
        )
        for column in target.columns
    )
    models = tuple(
        replace(model, columns=changed_columns) if model is target else model
        for model in shaped.silver_models
    )
    documents = tuple(
        (
            replace(
                document,
                models=tuple(
                    (
                        replace(
                            model,
                            columns=changed_columns,
                        )
                        if model.name == "client_type"
                        else model
                    )
                    for model in document.models
                ),
            )
            if document.kind is SchemaKind.SILVER
            else document
        )
        for document in shaped.schema_documents
    )
    changed = replace(
        shaped,
        silver_models=models,
        schema_documents=documents,
    )
    plan = plan_materialization(contract, changed)
    artifacts = render_project(changed, plan)
    schema = yaml.safe_load(artifacts["models/silver/client/_client__models.yml"])
    type_label = next(
        column
        for model in schema["models"]
        if model["name"] == "client_type"
        for column in model["columns"]
        if column["name"] == "type_label"
    )

    assert type_label["data_type"] == "VARCHAR(50)"
    assert type_label["meta"]["nullable"] == "false"
    assert type_label["meta"]["default"] == "'UNKNOWN'"
    ddl = artifacts[plan.silver.ddl_artifact_path]
    assert "type_label VARCHAR(50) DEFAULT 'UNKNOWN' NOT NULL" in ddl


def test_constraints_are_unenforced_collision_safe_and_adapter_bounded():
    _, _, plan, artifacts = _run()
    metadata = json.loads(artifacts[plan.silver.constraint_artifact_path])
    constraints = [
        constraint for model in metadata["models"] for constraint in model["constraints"]
    ]
    assert constraints
    assert all(constraint["enforced"] is False for constraint in constraints)
    assert "UNENFORCED" in artifacts[plan.silver.ddl_artifact_path]

    first = _bounded_identifier(
        "fabric-warehouse",
        "fk",
        "silver",
        "a" * 200,
        ("same-column",),
        "target-a",
    )
    second = _bounded_identifier(
        "fabric-warehouse",
        "fk",
        "silver",
        "a" * 200,
        ("same-column",),
        "target-b",
    )
    assert first != second
    assert len(first) <= 128
    assert first == _bounded_identifier(
        "fabric-warehouse",
        "fk",
        "silver",
        "a" * 200,
        ("same-column",),
        "target-a",
    )


def test_erd_and_parity_manifest_are_deterministic():
    *_, first = _run()
    *_, second = _run()
    for path in (
        "analyses/client/client-ddl.sql",
        "metadata/client-silver-constraints.json",
        "metadata/client-silver-parity.json",
        "docs/diagrams/client/client-erd.mmd",
    ):
        assert first[path] == second[path]


def test_deliberate_artifact_drift_blocks_parity():
    *_, artifacts = _run()
    manifest = artifacts["metadata/client-silver-parity.json"]
    drifted = dict(artifacts)
    drifted["analyses/client/client-ddl.sql"] += "-- drift\n"

    with pytest.raises(SilverParityError, match="hash drift"):
        validate_parity_manifest(manifest, drifted)


def test_standalone_silver_evidence_failure_is_actionable():
    graph = Graph()
    graph.parse(
        data="""
            @prefix ex: <https://example.test/domain#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            <https://example.test/domain> a owl:Ontology .
            ex:Entity a owl:Class ; rdfs:label "Entity" .
        """,
        format="turtle",
    )
    with pytest.raises(ValueError, match="ontology-only physical schema"):
        generate_dbt_artifacts(
            classes=[
                {
                    "uri": "https://example.test/domain#Entity",
                    "name": "Entity",
                    "label": "Entity",
                    "comment": "",
                }
            ],
            graph=graph,
            template_dir=TEMPLATE_DIR,
            namespace="https://example.test/domain#",
            ontology_name="domain",
            require_silver_evidence=True,
        )


def test_silver_projector_is_graph_free_render_only_facade():
    module = inspect.getmodule(generate_silver_artifacts)
    source = Path(module.__file__).read_text(encoding="utf-8")
    forbidden = (
        "from rdflib",
        "import rdflib",
        "Graph",
        "classify_foreign",
        "normalize_medallion_policy",
        "merge_ext_graph",
    )
    assert not any(value in source for value in forbidden)
    assert tuple(inspect.signature(generate_silver_artifacts).parameters) == (
        "models",
        "physical_plan",
        "rendered_artifacts",
        "schema_paths",
    )
