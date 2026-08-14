# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for dbt source()/ref() lineage tracing (issue #400)."""

from __future__ import annotations

from pathlib import Path

from kairos_ontology.core.compiler.dbt_lineage import resolve_dbt_model_contributing_sources


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_direct_source_calls_are_collected(tmp_path):
    models = tmp_path / "integration" / "transforms" / "dbt" / "models" / "intermediate"
    sql_path = models / "int_merged__party.sql"
    _write(
        sql_path,
        "select * from {{ source('crm', 'customers') }} "
        "union all select * from {{ source('erp', 'parties') }}",
    )

    sources, traceable = resolve_dbt_model_contributing_sources(tmp_path, sql_path)

    assert sources == frozenset({"crm", "erp"})
    assert traceable is True


def test_ref_targets_are_followed_transitively(tmp_path):
    models = tmp_path / "integration" / "transforms" / "dbt" / "models" / "intermediate"
    _write(
        models / "stg_crm__party.sql",
        "select * from {{ source('crm', 'customers') }}",
    )
    _write(
        models / "stg_erp__party.sql",
        "select * from {{ source('erp', 'parties') }}",
    )
    merged_path = models / "int_merged__party.sql"
    _write(
        merged_path,
        "select * from {{ ref('stg_crm__party') }} union all select * from {{ ref('stg_erp__party') }}",
    )

    sources, traceable = resolve_dbt_model_contributing_sources(tmp_path, merged_path)

    assert sources == frozenset({"crm", "erp"})
    assert traceable is True


def test_missing_ref_target_is_reported_as_non_traceable_not_guessed(tmp_path):
    models = tmp_path / "integration" / "transforms" / "dbt" / "models" / "intermediate"
    merged_path = models / "int_merged__party.sql"
    _write(
        merged_path,
        "select * from {{ source('crm', 'customers') }} "
        "union all select * from {{ ref('stg_missing__party') }}",
    )

    sources, traceable = resolve_dbt_model_contributing_sources(tmp_path, merged_path)

    # crm is still reported (it's real, direct evidence); the missing branch just
    # doesn't silently vanish or get guessed -- traceable flips to False instead.
    assert sources == frozenset({"crm"})
    assert traceable is False


def test_relative_sql_path_is_resolved_against_hub_root(tmp_path):
    models = tmp_path / "integration" / "transforms" / "dbt" / "models" / "intermediate"
    _write(models / "int_merged__party.sql", "select * from {{ source('crm', 'customers') }}")

    sources, traceable = resolve_dbt_model_contributing_sources(
        tmp_path,
        "integration/transforms/dbt/models/intermediate/int_merged__party.sql",
    )

    assert sources == frozenset({"crm"})
    assert traceable is True


def test_nonexistent_sql_path_is_non_traceable(tmp_path):
    sources, traceable = resolve_dbt_model_contributing_sources(
        tmp_path, "integration/transforms/dbt/models/does_not_exist.sql"
    )

    assert sources == frozenset()
    assert traceable is False


def test_dependency_cycle_does_not_infinite_loop(tmp_path):
    models = tmp_path / "integration" / "transforms" / "dbt" / "models" / "intermediate"
    _write(
        models / "a.sql",
        "select * from {{ source('crm', 'customers') }} union all select * from {{ ref('b') }}",
    )
    _write(models / "b.sql", "select * from {{ ref('a') }}")

    sources, traceable = resolve_dbt_model_contributing_sources(tmp_path, models / "a.sql")

    assert sources == frozenset({"crm"})
    assert traceable is True
