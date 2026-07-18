# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for generated dbt project validation."""

from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from kairos_ontology.cli.main import _SKILL_COVERED_COMMANDS, cli
from kairos_ontology.core.dbt_validation import DbtValidationError


def test_validate_dbt_reports_success(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "dbt"
    project.mkdir()
    manifest = project / "target" / "manifest.json"

    def fake_validate(project_dir, platform, profiles_dir=None):
        assert project_dir == project
        assert platform == "databricks"
        assert profiles_dir is None
        return SimpleNamespace(
            manifest_path=manifest,
            compile_status="environment_blocked",
            compile_message="credentials are unavailable",
        )

    monkeypatch.setattr(
        "kairos_ontology.core.dbt_validation.validate_dbt_project",
        fake_validate,
    )
    result = CliRunner().invoke(
        cli,
        [
            "validate-dbt",
            "--platform",
            "databricks",
            "--project-dir",
            str(project),
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    assert "deps and parse passed" in result.output
    assert "environment-blocked" in result.output


def test_validate_dbt_surfaces_validation_error(tmp_path: Path, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise DbtValidationError("parse", "dbt parse failed")

    monkeypatch.setattr(
        "kairos_ontology.core.dbt_validation.validate_dbt_project",
        fail,
    )
    result = CliRunner().invoke(
        cli,
        [
            "validate-dbt",
            "--platform",
            "fabric",
            "--project-dir",
            str(tmp_path),
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 1
    assert "dbt parse failed" in result.output


def test_validate_dbt_is_skill_gated() -> None:
    assert _SKILL_COVERED_COMMANDS["validate-dbt"] == "kairos-execute-validate"
