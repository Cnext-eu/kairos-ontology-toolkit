# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for direct v5 contracted-dbt source resolution."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.compiler import CompileError, load_entity_binding
from kairos_ontology.core.compiler.dbt_source import (
    contract_target_class,
    resolve_dbt_model_dependency_paths,
    resolve_dbt_model_source,
    validate_contract_target_class,
)


def _binding(*, grain: str = "customer_id", identity: str = "customer_id") -> str:
    return textwrap.dedent(f"""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: customer
          domain: party
        source:
          dbtModel:
            name: int_customer
            sqlPath: integration/transforms/dbt/models/intermediate/int_customer.sql
            contractPath: integration/transforms/dbt/models/intermediate/schema.yml
        target:
          class: party:Customer
        grain:
          columns: [{grain}]
        identity:
          strategy: source-natural
          sourceKey: [{identity}]
        load:
          mode: full-refresh
        fields:
          - property: party:customerId
            expression: customer_id
        """).strip()


def _model() -> dict:
    return {
        "name": "int_customer",
        "description": "Contracted customer rows.",
        "config": {"materialized": "table", "contract": {"enforced": True}},
        "meta": {
            "kairos": {
                "target_class": "https://example.com/party#Customer",
                "virtual_source_iri": "https://example.com/source/dbt#intCustomer",
                "grain": "one row per customer",
                "grain_key": ["customer_id"],
                "supported_adapters": ["fabric-warehouse"],
            }
        },
        "columns": [
            {"name": "customer_id", "data_type": "string"},
            {
                "name": "customer_name",
                "data_type": "varchar(200)",
                "data_tests": ["not_null"],
            },
        ],
    }


def _hub(tmp_path: Path, model: dict | None = None) -> Path:
    hub = tmp_path / "hub"
    models = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate"
    models.mkdir(parents=True)
    (models / "int_customer.sql").write_text(
        "select customer_id, customer_name from {{ ref('stg_customer') }}\n",
        encoding="utf-8",
    )
    (models / "stg_customer.sql").write_text(
        "select customer_id, customer_name from {{ source('crm', 'customers') }}\n",
        encoding="utf-8",
    )
    (models / "schema.yml").write_text(
        yaml.safe_dump({"version": 2, "models": [model or _model()]}, sort_keys=False),
        encoding="utf-8",
    )
    return hub


def _resolve(tmp_path: Path, model: dict | None = None, binding: str | None = None):
    hub = _hub(tmp_path, model)
    loaded = load_entity_binding(binding or _binding(), path="customer.binding.yml")
    return resolve_dbt_model_source(loaded, hub)


def test_resolves_authoritative_dbt_output_as_compiler_relation(tmp_path: Path) -> None:
    relation = _resolve(tmp_path)

    assert relation.ref == "int_customer"
    assert relation.uri == "https://example.com/source/dbt#intCustomer"
    assert relation.connection_type == "dbt"
    assert [(column.name, column.data_type) for column in relation.columns] == [
        ("customer_id", "string"),
        ("customer_name", "varchar(200)"),
    ]
    assert relation.columns[0].is_primary_key
    assert not relation.columns[0].nullable
    assert not relation.columns[1].nullable


def test_relation_binding_is_rejected_with_stable_missing_model_code(tmp_path: Path) -> None:
    relation_binding = load_entity_binding(
        _binding().replace(
            "  dbtModel:\n"
            "    name: int_customer\n"
            "    sqlPath: integration/transforms/dbt/models/intermediate/int_customer.sql\n"
            "    contractPath: integration/transforms/dbt/models/intermediate/schema.yml",
            "  relation: crm.customers",
        ),
        path="relation.binding.yml",
    )

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_source(relation_binding, _hub(tmp_path))

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "dbt-source.missing"
    assert diagnostic.location.path == "relation.binding.yml"
    assert diagnostic.location.pointer == "/source/dbtModel/name"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda model: model["config"]["contract"].update(enforced=False),
            "dbt-source.contract-not-enforced",
        ),
        (
            lambda model: model["columns"][1].update(data_type="made_up_type"),
            "dbt-source.type-invalid",
        ),
        (
            lambda model: model["meta"]["kairos"].update(grain_key=["missing"]),
            "dbt-source.grain-invalid",
        ),
        (lambda model: model.update(columns=[]), "dbt-source.columns-invalid"),
        (lambda model: model.update(name="other"), "dbt-source.model-unresolved"),
        (
            lambda model: model["meta"]["kairos"].update(virtual_source_iri="relative"),
            "dbt-source.contract-invalid",
        ),
        (
            lambda model: model["meta"]["kairos"].pop("supported_adapters"),
            "dbt-source.contract-invalid",
        ),
        (
            lambda model: model["meta"]["kairos"].update(supported_adapters=["snowflake"]),
            "dbt-source.contract-invalid",
        ),
        (
            lambda model: model["meta"]["kairos"].update(supported_adapters=["fabric-warehouse", "fabric-warehouse"]),
            "dbt-source.contract-invalid",
        ),
        # #503: target_class was declared by the contract and written as a sentinel by
        # scaffold-staging, but never read at compile time -- so neither an absent value
        # nor an unconfirmed `<CONFIRM_TARGET_CLASS>` was rejected.
        (
            lambda model: model["meta"]["kairos"].pop("target_class"),
            "dbt-source.contract-invalid",
        ),
        (
            lambda model: model["meta"]["kairos"].update(target_class="<CONFIRM_TARGET_CLASS>"),
            "dbt-source.contract-invalid",
        ),
        (
            lambda model: model["meta"]["kairos"].update(target_class="party:Customer"),
            "dbt-source.contract-invalid",
        ),
    ],
)
def test_rejects_invalid_selected_output_contract(tmp_path: Path, mutation, code: str) -> None:
    model = _model()
    mutation(model)

    with pytest.raises(CompileError) as excinfo:
        _resolve(tmp_path, model)

    assert {item.code for item in excinfo.value.diagnostics} == {code}


@pytest.mark.parametrize(
    ("binding", "code"),
    [
        (_binding(grain="customer_name"), "dbt-source.grain-mismatch"),
        (_binding(identity="customer_name"), "dbt-source.identity-mismatch"),
    ],
)
def test_requires_binding_grain_and_identity_to_match_contract(
    tmp_path: Path, binding: str, code: str
) -> None:
    with pytest.raises(CompileError) as excinfo:
        _resolve(tmp_path, binding=binding)

    assert {item.code for item in excinfo.value.diagnostics} == {code}


def test_contract_target_class_is_read_from_the_selected_model(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    assert contract_target_class(binding, hub) == "https://example.com/party#Customer"


def test_matching_target_class_is_accepted(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    validate_contract_target_class(binding, hub, "https://example.com/party#Customer")


def test_target_class_mismatch_is_rejected_with_stable_location(tmp_path: Path) -> None:
    """#503: the binding and the contract each declare the target class; nothing compared them.

    A contracted model claiming to produce ``RevenueLine`` while the binding maps its columns
    onto ``InvoiceLine`` compiled clean and only surfaced as wrong data downstream.
    """
    hub = _hub(tmp_path)
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    with pytest.raises(CompileError) as excinfo:
        validate_contract_target_class(binding, hub, "https://example.com/party#Supplier")

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "dbt-source.target-mismatch"
    assert diagnostic.location.path == "customer.binding.yml"
    assert diagnostic.location.pointer == "/source/dbtModel/contractPath"
    # Both sides are named, so the author does not have to open two files to see the drift.
    assert "https://example.com/party#Supplier" in diagnostic.message
    assert "https://example.com/party#Customer" in diagnostic.message


def test_requires_exact_selected_sql_and_contract_paths(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    binding = load_entity_binding(
        _binding().replace(
            "integration/transforms/dbt/models/intermediate/int_customer.sql",
            "integration/transforms/dbt/models/intermediate/other.sql",
        ),
        path="customer.binding.yml",
    )

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_source(binding, hub)

    assert {item.code for item in excinfo.value.diagnostics} == {"dbt-source.path-unresolved"}


def test_rejects_unresolved_transitive_dbt_ref_dependency(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    sql_path = (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "int_customer.sql"
    )
    sql_path.write_text(
        "select * from {{ ref('missing_support_model') }}\n",
        encoding="utf-8",
    )
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_source(binding, hub)

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "dbt-source.dependency-unresolved"
    assert diagnostic.location.pointer == "/source/dbtModel/sqlPath"
    assert "missing_support_model" in diagnostic.message


def test_resolves_seed_backed_ref_dependency_as_a_leaf(tmp_path: Path) -> None:
    """#586a: a ref() targeting an authored seed CSV terminates that walk branch."""
    hub = _hub(tmp_path)
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True)
    seed_path = seeds / "country_codes.csv"
    seed_path.write_text("code,name\nBE,Belgium\n", encoding="utf-8")
    sql_path = (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "int_customer.sql"
    )
    sql_path.write_text(
        "select customer_id, customer_name from {{ ref('stg_customer') }} "
        "left join {{ ref('country_codes') }} on 1 = 1\n",
        encoding="utf-8",
    )
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    paths = resolve_dbt_model_dependency_paths(binding, hub)

    assert seed_path.resolve() in paths
    assert {path.suffix for path in paths} == {".sql", ".csv"}
    # And full model resolution still succeeds over the same closure.
    relation = resolve_dbt_model_source(binding, hub, dependency_paths=paths)
    assert relation.ref == "int_customer"


def test_ref_matching_both_model_and_seed_is_ambiguous(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "stg_customer.csv").write_text("customer_id\n1\n", encoding="utf-8")
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_source(binding, hub)

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "dbt-source.dependency-ambiguous"
    assert diagnostic.location.pointer == "/source/dbtModel/sqlPath"
    assert "stg_customer" in diagnostic.message


def test_ref_matching_neither_model_nor_seed_mentions_seeds(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    sql_path = (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "int_customer.sql"
    )
    sql_path.write_text("select * from {{ ref('missing') }}\n", encoding="utf-8")
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_source(binding, hub)

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "dbt-source.dependency-unresolved"
    assert "seeds" in diagnostic.message


def test_rejects_unsafe_dbt_source_path_with_stable_location(tmp_path: Path) -> None:
    binding = load_entity_binding(
        _binding().replace(
            "integration/transforms/dbt/models/intermediate/int_customer.sql",
            "../int_customer.sql",
        ),
        path="customer.binding.yml",
    )

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_source(binding, _hub(tmp_path))

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "dbt-source.unsafe-path"
    assert diagnostic.location.path == "customer.binding.yml"
    assert diagnostic.location.pointer == "/source/dbtModel/sqlPath"


@pytest.mark.parametrize("construct", ["join", "window", "grainChange"])
def test_entity_binding_expression_rejects_relational_constructs(construct: str) -> None:
    binding = _binding().replace(
        "expression: customer_id",
        f"expression:\n      {construct}: customer_id",
    )

    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(binding, path="customer.binding.yml")

    assert any(item.code == "expression.ambiguous" for item in excinfo.value.diagnostics)


def test_wrong_case_ref_is_unresolved_even_on_case_insensitive_filesystems(tmp_path: Path) -> None:
    """dbt matches ref() names exactly; Windows rglob must not resolve a wrong-case ref."""
    hub = _hub(tmp_path)
    sql_path = (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "int_customer.sql"
    )
    sql_path.write_text("select * from {{ ref('STG_Customer') }}\n", encoding="utf-8")
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_source(binding, hub)

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "dbt-source.dependency-unresolved"
    assert "STG_Customer" in diagnostic.message


def test_jinja_commented_ref_creates_no_dependency(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    sql_path = (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "int_customer.sql"
    )
    sql_path.write_text(
        "{# unused: {{ ref('phantom_model') }} #}\n"
        "select customer_id, customer_name from {{ ref('stg_customer') }}\n",
        encoding="utf-8",
    )
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    paths = resolve_dbt_model_dependency_paths(binding, hub)

    assert {path.stem for path in paths} == {"int_customer", "stg_customer"}


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("select * from {{ source('crm', 'customers') }}", {("crm", "customers")}),
        (
            "select * from {{ source(source_name='crm', table_name='customers') }}",
            {("crm", "customers")},
        ),
        (
            "select * from {{ source(table_name='customers', source_name='crm') }}",
            {("crm", "customers")},
        ),
        (
            "select * from {{source( source_name = 'crm' ,  table_name = 'customers' )}}",
            {("crm", "customers")},
        ),
        (
            'select * from {{ source("dtb", "DtbBooking.sample") }}',
            {("dtb", "DtbBooking.sample")},
        ),
        ("{# {{ source('ghost', 'nope') }} #}\nselect 1", set()),
        (
            "{# source('ghost', 'nope') #} select * from {{ source('crm', 'customers') }}",
            {("crm", "customers")},
        ),
    ],
)
def test_extract_source_pairs_handles_positional_kwargs_and_comments(sql, expected) -> None:
    from kairos_ontology.core.compiler.dbt_source import extract_source_pairs

    assert extract_source_pairs(sql) == frozenset(expected)


@pytest.mark.parametrize(
    "sql",
    [
        # Mixed positional/keyword form: dbt-valid, statically unreadable by extraction.
        "select * from {{ source('crm', table_name='customers') }}",
        # Dynamic arguments of every shape.
        "select * from {{ source(var('sys'), 'customers') }}",
        "select * from {{ source(my_system, 'customers') }}",
        "select * from {{ source('crm' ~ suffix, 'customers') }}",
    ],
)
def test_unreadable_source_call_fails_closed(tmp_path: Path, sql: str) -> None:
    """#584: a source() call the compiler cannot read must not pass silently.

    The alternative is an emitted project whose source is never declared, which fails
    offline `dbt parse` with no compile diagnostic at all.
    """
    hub = _hub(tmp_path)
    (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "stg_customer.sql"
    ).write_text(sql + "\n", encoding="utf-8")
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_source(binding, hub)

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "dbt-source.source-unparsed"
    assert diagnostic.location.pointer == "/source/dbtModel/sqlPath"
    assert "source_name=" in diagnostic.message
    assert "dynamic arguments" in diagnostic.message


@pytest.mark.parametrize(
    "sql",
    [
        "select * from {{ source('crm', 'customers') }}",
        "select * from {{ source(source_name='crm', table_name='customers') }}",
        "select * from {{ source(table_name='customers', source_name='crm') }}",
        # A macro whose name merely ends in `source` is not a source() call site.
        "select * from {{ my_source('crm', anything) }} join {{ source('crm', 'customers') }}",
        # An unreadable call inside a Jinja comment is not a call site either.
        "{# {{ source(var('x'), 'y') }} #}\nselect * from {{ source('crm', 'customers') }}",
        # The same identical call twice must not look like one unparsed call.
        "select * from {{ source('crm', 'customers') }} "
        "union all select * from {{ source('crm', 'customers') }}",
    ],
)
def test_readable_source_calls_are_accepted(tmp_path: Path, sql: str) -> None:
    hub = _hub(tmp_path)
    (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "stg_customer.sql"
    ).write_text(sql + "\n", encoding="utf-8")
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    relation = resolve_dbt_model_source(binding, hub)

    assert relation.ref == "int_customer"


def test_extract_sources_counts_unreadable_call_sites() -> None:
    from kairos_ontology.core.compiler.dbt_source import extract_sources

    extraction = extract_sources(
        "{{ source('crm', 'customers') }} {{ source('crm', table_name='orders') }}"
    )

    assert extraction.pairs == frozenset({("crm", "customers")})
    assert extraction.unparsed == 1


def test_seed_column_docs_sibling_joins_the_closure(tmp_path: Path) -> None:
    """#586b: `seeds/<name>.yml` rides along with its CSV so it can be emitted."""
    hub = _hub(tmp_path)
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "country_codes.csv").write_text("code,name\nBE,Belgium\n", encoding="utf-8")
    docs_path = seeds / "country_codes.yml"
    docs_path.write_text(
        "version: 2\nseeds:\n  - name: country_codes\n    columns:\n      - name: code\n",
        encoding="utf-8",
    )
    sql_path = (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "int_customer.sql"
    )
    sql_path.write_text(
        "select customer_id, customer_name from {{ ref('stg_customer') }} "
        "left join {{ ref('country_codes') }} on 1 = 1\n",
        encoding="utf-8",
    )
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    paths = resolve_dbt_model_dependency_paths(binding, hub)

    assert docs_path.resolve() in paths
    # The CSV and its docs share a stem; that must NOT read as a name collision.
    assert {path.suffix for path in paths} == {".sql", ".csv", ".yml"}


def test_two_seed_docs_spellings_for_one_seed_are_ambiguous(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "country_codes.csv").write_text("code\nBE\n", encoding="utf-8")
    for suffix in (".yml", ".yaml"):
        (seeds / f"country_codes{suffix}").write_text(
            "version: 2\nseeds:\n  - name: country_codes\n", encoding="utf-8"
        )
    sql_path = (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "int_customer.sql"
    )
    sql_path.write_text(
        "select customer_id, customer_name from {{ ref('stg_customer') }} "
        "left join {{ ref('country_codes') }} on 1 = 1\n",
        encoding="utf-8",
    )
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_dependency_paths(binding, hub)

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "dbt-source.dependency-ambiguous"
    assert "column-docs" in diagnostic.message


def test_seed_docs_that_are_not_utf8_fail_as_a_binding_diagnostic(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "country_codes.csv").write_text("code\nBE\n", encoding="utf-8")
    (seeds / "country_codes.yml").write_bytes(b"version: 2\nseeds:\n  - name: caf\xe9\n")
    sql_path = (
        hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "int_customer.sql"
    )
    sql_path.write_text(
        "select customer_id, customer_name from {{ ref('stg_customer') }} "
        "left join {{ ref('country_codes') }} on 1 = 1\n",
        encoding="utf-8",
    )
    binding = load_entity_binding(_binding(), path="customer.binding.yml")

    with pytest.raises(CompileError) as excinfo:
        resolve_dbt_model_dependency_paths(binding, hub)

    assert excinfo.value.diagnostics[0].code == "dbt-source.dependency-unresolved"


def test_extract_refs_strips_comments_and_ignores_the_package_form() -> None:
    """The selection rule stays exact: no IGNORECASE, no two-argument package refs."""
    from kairos_ontology.core.compiler.dbt_source import extract_refs

    text = (
        "{# {{ ref('commented') }} #}\n"
        "{{ ref('real') }} {{ REF('shouted') }} {{ ref('dbt_utils', 'packaged') }}\n"
    )

    assert extract_refs(text) == {"real"}
