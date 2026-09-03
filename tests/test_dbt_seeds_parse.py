# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""#596: real-adapter parse coverage for the emitted `seeds:` config block.

`tests/test_dbt_projector.py::test_dbt_project_yml_has_seeds_config` asserts the rendered
YAML shape statically. This is the one check that would catch an adapter actually
rejecting the new block (e.g. a schema-name quoting rule) -- best-effort, skipped when
`dbt`/an adapter isn't installed, mirroring `tests/test_cr3_macros.py`'s `dbt_project`
fixture pattern.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from kairos_ontology.core.projections.dbt import (
    bind_sources,
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from tests.test_dbt_phases import _client_inputs


def _adapter_available(adapter: str) -> bool:
    return importlib.util.find_spec(f"dbt.adapters.{adapter}") is not None


def _render_artifacts(adapter: str) -> dict[str, str]:
    base_inputs = _client_inputs()
    inputs = replace(
        base_inputs,
        target_platform=adapter,
        gold_extension=base_inputs.gold_extension if adapter == "fabric-warehouse" else None,
    )
    bound = bind_sources(inputs)
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    return render_project(shaped, plan)


@pytest.fixture(params=("fabric-warehouse", "databricks"))
def seeds_dbt_project(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[Path, str]:
    """A real, template-rendered project (with the new seeds: block) plus one seed CSV."""
    pytest.importorskip("dbt")
    dbt_command = shutil.which("dbt")
    if dbt_command is None:
        pytest.skip("dbt command is not installed; seeds: block is covered by a static test")

    adapter = str(request.param)
    if not _adapter_available(adapter):
        pytest.skip(f"dbt-{adapter} adapter is not installed; seeds: block is covered statically")

    artifacts = _render_artifacts(adapter)

    project = tmp_path / f"seeds_probe_{adapter}"
    profiles_dir = project / ".dbt"
    for sub in ("models", "analyses", "tests", "seeds", "macros", "snapshots", "docs"):
        (project / sub).mkdir(parents=True)
    profiles_dir.mkdir()
    (project / "dbt_project.yml").write_text(artifacts["dbt_project.yml"], encoding="utf-8")
    for name, content in artifacts.items():
        if name.startswith("macros/"):
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    (project / "seeds" / "country_lookup.csv").write_text(
        "code,name\nBE,Belgium\nNL,Netherlands\n", encoding="utf-8"
    )
    if adapter == "fabric-warehouse":
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
        "client_project:\n  target: dev\n  outputs:\n    dev:\n" + profile_output,
        encoding="utf-8",
    )
    return project, dbt_command


def test_real_dbt_parse_accepts_seeds_config(seeds_dbt_project: tuple[Path, str]) -> None:
    """Best-effort dual-adapter parse of the emitted seeds: block; skipped without dbt."""
    project, dbt_command = seeds_dbt_project
    result = subprocess.run(
        [dbt_command, "parse", "--no-version-check", "--profiles-dir", ".dbt"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
