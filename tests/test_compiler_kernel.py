# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the stateless v5 compiler kernel."""

from __future__ import annotations

import shutil
import textwrap
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from pathlib import Path
from unittest.mock import patch

import pytest
from rdflib import Graph

from kairos_ontology.core.compiler import (
    CompileMode,
    build_compile_plan,
    compile_domain,
    compile_plan_result,
    render_compile_plan,
)

from discovery_fixtures import write_minimal_discovery_artifact


def _hub(tmp_path: Path, *, broken_column: bool = False) -> Path:
    ontology_dir = tmp_path / "model" / "ontologies"
    source_dir = tmp_path / "integration" / "sources" / "crm"
    binding_dir = tmp_path / "integration" / "bindings"
    ontology_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    binding_dir.mkdir(parents=True)
    (tmp_path / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    (ontology_dir / "party.ttl").write_text(
        textwrap.dedent("""
            @prefix party: <https://example.test/party#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
            party:Customer a owl:Class ; rdfs:label "Customer" .
            party:customer_id a owl:DatatypeProperty ;
              rdfs:domain party:Customer ; rdfs:range xsd:string .
            party:customerName a owl:DatatypeProperty ;
              rdfs:domain party:Customer ; rdfs:range xsd:string .
            """).strip(),
        encoding="utf-8",
    )
    (source_dir / "crm.vocabulary.ttl").write_text(
        textwrap.dedent("""
            @prefix src: <https://example.test/source#> .
            @prefix kb: <https://kairos.cnext.eu/bronze#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            src:crm a kb:SourceSystem ; rdfs:label "crm" ;
              kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
            src:customers a kb:SourceTable ; kb:sourceSystem src:crm ;
              kb:tableName "customers" ; kb:primaryKeyColumns "customer_id" .
            src:id a kb:SourceColumn ; kb:sourceTable src:customers ;
              kb:columnName "customer_id" ; kb:dataType "varchar(50)" ;
              kb:nullable "false"^^xsd:boolean .
            src:name a kb:SourceColumn ; kb:sourceTable src:customers ;
              kb:columnName "customer_name" ; kb:dataType "varchar(200)" ;
              kb:nullable "true"^^xsd:boolean .
            """).strip(),
        encoding="utf-8",
    )
    expression = "missing" if broken_column else "customer_name"
    (binding_dir / "customer.binding.yaml").write_text(
        textwrap.dedent(f"""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-customer
              domain: party
            source:
              relation: crm.customers
            target:
              class: party:Customer
            grain:
              columns: [customer_id]
            identity:
              strategy: source-natural
              sourceKey: [customer_id]
            load:
              mode: full-refresh
            fields:
              - property: party:customer_id
                expression: customer_id
              - property: party:customerName
                expression: {expression}
            """).strip(),
        encoding="utf-8",
    )
    write_minimal_discovery_artifact(tmp_path)
    return tmp_path


def test_compile_domain_check_explain_and_render_are_deterministic(tmp_path):
    hub = _hub(tmp_path)
    first = compile_domain(hub, "party", CompileMode.EXPLAIN)
    second = compile_domain(hub, "party", CompileMode.EXPLAIN)
    assert first.succeeded
    assert first.artifacts == second.artifacts
    assert first.provenance_hash == second.provenance_hash
    assert first.explain is not None
    assert first.explain.entities[0].grain == ("customer_id",)
    assert "models/silver/party/customer.sql" in first.artifact_dict()


def test_compile_plan_is_immutable_typed_and_graph_free(tmp_path):
    plan = build_compile_plan(_hub(tmp_path), "party")

    with pytest.raises(FrozenInstanceError):
        plan.blocked = True
    assert plan.normalized_contract is not None
    assert plan.shaped_project is not None
    assert plan.silver_registry is plan.shaped_project.silver_registry
    assert dict(plan.silver_registry.names) == {"https://example.test/party#Customer": "customer"}
    assert "customer_name" in dict(plan.silver_registry.columns)["customer"]
    assert plan.materialization_plan is not None
    assert plan.bindings == tuple(entity.binding for entity in plan.entities)

    def values(value):
        if isinstance(value, Graph):
            raise AssertionError("compile plan retained an RDF graph")
        if is_dataclass(value):
            for item in fields(value):
                yield from values(getattr(value, item.name))
        elif isinstance(value, (tuple, frozenset)):
            for item in value:
                yield from values(item)

    tuple(values(plan))


def test_compile_plan_identity_and_provenance_are_deterministic(tmp_path):
    hub = _hub(tmp_path)
    first = build_compile_plan(hub, "party")
    second = build_compile_plan(hub, "party")

    assert first == second
    assert first.provenance_hash == second.provenance_hash
    assert first.scope == second.scope
    assert first.artifact_paths == second.artifact_paths


def test_check_explain_emit_views_reuse_one_plan_without_resolution(tmp_path):
    plan = build_compile_plan(_hub(tmp_path), "party")

    with patch(
        "kairos_ontology.core.compiler.kernel.build_compile_plan",
        side_effect=AssertionError("plan must not be rebuilt"),
    ):
        results = tuple(
            compile_plan_result(plan, mode)
            for mode in (CompileMode.CHECK, CompileMode.EXPLAIN, CompileMode.EMIT)
        )

    assert all(result.plan is plan for result in results)
    assert all(result.provenance_hash == plan.provenance_hash for result in results)
    assert results[0].artifacts == results[1].artifacts == ()
    assert render_compile_plan(plan) == results[2].artifacts


def test_full_refresh_regression_does_not_enable_incremental_runtime(tmp_path):
    result = compile_domain(_hub(tmp_path), "party")

    assert result.succeeded
    sql = result.artifact_dict()["models/silver/party/customer.sql"].lower()
    assert "dd-109 scd" not in sql
    assert "materialized='table'" in sql


def test_compile_domain_collects_binding_error_without_writing(tmp_path):
    result = compile_domain(_hub(tmp_path, broken_column=True), "party")
    assert not result.succeeded
    assert not result.artifacts
    assert {item.code for item in result.diagnostics.items} == {"safety.column-unresolved"}


def test_missing_scope_is_a_diagnostic(tmp_path):
    result = compile_domain(tmp_path, "missing")
    assert not result.succeeded
    assert result.diagnostics.items[0].code == "scope.no-bindings-authored"


def test_invalid_entity_is_blocked_while_safe_entity_still_plans(tmp_path):
    scenario = Path(__file__).parent / "scenarios" / "v5-hub"
    hub = tmp_path / "hub"
    shutil.copytree(scenario, hub)
    customer = hub / "integration" / "bindings" / "customer.binding.yaml"
    customer.write_text(
        customer.read_text(encoding="utf-8").replace(
            "column: customer_name", "column: missing_name"
        ),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert "models/silver/party/country.sql" in result.artifact_dict()
    assert "models/silver/party/customer.sql" not in result.artifact_dict()
    blocked = {item.name: item.blocked for item in result.explain.entities}
    assert blocked == {"crm-country": False, "crm-customer": True}
    assert result.plan.blocked
    assert {entity.binding.name for entity in result.plan.entities if entity.blocked} == {
        "crm-customer"
    }
    assert all(
        "customer.sql" not in path
        for entity in result.plan.entities
        if entity.blocked
        for path in entity.artifact_paths
    )


def test_policy_normalization_error_preserves_its_own_code(tmp_path):
    """#337: a ``PolicyNormalizationError`` raised while normalizing one binding (e.g. the
    DD-108 ``identity.authored-key-not-supplied`` rule) must surface under its own specific
    code, not get flattened into the generic ``safety.type-incompatible`` by the blanket
    ``except Exception`` in the per-binding compile loop. That blanket handler must still
    catch genuinely-unexpected exceptions, so this only asserts the more specific
    ``PolicyNormalizationError`` branch is tried first.
    """
    from kairos_ontology.core.projections.dbt.policy_normalize import PolicyNormalizationError

    hub = _hub(tmp_path)

    def _boom(*_args, **_kwargs):
        raise PolicyNormalizationError(
            "identity.authored-key-not-supplied",
            "authored naturalKey identity OUTPUT column(s) must be explicitly materialized "
            "as a mapped fields: entry or an authored technicalFields: entry (DD-139) on "
            "'customer'; missing output column(s): gc_pk. Output column names are derived "
            "from source column names via snake_case conversion (e.g. 'OrderNo' → 'order_no').",
            rule_id="DD-108-business-identity",
            resource_uri="https://example.test/party#Customer",
        )

    with patch("kairos_ontology.core.compiler.kernel.normalize_contract", side_effect=_boom):
        result = compile_domain(hub, "party")

    assert not result.succeeded
    codes = {item.code for item in result.diagnostics.items}
    assert "identity.authored-key-not-supplied" in codes
    assert "safety.type-incompatible" not in codes
    diagnostic = next(
        item
        for item in result.diagnostics.items
        if item.code == "identity.authored-key-not-supplied"
    )
    assert diagnostic.rule_id == "DD-108-business-identity"
    assert "gc_pk" in diagnostic.message


def test_unsupported_adapter_fails_closed(tmp_path):
    hub = _hub(tmp_path)
    (hub / "kairos.yaml").write_text("adapter: unknown\n", encoding="utf-8")
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert result.diagnostics.items[0].code == "safety.adapter-unsupported"


def test_empty_selected_domain_is_non_emittable(tmp_path):
    hub = _hub(tmp_path)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace("domain: party", "domain: other"),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert not result.can_emit
    assert result.diagnostics.items[0].code == "scope.no-bindings-authored"


def test_all_malformed_selected_bindings_are_non_emittable(tmp_path):
    hub = _hub(tmp_path)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text("metadata:\n  domain: party\nunknown: rejected\n", encoding="utf-8")
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert not result.can_emit
    assert not result.artifacts


def test_project_render_failure_is_non_emittable_with_blocked_entity(tmp_path):
    plan = build_compile_plan(_hub(tmp_path), "party")
    entity = plan.entities[0]
    plan = replace(
        plan,
        entities=(replace(entity, blocked=True), entity),
        blocked=True,
    )

    with patch(
        "kairos_ontology.core.compiler.kernel.render_canonical_project",
        side_effect=ValueError("renderer rejected plan"),
    ):
        result = compile_plan_result(plan, CompileMode.EMIT)

    assert "compiler.render-failed" in {item.code for item in result.diagnostics.items}
    assert not result.can_emit
    assert not result.artifacts


def test_invalid_unrelated_domain_binding_is_ignored(tmp_path):
    hub = _hub(tmp_path)
    unrelated_source = hub / "integration" / "sources" / "unrelated.ttl"
    unrelated_source.write_text(
        "@prefix ex: <https://example.test/source#> .\n"
        "@prefix kb: <https://kairos.cnext.eu/bronze#> .\n"
        'ex:system a kb:SourceSystem ; kb:systemName "other" .\n',
        encoding="utf-8",
    )
    other = hub / "integration" / "bindings" / "other.binding.yaml"
    other.write_text(
        "metadata:\n  domain: other\nunknown: rejected-in-v5\n",
        encoding="utf-8",
    )
    first = compile_domain(hub, "party")
    other.write_text(
        "metadata:\n  domain: other\nunknown: changed-but-unrelated\n",
        encoding="utf-8",
    )
    unrelated_source.write_text(
        unrelated_source.read_text(encoding="utf-8") + "# changed\n",
        encoding="utf-8",
    )
    second = compile_domain(hub, "party")
    assert first.succeeded and second.succeeded
    assert first.provenance_hash == second.provenance_hash
    assert all("other.binding.yaml" not in path for path in first.explain.binding_paths)


def test_property_domain_mismatch_is_blocked(tmp_path):
    hub = tmp_path / "hub"
    shutil.copytree(Path(__file__).parent / "scenarios" / "v5-hub", hub)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace("party:customer_name", "party:country_name"),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert "binding.property-domain-incompatible" in {
        item.code for item in result.diagnostics.items
    }


def test_unsupported_ambiguous_parent_first_is_blocked(tmp_path):
    hub = tmp_path / "hub"
    shutil.copytree(Path(__file__).parent / "scenarios" / "v5-hub", hub)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "ambiguousParent: error", "ambiguousParent: first"
        ),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert "safety.adapter-unsupported" in {item.code for item in result.diagnostics.items}


@pytest.mark.parametrize("side", ["local", "foreign"])
def test_relationship_join_columns_must_resolve(tmp_path, side):
    scenario = Path(__file__).parent / "scenarios" / "v5-hub"
    hub = tmp_path / "hub"
    shutil.copytree(scenario, hub)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            f"{side}: {'country_code' if side == 'local' else 'code'}",
            f"{side}: missing",
        ),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert "safety.column-unresolved" in {item.code for item in result.diagnostics.items}


def _add_source_columns(hub: Path, *columns: tuple[str, str]) -> None:
    source = hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
    additions = "\n".join(
        (
            f"src:{name} a kb:SourceColumn ; kb:sourceTable src:customers ; "
            f'kb:columnName "{name}" ; kb:dataType "{data_type}" ; '
            'kb:nullable "false"^^xsd:boolean .'
        )
        for name, data_type in columns
    )
    source.write_text(source.read_text(encoding="utf-8") + "\n" + additions, encoding="utf-8")


@pytest.mark.parametrize(("scd", "correction"), [(1, "overwrite"), (2, "new-version")])
def test_complete_incremental_binding_uses_existing_dd109_runtime(tmp_path, scd, correction):
    hub = _hub(tmp_path)
    _add_source_columns(
        hub,
        ("operation", "varchar(1)"),
        ("source_updated_at", "timestamp"),
        ("effective_at", "timestamp"),
        ("ingested_at", "timestamp"),
        ("sequence_number", "bigint"),
    )
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    text = binding.read_text(encoding="utf-8")
    text = text.replace(
        "load:\n  mode: full-refresh",
        textwrap.dedent(f"""\
        load:
          mode: incremental
          scd: {scd}
          incremental:
            mergeIdentity: [customer_id]
            canonicalHashInputs: [customer_id, customer_name]
            cdcOperation:
              column: operation
              insertValues: [I]
              updateValues: [U]
              deleteValues: [D]
            sourceUpdatedAt: source_updated_at
            businessEffectiveAt: effective_at
            ingestedAt: ingested_at
            totalOrder: [sequence_number]
            lookback: {{value: 2, unit: days}}
            delete: soft-delete
            lateArrival: accept
            correction: {correction}
            replay: idempotent
            backfill: merge
            schemaEvolution: append-compatible"""),
    )
    binding.write_text(text, encoding="utf-8")

    result = compile_domain(hub, "party")

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    sql = result.artifact_dict()["models/silver/party/customer.sql"].lower()
    assert f"dd-109 scd{scd} runtime" in sql
    assert "kairos_canonical_hash_v1" in sql


def test_contracted_dbt_model_compiles_as_virtual_ref_source(tmp_path):
    hub = _hub(tmp_path)
    models = hub / "integration" / "transforms" / "dbt" / "models"
    models.mkdir(parents=True)
    (models / "customer_stage.sql").write_text(
        "select customer_id, customer_name from source_rows\n", encoding="utf-8"
    )
    (models / "schema.yml").write_text(
        textwrap.dedent("""\
        version: 2
        models:
          - name: customer_stage
            config:
              contract:
                enforced: true
            meta:
              kairos:
                grain: one row per customer
                grain_key: [customer_id]
                virtual_source_iri: https://example.test/virtual/customer-stage
                supported_adapters: [fabric]
            columns:
              - {name: customer_id, data_type: string, data_tests: [not_null]}
              - {name: customer_name, data_type: string}
        """),
        encoding="utf-8",
    )
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    text = binding.read_text(encoding="utf-8").replace(
        "source:\n  relation: crm.customers",
        textwrap.dedent("""\
        source:
          dbtModel:
            name: customer_stage
            sqlPath: integration/transforms/dbt/models/customer_stage.sql
            contractPath: integration/transforms/dbt/models/schema.yml"""),
    )
    binding.write_text(text, encoding="utf-8")

    result = compile_domain(hub, "party")

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()
    sql = artifacts["models/silver/party/customer.sql"]
    assert "ref('customer_stage')" in sql
    assert "source('dbt'" not in sql
    # A lone contracted model is not a conformance group, so no source branches.
    assert not [path for path in artifacts if "__from_" in path]
    # The managed virtual source is never re-declared as a raw dbt source.
    assert "models/silver/_dbt__sources.yml" not in artifacts


def _write_contracted_models(hub: Path, names: list[str]) -> None:
    """Write ``names`` as contracted dbt models sharing one properties document."""
    models = hub / "integration" / "transforms" / "dbt" / "models"
    models.mkdir(parents=True, exist_ok=True)
    entries = []
    for name in names:
        (models / f"{name}.sql").write_text(
            "select customer_id, customer_name from source_rows\n", encoding="utf-8"
        )
        entries.append(
            f"  - name: {name}\n"
            "    config:\n"
            "      contract:\n"
            "        enforced: true\n"
            "    meta:\n"
            "      kairos:\n"
            "        grain: one row per customer\n"
            "        grain_key: [customer_id]\n"
            f"        virtual_source_iri: https://example.test/virtual/{name}\n"
            "        supported_adapters: [fabric]\n"
            "    columns:\n"
            "      - {name: customer_id, data_type: string, data_tests: [not_null]}\n"
            "      - {name: customer_name, data_type: string}\n"
        )
    (models / "schema.yml").write_text("version: 2\nmodels:\n" + "".join(entries), encoding="utf-8")


def _conformance_block(precedence: int, union_mode: str) -> str:
    union_policy = (
        "    mode: deduplicate\n"
        "    deduplicateBy: [customer_id]\n"
        "    orderBy: [{column: customer_id, direction: ascending}]\n"
        if union_mode == "deduplicate"
        else "    mode: union-all\n"
    )
    return (
        "conformance:\n"
        "  group: party-customer\n"
        f"  sourcePrecedence: {precedence}\n"
        "  conflict: prefer-precedence\n"
        "  union:\n"
    ) + union_policy


def _dbt_binding_text(binding_name: str, model_name: str, conformance: str) -> str:
    return (
        textwrap.dedent(f"""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: {binding_name}
              domain: party
            source:
              dbtModel:
                name: {model_name}
                sqlPath: integration/transforms/dbt/models/{model_name}.sql
                contractPath: integration/transforms/dbt/models/schema.yml
            target:
              class: party:Customer
            grain:
              columns: [customer_id]
            identity:
              strategy: source-natural
              sourceKey: [customer_id]
            load:
              mode: full-refresh
            fields:
              - property: party:customer_id
                expression: customer_id
              - property: party:customerName
                expression: customer_name
            """).strip()
        + "\n"
        + conformance
    )


def _dbt_conformance_hub(tmp_path: Path, models: list[str], union_mode: str) -> Path:
    """Hub whose only bindings are ``models`` contracted dbt sources in one group."""
    hub = _hub(tmp_path)
    _write_contracted_models(hub, models)
    binding_dir = hub / "integration" / "bindings"
    (binding_dir / "customer.binding.yaml").unlink()
    for precedence, model in enumerate(models, start=1):
        (binding_dir / f"{model}.binding.yaml").write_text(
            _dbt_binding_text(
                f"{model}-customer", model, _conformance_block(precedence, union_mode)
            ),
            encoding="utf-8",
        )
    return hub


@pytest.mark.parametrize("union_mode", ["union-all", "deduplicate"])
def test_conformance_over_contracted_dbt_models_emits_one_branch_per_model(tmp_path, union_mode):
    """Issue #284: N contracted dbt models in one group must not collapse to one."""
    models = ["crm_customer_stage", "erp_customer_stage"]
    hub = _dbt_conformance_hub(tmp_path, models, union_mode)

    result = compile_domain(hub, "party")

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()
    assert sorted(path for path in artifacts if "__from_" in path) == [
        f"models/silver/party/customer__from_dbt__{model}.sql" for model in models
    ]
    for model in models:
        branch = artifacts[f"models/silver/party/customer__from_dbt__{model}.sql"]
        assert f"ref('{model}')" in branch
        assert "source('dbt'" not in branch
        assert "'dbt' as _source_system" in branch
    assert "models/silver/_dbt__sources.yml" not in artifacts
    union_sql = artifacts["models/silver/party/customer.sql"]
    assert "union all" in union_sql.lower()
    for model in models:
        assert f"ref('customer__from_dbt__{model}')" in union_sql


def test_conformance_over_three_contracted_dbt_models(tmp_path):
    """The N-way path (issue #284 reports eight contributors), not just N=2."""
    models = ["crm_customer_stage", "erp_customer_stage", "web_customer_stage"]
    hub = _dbt_conformance_hub(tmp_path, models, "union-all")

    result = compile_domain(hub, "party")

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()
    assert sorted(path for path in artifacts if "__from_" in path) == [
        f"models/silver/party/customer__from_dbt__{model}.sql" for model in models
    ]
    union_sql = artifacts["models/silver/party/customer.sql"]
    assert union_sql.lower().count("union all") == len(models) - 1


def test_conformance_mixes_relation_and_contracted_dbt_model_sources(tmp_path):
    """A dbt-model contributor does not perturb a relation contributor's branch name."""
    hub = _hub(tmp_path)
    _write_contracted_models(hub, ["erp_customer_stage"])
    binding_dir = hub / "integration" / "bindings"
    crm_binding = binding_dir / "customer.binding.yaml"
    crm_binding.write_text(
        crm_binding.read_text(encoding="utf-8") + "\n" + _conformance_block(1, "union-all"),
        encoding="utf-8",
    )
    (binding_dir / "erp_customer_stage.binding.yaml").write_text(
        _dbt_binding_text("erp-customer", "erp_customer_stage", _conformance_block(2, "union-all")),
        encoding="utf-8",
    )

    result = compile_domain(hub, "party")

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()
    assert sorted(path for path in artifacts if "__from_" in path) == [
        "models/silver/party/customer__from_crm__customers.sql",
        "models/silver/party/customer__from_dbt__erp_customer_stage.sql",
    ]
    relation_branch = artifacts["models/silver/party/customer__from_crm__customers.sql"]
    assert "source('crm', 'customers')" in relation_branch
    assert "'crm' as _source_system" in relation_branch
    assert "models/silver/_dbt__sources.yml" not in artifacts


@pytest.mark.parametrize("union_mode", ["union-all", "deduplicate"])
def test_explicit_conformance_uses_existing_union_renderer(tmp_path, union_mode):
    hub = _hub(tmp_path)
    crm_source = hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
    erp_dir = hub / "integration" / "sources" / "erp"
    erp_dir.mkdir()
    erp_text = (
        crm_source.read_text(encoding="utf-8")
        .replace("src:crm", "src:erp")
        .replace('rdfs:label "crm"', 'rdfs:label "erp"')
        .replace("src:customers", "src:erp_customers")
        .replace('kb:tableName "customers"', 'kb:tableName "erp_customers"')
    )
    (erp_dir / "erp.vocabulary.ttl").write_text(erp_text, encoding="utf-8")
    binding_dir = hub / "integration" / "bindings"
    crm_binding = binding_dir / "customer.binding.yaml"
    union_policy = (
        "    mode: deduplicate\n"
        "    deduplicateBy: [customer_id]\n"
        "    orderBy: [{column: customer_id, direction: ascending}]"
        if union_mode == "deduplicate"
        else "    mode: union-all"
    )
    conformance = (
        textwrap.dedent("""\
    conformance:
      group: party-customer
      sourcePrecedence: 1
      conflict: prefer-precedence
      union:
    """)
        + union_policy
        + "\n"
    )
    crm_binding.write_text(
        crm_binding.read_text(encoding="utf-8") + "\n" + conformance,
        encoding="utf-8",
    )
    erp_binding = (
        crm_binding.read_text(encoding="utf-8")
        .replace("crm-customer", "erp-customer")
        .replace("crm.customers", "erp.erp_customers")
        .replace("sourcePrecedence: 1", "sourcePrecedence: 2")
    )
    (binding_dir / "erp-customer.binding.yaml").write_text(erp_binding, encoding="utf-8")

    result = compile_domain(hub, "party")

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()
    union_sql = artifacts["models/silver/party/customer.sql"]
    assert "union all" in union_sql.lower()
    if union_mode == "deduplicate":
        assert "row_number() over" in union_sql.lower()


# ------------------------------------------------------------------------------------------
# #343: ``_binding_safety_diagnostics`` checks ``technicalFields:`` for duplicate source
# columns and duplicate output names, but had no equivalent check over ``fields:``. Two
# ``fields:`` entries resolving to the same property -- or producing the same output column
# name -- were accepted silently, and ``semantic_outputs`` (built with ``setdefault`` in
# ``_technical_field_safety_diagnostics``) quietly discarded the second entry instead of
# reporting the collision. Dormant only because today's column matcher requires exact name
# equality, so nothing currently authors two ``fields:`` entries for one property.
# ------------------------------------------------------------------------------------------
def test_duplicate_fields_entry_for_same_property_is_rejected(tmp_path):
    hub = _hub(tmp_path)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8")
        + "\n  - property: party:customerName\n    expression: customer_name\n",
        encoding="utf-8",
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    codes = {item.code for item in result.diagnostics.items}
    assert "field.duplicate-property" in codes, [item.render() for item in result.diagnostics.items]


def test_fields_entries_with_colliding_output_columns_are_rejected(tmp_path):
    """Two *different* properties whose local names normalize to the same output column.

    ``party:customerName`` and a newly authored ``party:customer_name`` are distinct
    property URIs, but ``camel_to_snake`` normalizes both to the ``customer_name`` output
    column -- the synthetic case a future name-relaxing column matcher could produce for
    real, and which ``field.duplicate-property`` alone (a same-URI check) cannot catch.
    """
    hub = _hub(tmp_path)
    ontology = hub / "model" / "ontologies" / "party.ttl"
    ontology.write_text(
        ontology.read_text(encoding="utf-8")
        + "\nparty:customer_name a owl:DatatypeProperty ;\n"
        "  rdfs:domain party:Customer ; rdfs:range xsd:string .\n",
        encoding="utf-8",
    )
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8")
        + "\n  - property: party:customer_name\n    expression: customer_name\n",
        encoding="utf-8",
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    codes = {item.code for item in result.diagnostics.items}
    assert "field.output-collision" in codes, [item.render() for item in result.diagnostics.items]
    # Distinct property URIs: this must not also fire the same-property duplicate check.
    assert "field.duplicate-property" not in codes


def test_single_fields_entry_per_property_is_unaffected(tmp_path):
    """The overwhelming common case -- one ``fields:`` entry per property -- stays green."""
    result = compile_domain(_hub(tmp_path), "party")

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    codes = {item.code for item in result.diagnostics.items}
    assert "field.duplicate-property" not in codes
    assert "field.output-collision" not in codes
