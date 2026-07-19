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


def _contract(*, macros=(), packages=()):
    return SimpleNamespace(
        name="conformed",
        required_macros=macros,
        required_packages=packages,
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
