# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contracted dbt models' physical ``source()`` declarations (#584) and seed refs (#586a)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.compiler import CompileMode, compile_domain, load_entity_binding
from kairos_ontology.core.compiler.kernel import _dbt_dependency_closures
from kairos_ontology.core.compiler.scope import BuildScope, ProvenanceInput

from .test_compiler_kernel import _hub


def _contract_text(
    name: str,
    *,
    target_class: str = "https://example.test/party#Customer",
    grain_key: str = "customer_id",
    columns: str = (
        "      - {name: customer_id, data_type: string, data_tests: [not_null]}\n"
        "      - {name: customer_name, data_type: string}\n"
    ),
) -> str:
    return (
        textwrap.dedent(f"""\
        version: 2
        models:
          - name: {name}
            config:
              contract:
                enforced: true
            meta:
              kairos:
                grain: one row per {grain_key}
                grain_key: [{grain_key}]
                target_class: {target_class}
                virtual_source_iri: https://example.test/virtual/{name}
                supported_adapters: [fabric]
            columns:
        """)
        + columns
    )


def _use_contracted_customer(hub: Path, sql: str) -> Path:
    """Swap the default relation binding for a contracted ``customer_stage`` model."""
    models = hub / "integration" / "transforms" / "dbt" / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "customer_stage.sql").write_text(sql, encoding="utf-8")
    (models / "schema.yml").write_text(_contract_text("customer_stage"), encoding="utf-8")
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "source:\n  relation: crm.customers",
            textwrap.dedent("""\
            source:
              dbtModel:
                name: customer_stage
                sqlPath: integration/transforms/dbt/models/customer_stage.sql
                contractPath: integration/transforms/dbt/models/schema.yml"""),
        ),
        encoding="utf-8",
    )
    return hub


def test_contracted_source_pair_is_declared_in_shared_catalog(tmp_path):
    """#584: the closure's source('crm', 'customers') must land in _crm__sources.yml."""
    hub = _use_contracted_customer(
        _hub(tmp_path),
        "select customer_id, customer_name from {{ source('crm', 'customers') }}\n",
    )

    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()
    catalog = yaml.safe_load(artifacts["models/silver/_crm__sources.yml"])
    crm = next(source for source in catalog["sources"] if source["name"] == "crm")
    assert crm["database"] == "raw"
    assert crm["schema"] == "dbo"
    assert [table["name"] for table in crm["tables"]] == ["customers"]
    # The managed virtual "dbt" system is still never declared as a raw source.
    assert "models/silver/_dbt__sources.yml" not in artifacts
    # The vocabulary a purely-contracted domain reads joins scope.inputs/provenance.
    inputs = {item.name.replace("\\", "/") for item in result.ir.scope.inputs}
    assert "integration/sources/crm/crm.vocabulary.ttl" in inputs


def test_unresolved_contracted_source_pair_is_a_blocking_diagnostic(tmp_path):
    hub = _use_contracted_customer(
        _hub(tmp_path),
        "select customer_id, customer_name from {{ source('nosuch', 'customers') }}\n",
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    diagnostic = next(
        item for item in result.diagnostics.items if item.code == "dbt-source.source-unresolved"
    )
    assert "'nosuch'" in diagnostic.message
    assert "snake_case" in diagnostic.message
    assert diagnostic.location.pointer == "/source/dbtModel/sqlPath"


def test_dotted_table_name_round_trips_into_the_catalog(tmp_path):
    hub = _hub(tmp_path)
    dtb_dir = hub / "integration" / "sources" / "dtb"
    dtb_dir.mkdir(parents=True)
    (dtb_dir / "dtb.vocabulary.ttl").write_text(
        textwrap.dedent("""
            @prefix src: <https://example.test/source/dtb#> .
            @prefix kb: <https://kairos.cnext.eu/bronze#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            src:dtb a kb:SourceSystem ; rdfs:label "dtb" ;
              kb:database "dtb_raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
            src:booking a kb:SourceTable ; kb:sourceSystem src:dtb ;
              kb:tableName "DtbBooking.sample" ; kb:primaryKeyColumns "customer_id" .
            src:id a kb:SourceColumn ; kb:sourceTable src:booking ;
              kb:columnName "customer_id" ; kb:dataType "varchar(50)" ;
              kb:nullable "false"^^xsd:boolean .
            """).strip(),
        encoding="utf-8",
    )
    hub = _use_contracted_customer(
        hub,
        "select customer_id, customer_name from {{ source('dtb', 'DtbBooking.sample') }}\n",
    )

    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    catalog = yaml.safe_load(result.artifact_dict()["models/silver/_dtb__sources.yml"])
    dtb = next(source for source in catalog["sources"] if source["name"] == "dtb")
    assert dtb["database"] == "dtb_raw"
    assert [table["name"] for table in dtb["tables"]] == ["DtbBooking.sample"]


def test_direct_binding_and_contracted_read_of_same_table_coexist(tmp_path):
    """#584 regression guard: contracted declarations must not revoke mapping authority.

    ``replacement_input_uris`` would have been the easy carrier, but tables in that set
    lose direct-mapping authority (``mapping.replaced-source-direct-authority``); this
    pins the legal combination of a direct binding on ``crm.customers`` plus a contracted
    model reading ``source('crm', 'customers')``.
    """
    hub = _hub(tmp_path)
    ontology = hub / "model" / "ontologies" / "party.ttl"
    ontology.write_text(
        ontology.read_text(encoding="utf-8") + "\nparty:Segment a owl:Class ; "
        'rdfs:label "Segment" .\n'
        "party:segment_id a owl:DatatypeProperty ;\n"
        "  rdfs:domain party:Segment ; rdfs:range xsd:string .\n",
        encoding="utf-8",
    )
    models = hub / "integration" / "transforms" / "dbt" / "models"
    models.mkdir(parents=True)
    (models / "segment_stage.sql").write_text(
        "select customer_id as segment_id from {{ source('crm', 'customers') }}\n",
        encoding="utf-8",
    )
    (models / "schema.yml").write_text(
        _contract_text(
            "segment_stage",
            target_class="https://example.test/party#Segment",
            grain_key="segment_id",
            columns="      - {name: segment_id, data_type: string, data_tests: [not_null]}\n",
        ),
        encoding="utf-8",
    )
    (hub / "integration" / "bindings" / "segment.binding.yaml").write_text(
        textwrap.dedent("""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-segment
              domain: party
            source:
              dbtModel:
                name: segment_stage
                sqlPath: integration/transforms/dbt/models/segment_stage.sql
                contractPath: integration/transforms/dbt/models/schema.yml
            target:
              class: party:Segment
            grain:
              columns: [segment_id]
            identity:
              strategy: source-natural
              sourceKey: [segment_id]
            load:
              mode: full-refresh
            fields:
              - property: party:segment_id
                expression: segment_id
            """).strip(),
        encoding="utf-8",
    )

    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    codes = {item.code for item in result.diagnostics.items}
    assert "mapping.replaced-source-direct-authority" not in codes
    catalog = yaml.safe_load(result.artifact_dict()["models/silver/_crm__sources.yml"])
    assert len(catalog["sources"]) == 1
    tables = [table["name"] for table in catalog["sources"][0]["tables"]]
    assert tables.count("customers") == 1


def test_source_pair_matching_two_distinct_tables_is_ambiguous(tmp_path):
    """Two system labels whose snake_case renderings collide on the same table name."""
    hub = _hub(tmp_path)
    for index, label in enumerate(("myCrm", "MyCrm")):
        source_dir = hub / "integration" / "sources" / f"collide{index}"
        source_dir.mkdir(parents=True)
        (source_dir / f"collide{index}.vocabulary.ttl").write_text(
            textwrap.dedent(f"""
                @prefix src: <https://example.test/source/collide{index}#> .
                @prefix kb: <https://kairos.cnext.eu/bronze#> .
                @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
                src:system a kb:SourceSystem ; rdfs:label "{label}" ;
                  kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
                src:customers a kb:SourceTable ; kb:sourceSystem src:system ;
                  kb:tableName "customers" ; kb:primaryKeyColumns "customer_id" .
                """).strip(),
            encoding="utf-8",
        )
    hub = _use_contracted_customer(
        hub,
        "select customer_id, customer_name from {{ source('my_crm', 'customers') }}\n",
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    diagnostic = next(
        item for item in result.diagnostics.items if item.code == "dbt-source.source-ambiguous"
    )
    assert "'my_crm'" in diagnostic.message


def test_seed_ref_resolves_and_joins_the_plan_as_a_seed_dependency(tmp_path):
    """#586a: ref() → authored seed CSV is a valid leaf, planned as kind="seed"."""
    hub = _hub(tmp_path)
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "country_codes.csv").write_text("code,name\nBE,Belgium\n", encoding="utf-8")
    hub = _use_contracted_customer(
        hub,
        "select customer_id, customer_name from {{ source('crm', 'customers') }} "
        "left join {{ ref('country_codes') }} on 1 = 1\n",
    )

    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    dependencies = {item.path: item for item in result.plan.dbt_dependencies}
    seed = dependencies["seeds/country_codes.csv"]
    assert seed.kind == "seed"
    assert seed.model_name == "country_codes"
    assert seed.content == "code,name\nBE,Belgium\n"
    assert seed.source_path == "integration/transforms/dbt/seeds/country_codes.csv"
    # Seed bytes are provenance inputs: a CSV change must change the hash.
    (seeds / "country_codes.csv").write_text("code,name\nNL,Netherlands\n", encoding="utf-8")
    changed = compile_domain(hub, "party", CompileMode.EMIT)
    assert changed.succeeded
    assert changed.provenance_hash != result.provenance_hash


def test_ref_matching_both_model_and_seed_blocks_the_domain(tmp_path):
    hub = _hub(tmp_path)
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "dup.csv").write_text("id\n1\n", encoding="utf-8")
    hub = _use_contracted_customer(
        hub,
        "select customer_id, customer_name from {{ ref('dup') }}\n",
    )
    (hub / "integration" / "transforms" / "dbt" / "models" / "dup.sql").write_text(
        "select 1 as customer_id\n", encoding="utf-8"
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    assert "dbt-source.dependency-ambiguous" in {item.code for item in result.diagnostics.items}


def _scope_with_inputs(*inputs: ProvenanceInput) -> BuildScope:
    return BuildScope(
        domain="party",
        hub_root=".",
        api_version="kairos.eu/v5",
        adapter="fabric",
        namespace="https://example.test/party#",
        toolkit_version="0",
        inputs=inputs,
    )


def _contracted_binding():
    return load_entity_binding(
        textwrap.dedent("""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-customer
              domain: party
            source:
              dbtModel:
                name: customer_stage
                sqlPath: integration/transforms/dbt/models/customer_stage.sql
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
            """).strip(),
        path="customer.binding.yaml",
    )


def test_inputs_walk_applies_the_same_seed_and_ambiguity_rules():
    """Two-walk consistency: the plan walk over scope.inputs mirrors the filesystem walk."""
    binding = _contracted_binding()
    scope = _scope_with_inputs(
        ProvenanceInput(
            "integration/transforms/dbt/models/customer_stage.sql",
            "select 1 from {{ source('crm', 'customers') }} join {{ ref('country_codes') }}\n",
        ),
        ProvenanceInput("integration/transforms/dbt/seeds/country_codes.csv", "code\nBE\n"),
    )

    closures, diagnostics = _dbt_dependency_closures((binding,), scope)

    assert diagnostics == ()
    (closure,) = closures
    assert closure.sql_paths == ("integration/transforms/dbt/models/customer_stage.sql",)
    assert closure.seed_paths == ("integration/transforms/dbt/seeds/country_codes.csv",)
    assert closure.source_pairs == (("crm", "customers"),)


def test_inputs_walk_flags_model_and_seed_name_clash():
    binding = _contracted_binding()
    scope = _scope_with_inputs(
        ProvenanceInput(
            "integration/transforms/dbt/models/customer_stage.sql",
            "select 1 from {{ ref('dup') }}\n",
        ),
        ProvenanceInput("integration/transforms/dbt/models/dup.sql", "select 1\n"),
        ProvenanceInput("integration/transforms/dbt/seeds/dup.csv", "id\n1\n"),
    )

    closures, diagnostics = _dbt_dependency_closures((binding,), scope)

    assert [item.code for item in diagnostics] == ["dbt-source.dependency-ambiguous"]
    (closure,) = closures
    assert closure.seed_paths == ()


def test_undecodable_seed_bytes_are_a_diagnostic_not_a_crash(tmp_path):
    """A cp1252 seed export (the real #586 use case) must not escape as a traceback."""
    hub = _hub(tmp_path)
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "country_codes.csv").write_bytes(b"code,name\nBE,C\xf4te\n")
    hub = _use_contracted_customer(
        hub,
        "select customer_id, customer_name from {{ source('crm', 'customers') }} "
        "left join {{ ref('country_codes') }} on 1 = 1\n",
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    codes = {item.code for item in result.diagnostics.items}
    assert "dbt-source.dependency-unresolved" in codes


def test_jinja_commented_source_and_ref_are_ignored(tmp_path):
    """{# ... #} blocks are never rendered by dbt; they must not create phantom
    dependencies or false blocking source diagnostics."""
    hub = _use_contracted_customer(
        _hub(tmp_path),
        "{# scratch: {{ source('ghost', 'nope') }} and {{ ref('phantom_model') }} #}\n"
        "select customer_id, customer_name from {{ source('crm', 'customers') }}\n",
    )

    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    codes = {item.code for item in result.diagnostics.items}
    assert "dbt-source.source-unresolved" not in codes
    assert "dbt-source.dependency-unresolved" not in codes
    assert not any("phantom" in path for path in result.artifact_dict())


def test_keyword_source_call_is_declared(tmp_path):
    """dbt accepts source(source_name=..., table_name=...) in either order."""
    hub = _use_contracted_customer(
        _hub(tmp_path),
        "select customer_id, customer_name from "
        "{{ source(table_name='customers', source_name='crm') }}\n",
    )

    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    catalog = yaml.safe_load(result.artifact_dict()["models/silver/_crm__sources.yml"])
    crm = next(source for source in catalog["sources"] if source["name"] == "crm")
    assert [table["name"] for table in crm["tables"]] == ["customers"]


def test_inputs_walk_matches_ref_names_case_exactly():
    """dbt matches ref() names exactly; a wrong-case ref must not resolve."""
    binding = _contracted_binding()
    scope = _scope_with_inputs(
        ProvenanceInput(
            "integration/transforms/dbt/models/customer_stage.sql",
            "select 1 from {{ ref('STG_Customer') }}\n",
        ),
        ProvenanceInput("integration/transforms/dbt/models/stg_customer.sql", "select 1\n"),
    )

    closures, diagnostics = _dbt_dependency_closures((binding,), scope)

    assert [item.code for item in diagnostics] == ["dbt-source.dependency-unresolved"]
    (closure,) = closures
    assert closure.sql_paths == ("integration/transforms/dbt/models/customer_stage.sql",)


@pytest.mark.parametrize(
    "call",
    [
        "{{ source('crm', table_name='customers') }}",
        "{{ source(var('sys'), 'customers') }}",
    ],
)
def test_unreadable_source_call_blocks_the_domain(tmp_path, call):
    """#584 fails closed rather than emitting a project with an undeclared source."""
    hub = _use_contracted_customer(
        _hub(tmp_path), f"select customer_id, customer_name from {call}\n"
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    diagnostic = next(
        item for item in result.diagnostics.items if item.code == "dbt-source.source-unparsed"
    )
    assert "source_name=" in diagnostic.message
    # The binding is blocked, so neither its model nor an (undeclarable) source catalog
    # is emitted -- same containment as the other dbt-source.* resolution failures.
    assert {entity.binding.name for entity in result.plan.entities if entity.blocked} == {
        "crm-customer"
    }
    artifacts = result.artifact_dict()
    assert "models/silver/_crm__sources.yml" not in artifacts
    assert "models/silver/party/customer.sql" not in artifacts


def test_macro_named_like_source_is_not_treated_as_a_source_call(tmp_path):
    """`\b` must not match a macro whose name merely ends in `source`."""
    hub = _use_contracted_customer(
        _hub(tmp_path),
        "select customer_id, customer_name from {{ source('crm', 'customers') }} "
        "where {{ my_source(anything) }}\n",
    )

    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    assert "models/silver/_crm__sources.yml" in result.artifact_dict()


def test_inputs_walk_reports_unreadable_source_calls_too():
    """Both extraction sites share one verdict via the same helper."""
    binding = _contracted_binding()
    scope = _scope_with_inputs(
        ProvenanceInput(
            "integration/transforms/dbt/models/customer_stage.sql",
            "select 1 from {{ source('crm', table_name='customers') }}\n",
        ),
    )

    closures, diagnostics = _dbt_dependency_closures((binding,), scope)

    assert [item.code for item in diagnostics] == ["dbt-source.source-unparsed"]
    (closure,) = closures
    assert closure.source_pairs == ()


def test_inputs_walk_selects_seed_column_docs_siblings():
    """#586b: the plan walk carries `seeds/<name>.yml` alongside the CSV it documents."""
    binding = _contracted_binding()
    scope = _scope_with_inputs(
        ProvenanceInput(
            "integration/transforms/dbt/models/customer_stage.sql",
            "select 1 from {{ ref('country_codes') }}\n",
        ),
        ProvenanceInput("integration/transforms/dbt/seeds/country_codes.csv", "code\nBE\n"),
        ProvenanceInput(
            "integration/transforms/dbt/seeds/country_codes.yml",
            "version: 2\nseeds:\n  - name: country_codes\n",
        ),
        # An unrelated seed's docs must not be dragged in.
        ProvenanceInput(
            "integration/transforms/dbt/seeds/other.yml",
            "version: 2\nseeds:\n  - name: other\n",
        ),
    )

    closures, diagnostics = _dbt_dependency_closures((binding,), scope)

    assert diagnostics == ()
    (closure,) = closures
    assert closure.seed_paths == ("integration/transforms/dbt/seeds/country_codes.csv",)
    assert closure.seed_properties_paths == (
        "integration/transforms/dbt/seeds/country_codes.yml",
    )


def test_inputs_walk_flags_two_docs_spellings_for_one_seed():
    binding = _contracted_binding()
    scope = _scope_with_inputs(
        ProvenanceInput(
            "integration/transforms/dbt/models/customer_stage.sql",
            "select 1 from {{ ref('country_codes') }}\n",
        ),
        ProvenanceInput("integration/transforms/dbt/seeds/country_codes.csv", "code\nBE\n"),
        ProvenanceInput(
            "integration/transforms/dbt/seeds/country_codes.yml",
            "version: 2\nseeds:\n  - name: country_codes\n",
        ),
        ProvenanceInput(
            "integration/transforms/dbt/seeds/country_codes.yaml",
            "version: 2\nseeds:\n  - name: country_codes\n",
        ),
    )

    closures, diagnostics = _dbt_dependency_closures((binding,), scope)

    assert [item.code for item in diagnostics] == ["dbt-source.dependency-ambiguous"]
    (closure,) = closures
    assert closure.seed_properties_paths == ()
