# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for governed custom dbt bundle assembly."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kairos_ontology.core.dbt_bundle import assemble_dbt_bundle
from kairos_ontology.core.dbt_contracts import DbtContractError


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "transforms"
    for directory in ("models/intermediate", "macros", "tests"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "models/intermediate/conformed.sql").write_text(
        "{{ ref('stg_source') }}\n",
        encoding="utf-8",
    )
    (root / "models/intermediate/conformed.yml").write_text(
        "version: 2\nmodels:\n  - name: conformed\n",
        encoding="utf-8",
    )
    (root / "tests/conformed_grain.sql").write_text("select 1 where false\n", encoding="utf-8")
    return root


def _contract(name="conformed", *, macros=(), packages=(), decisions=()):
    return SimpleNamespace(
        name=name,
        required_macros=macros,
        required_packages=packages,
        decisions=decisions,
    )


def test_assembles_artifacts_and_governed_packages(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "macros/hub__normalize.sql").write_text(
        "{% macro hub__normalize(value) %}lower({{ value }}){% endmacro %}\n",
        encoding="utf-8",
    )

    bundle = assemble_dbt_bundle(
        root,
        [_contract(macros=("hub__normalize",), packages=("dbt-labs/dbt_utils",))],
        known_resources=("stg_source",),
    )

    assert bundle.model_names == {"conformed"}
    assert bundle.macro_names == {"hub__normalize"}
    assert "models/intermediate/conformed.sql" in bundle.artifacts
    packages = yaml.safe_load(bundle.artifacts["packages.yml"])
    assert packages["packages"][0]["package"] == "dbt-labs/dbt_utils"
    assert packages["packages"][0]["version"] == [">=1.0.0", "<2.0.0"]


def test_rejects_missing_macro_and_invalid_macro_name(tmp_path: Path) -> None:
    root = _bundle(tmp_path)

    with pytest.raises(DbtContractError, match="not defined"):
        assemble_dbt_bundle(
            root,
            [_contract(macros=("hub__normalize",))],
            known_resources=("stg_source",),
        )

    (root / "macros/bad.sql").write_text(
        "{% macro kairos_internal(value) %}{{ value }}{% endmacro %}\n",
        encoding="utf-8",
    )
    with pytest.raises(DbtContractError, match="cannot use the kairos_ prefix"):
        assemble_dbt_bundle(root, [_contract()], known_resources=("stg_source",))


def test_rejects_unresolved_ref_and_generated_collision(tmp_path: Path) -> None:
    root = _bundle(tmp_path)

    with pytest.raises(DbtContractError, match="unresolved dbt ref"):
        assemble_dbt_bundle(root, [_contract()])

    with pytest.raises(DbtContractError, match="collides with generated"):
        assemble_dbt_bundle(
            root,
            [_contract()],
            known_resources=("stg_source",),
            generated_artifacts=("models/intermediate/conformed.sql",),
        )


def test_rejects_duplicate_model_and_macro_resources(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "models/conformed.sql").write_text("select 1\n", encoding="utf-8")

    with pytest.raises(DbtContractError, match="duplicate dbt model"):
        assemble_dbt_bundle(root, [], known_resources=("stg_source",))

    (root / "models/conformed.sql").unlink()
    for name in ("one.sql", "two.sql"):
        (root / "macros" / name).write_text(
            "{% macro hub__same() %}1{% endmacro %}\n",
            encoding="utf-8",
        )
    with pytest.raises(DbtContractError, match="duplicate custom macro"):
        assemble_dbt_bundle(root, [_contract()], known_resources=("stg_source",))


def test_rejects_custom_sql_without_contract(tmp_path: Path) -> None:
    root = _bundle(tmp_path)

    with pytest.raises(DbtContractError, match="require meta.kairos contracts"):
        assemble_dbt_bundle(root, [], known_resources=("stg_source",))


def test_rejects_generated_model_name_collision(tmp_path: Path) -> None:
    root = _bundle(tmp_path)

    with pytest.raises(DbtContractError, match="collide with generated resources"):
        assemble_dbt_bundle(
            root,
            [_contract()],
            generated_artifacts=("models/silver/domain/conformed.sql",),
            known_resources=("stg_source",),
        )


def test_scopes_bundle_to_active_contract_dependency_closure(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "models/intermediate/conformed.sql").write_text(
        "{{ ref('base_model') }}\n",
        encoding="utf-8",
    )
    (root / "models/intermediate/base_model.sql").write_text(
        "{{ ref('stg_source') }}\n",
        encoding="utf-8",
    )
    (root / "models/intermediate/unrelated.sql").write_text("select 1\n", encoding="utf-8")
    (root / "models/intermediate/conformed.yml").unlink()
    (root / "models/intermediate/contracts.yml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "models": [
                    {"name": "conformed"},
                    {"name": "base_model"},
                    {"name": "unrelated"},
                ],
                "unit_tests": [
                    {"name": "active_unit", "model": "conformed"},
                    {"name": "unrelated_unit", "model": "unrelated"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "tests/conformed_grain.sql").write_text(
        "select * from {{ ref('conformed') }}\n",
        encoding="utf-8",
    )
    (root / "tests/unrelated_test.sql").write_text(
        "select * from {{ ref('unrelated') }}\n",
        encoding="utf-8",
    )
    for name in ("active", "base", "unrelated"):
        (root / f"macros/{name}.sql").write_text(
            f"{{% macro hub__{name}() %}}1{{% endmacro %}}\n",
            encoding="utf-8",
        )

    contracts = [
        _contract(
            macros=("hub__active",),
            packages=("dbt-labs/dbt_utils",),
        ),
        _contract(
            "base_model",
            macros=("hub__base",),
            packages=("metaplane/dbt_expectations",),
        ),
        _contract(
            "unrelated",
            macros=("hub__unrelated",),
        ),
    ]
    bundle = assemble_dbt_bundle(
        root,
        contracts,
        active_contract_names=("conformed",),
        known_resources=("stg_source",),
    )

    assert bundle.model_names == {"conformed", "base_model"}
    assert bundle.macro_names == {"hub__active", "hub__base"}
    assert bundle.packages == ("dbt-labs/dbt_utils", "metaplane/dbt_expectations")
    assert "models/intermediate/unrelated.sql" not in bundle.artifacts
    assert "tests/unrelated_test.sql" not in bundle.artifacts
    assert "macros/unrelated.sql" not in bundle.artifacts
    properties = yaml.safe_load(bundle.artifacts["models/intermediate/contracts.yml"])
    assert [model["name"] for model in properties["models"]] == [
        "conformed",
        "base_model",
    ]
    assert [test["name"] for test in properties["unit_tests"]] == ["active_unit"]

    full_bundle = assemble_dbt_bundle(
        root,
        contracts,
        known_resources=("stg_source",),
    )
    assert "models/intermediate/unrelated.sql" in full_bundle.artifacts
    assert "tests/unrelated_test.sql" in full_bundle.artifacts
    assert "macros/unrelated.sql" in full_bundle.artifacts


def test_explicit_empty_scope_excludes_custom_artifacts(tmp_path: Path) -> None:
    root = _bundle(tmp_path)

    bundle = assemble_dbt_bundle(
        root,
        [_contract()],
        active_contract_names=(),
    )

    assert bundle.artifacts == {}
    assert bundle.model_names == set()
    assert bundle.macro_names == set()
    assert bundle.packages == ()


def test_scoped_bundle_accepts_ref_to_generated_model(tmp_path: Path) -> None:
    root = _bundle(tmp_path)

    bundle = assemble_dbt_bundle(
        root,
        [_contract()],
        active_contract_names=("conformed",),
        generated_artifacts=("models/silver/domain/stg_source.sql",),
    )

    assert bundle.model_names == {"conformed"}


def test_scoped_bundle_follows_test_model_dependencies(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "models/intermediate/test_input.sql").write_text(
        "select 1 as value\n",
        encoding="utf-8",
    )
    (root / "models/intermediate/conformed.yml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "models": [{"name": "conformed"}, {"name": "test_input"}],
                "unit_tests": [
                    {
                        "name": "conformed_input",
                        "model": "conformed",
                        "given": [{"input": "ref('test_input')", "rows": [{"value": 1}]}],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    bundle = assemble_dbt_bundle(
        root,
        [_contract(), _contract("test_input")],
        active_contract_names=("conformed",),
        known_resources=("stg_source",),
    )

    assert bundle.model_names == {"conformed", "test_input"}
    assert "models/intermediate/test_input.sql" in bundle.artifacts


def test_scoped_bundle_keeps_referenced_sources_and_groups(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "models/intermediate/conformed.sql").write_text(
        "{{ config(group='finance') }}\n{{ source('custom', 'input') }}\n",
        encoding="utf-8",
    )
    (root / "models/intermediate/conformed.yml").write_text(
        "version: 2\nmodels:\n  - name: conformed\n",
        encoding="utf-8",
    )
    (root / "models/intermediate/resources.yml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "sources": [
                    {"name": "custom", "tables": [{"name": "input"}]},
                    {"name": "unrelated", "tables": [{"name": "other"}]},
                ],
                "groups": [
                    {"name": "finance", "owner": {"name": "Data Team"}},
                    {"name": "other", "owner": {"name": "Other Team"}},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    bundle = assemble_dbt_bundle(
        root,
        [_contract()],
        active_contract_names=("conformed",),
    )

    resources = yaml.safe_load(bundle.artifacts["models/intermediate/resources.yml"])
    assert [item["name"] for item in resources["sources"]] == ["custom"]
    assert [item["name"] for item in resources["groups"]] == ["finance"]


def test_scoped_bundle_follows_required_macro_resources(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "models/intermediate/macro_input.sql").write_text(
        "select 1 as value\n",
        encoding="utf-8",
    )
    (root / "macros/active.sql").write_text(
        "{% macro hub__active() %}"
        "{{ ref('macro_input') }} {{ source('macro_source', 'input') }}"
        "{% endmacro %}\n",
        encoding="utf-8",
    )
    (root / "models/intermediate/resources.yml").write_text(
        "version: 2\nsources:\n  - name: macro_source\n    tables:\n      - name: input\n",
        encoding="utf-8",
    )

    bundle = assemble_dbt_bundle(
        root,
        [_contract(macros=("hub__active",)), _contract("macro_input")],
        active_contract_names=("conformed",),
        known_resources=("stg_source",),
    )

    assert bundle.model_names == {"conformed", "macro_input"}
    assert "models/intermediate/macro_input.sql" in bundle.artifacts
    resources = yaml.safe_load(bundle.artifacts["models/intermediate/resources.yml"])
    assert [item["name"] for item in resources["sources"]] == ["macro_source"]


def test_scoped_bundle_follows_transitive_macro_dependencies(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "macros/active.sql").write_text(
        "{% macro hub__active(value) %}{{ hub__helper(value) }}{% endmacro %}\n",
        encoding="utf-8",
    )
    (root / "macros/helper.sql").write_text(
        "{% macro hub__helper(value) %}lower({{ value }}){% endmacro %}\n",
        encoding="utf-8",
    )

    bundle = assemble_dbt_bundle(
        root,
        [_contract(macros=("hub__active",))],
        active_contract_names=("conformed",),
        known_resources=("stg_source",),
    )

    assert bundle.macro_names == {"hub__active", "hub__helper"}
    assert "macros/active.sql" in bundle.artifacts
    assert "macros/helper.sql" in bundle.artifacts


def test_scoped_bundle_rejects_dangling_supporting_artifact_ref(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "tests/conformed_grain.sql").write_text(
        "select * from {{ ref('conformed') }} join {{ ref('missing_helper') }} using (value)\n",
        encoding="utf-8",
    )

    with pytest.raises(DbtContractError, match="missing_helper"):
        assemble_dbt_bundle(
            root,
            [_contract()],
            active_contract_names=("conformed",),
            known_resources=("stg_source",),
        )
