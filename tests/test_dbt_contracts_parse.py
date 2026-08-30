# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""#630-contracts: real-adapter parse coverage for `config.contract.enforced: true`.

`tests/test_dbt_projector.py::test_schema_yaml_with_shacl` asserts the rendered
properties YAML shape statically (every Silver model now carries
``config: {contract: {enforced: true}}`` alongside a ``data_type`` for every
column). This is the one check that would catch dbt actually rejecting the
contract -- e.g. a column contracts disallows but the physical Silver plan
left untyped, or a data_type dbt's adapter doesn't recognize -- best-effort,
skipped when `dbt`/an adapter isn't installed or `dbt deps` can't reach the
package hub, mirroring `tests/test_dbt_seeds_parse.py`'s fixture pattern.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
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


def _render_artifacts() -> dict[str, object]:
    inputs = _client_inputs()
    bound = bind_sources(inputs)
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    return render_project(shaped, plan)


@pytest.fixture
def contracts_dbt_project(tmp_path: Path) -> tuple[Path, str]:
    """A real, template-rendered fabric project with the full Silver package
    (models, properties yml with contracts, macros, packages) on disk."""
    pytest.importorskip("dbt")
    dbt_command = shutil.which("dbt")
    if dbt_command is None:
        pytest.skip("dbt command is not installed; contracts are covered by a static test")
    if not _adapter_available("fabric"):
        pytest.skip("dbt-fabric adapter is not installed; contracts are covered statically")

    artifacts = _render_artifacts()

    project = tmp_path / "contracts_probe"
    profiles_dir = project / ".dbt"
    for sub in ("models", "analyses", "tests", "seeds", "macros", "snapshots", "docs"):
        (project / sub).mkdir(parents=True)
    profiles_dir.mkdir()
    for name, content in artifacts.items():
        if not isinstance(content, str):
            continue
        if name in {"dbt_project.yml", "packages.yml"} or name.startswith(
            ("models/", "macros/")
        ):
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    (profiles_dir / "profiles.yml").write_text(
        "client_project:\n"
        "  target: dev\n"
        "  outputs:\n"
        "    dev:\n"
        "      type: fabric\n"
        "      driver: ODBC Driver 18 for SQL Server\n"
        "      server: example.datawarehouse.fabric.microsoft.com\n"
        "      database: example\n"
        "      schema: dbo\n"
        "      authentication: CLI\n",
        encoding="utf-8",
    )

    deps = subprocess.run(
        [dbt_command, "deps", "--no-version-check"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if deps.returncode != 0:
        pytest.skip(
            "dbt deps could not install dbt_utils/dbt_expectations (offline/no network?): "
            + deps.stdout
            + deps.stderr
        )
    return project, dbt_command


def test_real_dbt_parse_accepts_silver_contracts(
    contracts_dbt_project: tuple[Path, str],
) -> None:
    """Best-effort real parse of the emitted Silver package with contracts enabled."""
    project, dbt_command = contracts_dbt_project
    result = subprocess.run(
        [dbt_command, "parse", "--no-version-check", "--profiles-dir", ".dbt"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
