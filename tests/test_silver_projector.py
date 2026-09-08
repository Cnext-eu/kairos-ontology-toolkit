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
    SilverConstraintPhysicalPlan,
)
from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)
from kairos_ontology.core.projections.medallion_silver_projector import (
    SilverParityError,
    _render_erd,
    generate_master_erd,
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
            gold_extension=(
                _client_inputs().gold_extension if adapter == "fabric-warehouse" else None
            ),
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


_EXTERNAL_STUB = '    REGION {\n        string external "model from another domain"\n    }\n'
_CROSS_DOMAIN_URI = "https://acme.example/ontology/billing#inRegion"


def _plan_with_cross_domain_foreign_key():
    """The client plan plus one FK from ``client`` to a model no client binding emits."""
    *_, plan, _ = _run()
    silver = plan.silver
    client = next(model for model in silver.models if model.model_name == "client")
    foreign_key = SilverConstraintPhysicalPlan(
        name="fk_client_region",
        kind="foreign-key",
        columns=("region_sk",),
        referenced_model="region",
        referenced_columns=("region_sk",),
        temporal_mode="current",
        property_uri=_CROSS_DOMAIN_URI,
    )
    patched = replace(client, constraints=(*client.constraints, foreign_key))
    return replace(
        silver,
        models=tuple(patched if model is client else model for model in silver.models),
    )


def test_erd_draws_a_cross_domain_foreign_key_as_an_external_stub_and_edge():
    """#754: a FK to a model outside the plan used to vanish from the domain ERD."""
    erd = _render_erd(_plan_with_cross_domain_foreign_key())

    assert erd.count(_EXTERNAL_STUB) == 1
    assert f'    REGION ||--o{{ CLIENT : "{_CROSS_DOMAIN_URI} [temporal=current] [external]"' in erd
    in_domain = [line for line in erd.splitlines() if "CLIENT_TYPE ||--o{" in line]
    assert in_domain and all("[external]" not in line for line in in_domain)
    assert _render_erd(_plan_with_cross_domain_foreign_key()) == erd


def _write_domain(root: Path, domain: str, erd: str, models: list[dict]) -> None:
    diagram = root / "docs" / "diagrams" / domain / f"{domain}-erd.mmd"
    diagram.parent.mkdir(parents=True, exist_ok=True)
    diagram.write_text(erd, encoding="utf-8")
    metadata = root / "metadata" / f"{domain}-silver-constraints.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(json.dumps({"models": models}), encoding="utf-8")


def test_master_erd_replaces_an_external_stub_once_its_domain_is_emitted(tmp_path):
    """The master has the hub-wide inventory, so it draws the real entity and the resolved
    cross-domain edge exactly once -- the stub must not merge into the real entity."""
    _write_domain(
        tmp_path,
        "client",
        _render_erd(_plan_with_cross_domain_foreign_key()),
        [
            {
                "model_name": "client",
                "constraints": [
                    {
                        "kind": "foreign-key",
                        "referenced_model": "region",
                        "temporal_mode": "current",
                        "property_uri": _CROSS_DOMAIN_URI,
                    }
                ],
            }
        ],
    )

    client_only = generate_master_erd(tmp_path, hub_name="acme")
    assert client_only is not None
    assert client_only.count(_EXTERNAL_STUB.rstrip("\n")) == 1
    assert client_only.count(f"{_CROSS_DOMAIN_URI} [temporal=current] [external]") == 1

    billing_erd = "erDiagram\n    REGION {\n        VARCHAR_8000_ region_sk PK\n    }\n"
    _write_domain(tmp_path, "billing", billing_erd, [{"model_name": "region", "constraints": []}])

    both = generate_master_erd(tmp_path, hub_name="acme")
    assert both is not None
    assert "model from another domain" not in both
    # The master strips each domain body, so the first entity line may sit at column 0.
    assert both.count("REGION {") == 1
    assert both.count(f'REGION ||--o{{ CLIENT : "{_CROSS_DOMAIN_URI} [temporal=current]"') == 1
    edges = [line for line in both.splitlines() if "||--o{" in line]
    assert edges and all("[external]" not in line for line in edges)


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
