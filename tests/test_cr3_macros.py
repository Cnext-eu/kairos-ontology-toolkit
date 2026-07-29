# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CR3 tests for compiler-emitted Kairos dbt macros."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import jinja2
import pytest

from kairos_ontology.core.projections.dbt import (
    bind_sources,
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from tests.test_dbt_phases import _client_inputs

MACRO_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "kairos_ontology"
    / "templates"
    / "dbt"
    / "macros"
)
NEW_MACROS = (
    "kairos_clean_sentinel",
    "kairos_normalize_key",
    "kairos_survivor",
    "kairos_source_system_label",
)


def _render_artifacts(adapter: str) -> dict[str, str]:
    base_inputs = _client_inputs()
    inputs = replace(
        base_inputs,
        target_platform=adapter,
        gold_extension=base_inputs.gold_extension if adapter == "fabric" else None,
    )
    bound = bind_sources(inputs)
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    return render_project(shaped, plan)


@pytest.mark.parametrize("macro_name", NEW_MACROS)
def test_new_macro_files_exist_and_define_macro(macro_name: str) -> None:
    path = MACRO_DIR / f"{macro_name}.sql"
    assert path.is_file()
    assert f"{{% macro {macro_name}(" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("adapter", ("fabric", "databricks"))
def test_new_macros_are_emitted_for_supported_adapters(adapter: str) -> None:
    artifacts = _render_artifacts(adapter)

    for macro_name in NEW_MACROS:
        artifact_path = f"macros/{macro_name}.sql"
        assert artifact_path in artifacts
        assert f"{{% macro {macro_name}(" in artifacts[artifact_path]


def test_macro_sql_renders_statically_when_dbt_parse_is_skipped() -> None:
    """Validate macro expansion shape without dbt adapter parsing.

    This is a static fallback: it proves the Jinja macros render portable SQL snippets,
    but it does not replace real `dbt parse` adapter validation when dbt and adapters
    are installed.
    """
    source = "\n".join(
        (MACRO_DIR / f"{name}.sql").read_text(encoding="utf-8") for name in NEW_MACROS
    )
    module = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(source).module

    assert module.kairos_clean_sentinel("raw_code", ["-", "N/A"]).strip() == (
        "NULLIF(NULLIF(raw_code, '-'), 'N/A')"
    )
    assert module.kairos_normalize_key("customer_id").strip() == (
        "NULLIF(upper(trim(customer_id)), '')"
    )
    survivor = " ".join(
        module.kairos_survivor(
            ["customer_id"], "source_priority", ["source_system", "ingest_sequence"]
        ).split()
    )
    assert survivor == (
        "row_number() over ( partition by customer_id order by source_priority asc, "
        "source_system, ingest_sequence )"
    )
    assert module.kairos_source_system_label("source_system").strip() == "trim(source_system)"


def _adapter_available(adapter: str) -> bool:
    return importlib.util.find_spec(f"dbt.adapters.{adapter}") is not None


@pytest.fixture(params=("fabric", "databricks"))
def dbt_project(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[Path, str]:
    """Create a minimal project for best-effort real dbt adapter parsing."""
    pytest.importorskip("dbt")
    dbt_command = shutil.which("dbt")
    if dbt_command is None:
        pytest.skip("dbt command is not installed; static macro rendering is tested instead")

    adapter = str(request.param)
    if not _adapter_available(adapter):
        pytest.skip(f"dbt-{adapter} adapter is not installed; static rendering is tested")

    project = tmp_path / f"cr3_{adapter}"
    profiles_dir = project / ".dbt"
    (project / "models").mkdir(parents=True)
    (project / "macros").mkdir()
    profiles_dir.mkdir()
    (project / "dbt_project.yml").write_text(
        "name: cr3_macros\nversion: '1.0'\nprofile: cr3_macros\nmodel-paths: ['models']\n"
        "macro-paths: ['macros']\nmodels:\n  cr3_macros:\n    +materialized: view\n",
        encoding="utf-8",
    )
    for macro_name in NEW_MACROS:
        (project / "macros" / f"{macro_name}.sql").write_text(
            (MACRO_DIR / f"{macro_name}.sql").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (project / "models" / "cr3_macro_probe.sql").write_text(
        "select\n"
        "  {{ kairos_clean_sentinel('raw_code', ['-', 'N/A']) }} as cleaned_code,\n"
        "  {{ kairos_normalize_key('customer_id') }} as normalized_key,\n"
        "  {{ kairos_source_system_label('source_system') }} as source_label,\n"
        "  {{ kairos_survivor(['customer_id'], 'source_priority', "
        "['source_system', 'ingest_sequence']) }} as survivor_rank\n"
        "from (select ' a ' as customer_id, '-' as raw_code, 'crm' as source_system, "
        "1 as source_priority, 1 as ingest_sequence) as source_data\n",
        encoding="utf-8",
    )
    if adapter == "fabric":
        profile_output = (
            "      type: fabric\n"
            "      driver: ODBC Driver 18 for SQL Server\n"
            "      server: example.datawarehouse.fabric.microsoft.com\n"
            "      database: example\n"
            "      schema: dbo\n"
            "      authentication: CLI\n"
        )
    else:
        profile_output = (
            "      type: databricks\n"
            "      catalog: main\n"
            "      schema: silver\n"
            "      host: adb.example.azuredatabricks.net\n"
            "      http_path: /sql/1.0/warehouses/example\n"
            "      token: dapi-example\n"
        )
    (profiles_dir / "profiles.yml").write_text(
        "cr3_macros:\n  target: dev\n  outputs:\n    dev:\n" + profile_output,
        encoding="utf-8",
    )
    return project, dbt_command


def test_real_dbt_parse_for_installed_adapters(dbt_project: tuple[Path, str]) -> None:
    """Best-effort dual-adapter parse; skipped if dbt or an adapter is unavailable."""
    project, dbt_command = dbt_project
    result = subprocess.run(
        [dbt_command, "parse", "--no-version-check", "--profiles-dir", ".dbt"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
