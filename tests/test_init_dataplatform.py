# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for init-dataplatform CLI command and dataplatform scaffold."""

import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli


@pytest.fixture(scope="module")
def mock_hub(tmp_path_factory):
    """Create a mock ontology-hub directory structure (module-scoped)."""
    tmp_path = tmp_path_factory.mktemp("hub")
    hub = tmp_path / "ontology-hub"
    hub.mkdir()
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "model" / "extensions").mkdir(parents=True)
    (hub / "model" / "mappings").mkdir(parents=True)
    (hub / "integration" / "sources" / "adminpulse").mkdir(parents=True)

    # Create a vocabulary TTL with table definitions
    vocab = hub / "integration" / "sources" / "adminpulse" / "adminpulse.vocabulary.ttl"
    vocab.write_text(
        '@prefix ap: <https://kairos.cnext.eu/source/adminpulse#> .\n'
        '@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .\n'
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        'ap:adminpulse a kairos-bronze:SourceSystem ; rdfs:label "adminpulse" .\n'
        'ap:tblClient a kairos-bronze:SourceTable ;\n'
        '    kairos-bronze:sourceSystem ap:adminpulse ;\n'
        '    kairos-bronze:tableName "tblClient" ;\n'
        '    rdfs:label "tblClient" .\n'
        'ap:tblInvoice a kairos-bronze:SourceTable ;\n'
        '    kairos-bronze:sourceSystem ap:adminpulse ;\n'
        '    kairos-bronze:tableName "tblInvoice" ;\n'
        '    rdfs:label "tblInvoice" .\n',
        encoding="utf-8",
    )

    # Create VERSION.json
    (tmp_path / "VERSION.json").write_text(
        json.dumps({"version": "1.2.0", "toolkit_version": "3.8.0"}),
        encoding="utf-8",
    )

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--allow-empty"],
        cwd=tmp_path, capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin",
         "https://github.com/TestOrg/test-ontology-hub.git"],
        cwd=tmp_path, capture_output=True,
    )

    return tmp_path


@pytest.fixture(scope="module")
def dataplatform_output(mock_hub):
    """Run init-dataplatform once and return the output directory (module-scoped)."""
    runner = CliRunner()
    dp_dir = mock_hub / "test-dataplatform"

    old_cwd = os.getcwd()
    try:
        os.chdir(mock_hub)
        result = runner.invoke(cli, [
            "init-dataplatform", "test-dataplatform",
            "--path", str(mock_hub),
        ])
    finally:
        os.chdir(old_cwd)

    assert result.exit_code == 0, result.output
    return dp_dir

    return tmp_path


def _run_in_hub(runner, mock_hub, args):
    """Run CLI command with cwd set to the mock hub directory."""
    old_cwd = os.getcwd()
    try:
        os.chdir(mock_hub)
        return runner.invoke(cli, args)
    finally:
        os.chdir(old_cwd)


class TestInitDataplatform:
    def test_creates_dbt_project(self, dataplatform_output):
        dp_dir = dataplatform_output
        assert dp_dir.exists()
        assert (dp_dir / "dbt_project.yml").exists()
        assert (dp_dir / "packages.yml").exists()
        assert (dp_dir / "pyproject.toml").exists()
        assert (dp_dir / "README.md").exists()

    def test_packages_yml_has_hub_reference(self, dataplatform_output):
        packages = (dataplatform_output / "packages.yml").read_text(encoding="utf-8")
        assert "TestOrg" in packages or "test-ontology-hub" in packages

    def test_sources_yml_populated_from_vocabulary(self, dataplatform_output):
        sources = (dataplatform_output / "models" / "_sources.yml").read_text(
            encoding="utf-8"
        )
        assert "adminpulse" in sources
        assert "tblClient" in sources
        assert "tblInvoice" in sources

    def test_extraction_macro_copied(self, dataplatform_output):
        macro = dataplatform_output / "macros" / "extract_source_schema.sql"
        assert macro.exists()
        content = macro.read_text(encoding="utf-8")
        assert "extract_source_schema" in content

    def test_pyproject_has_toolkit_dependency(self, dataplatform_output):
        pyproject = (dataplatform_output / "pyproject.toml").read_text(encoding="utf-8")
        assert "kairos-ontology-toolkit" in pyproject

    def test_version_pinned_from_hub(self, dataplatform_output):
        packages = (dataplatform_output / "packages.yml").read_text(encoding="utf-8")
        assert "v1.2.0" in packages

    def test_gitignore_created(self, dataplatform_output):
        gitignore = (dataplatform_output / ".gitignore").read_text(encoding="utf-8")
        assert "target/" in gitignore
        assert "dbt_packages/" in gitignore

    def test_copilot_instructions_created(self, dataplatform_output):
        ci = dataplatform_output / ".github" / "copilot-instructions.md"
        assert ci.exists()
        content = ci.read_text(encoding="utf-8")
        assert "Kairos Dataplatform" in content
        assert "kairos-ontology-toolkit" in content

    def test_skills_subset_created(self, dataplatform_output):
        skills_dir = dataplatform_output / ".github" / "skills"
        assert skills_dir.exists()

        expected = [
            "kairos-develop-dataplatform",
            "kairos-package-dataplatform",
            "kairos-help",
            "kairos-diagnose-status",
            "kairos-toolkit-ops",
            "SC-feature-branch",
            "SC-merge-pr",
            "SC-document",
        ]
        for skill in expected:
            skill_file = skills_dir / skill / "SKILL.md"
            assert skill_file.exists(), f"Missing skill: {skill}"
            content = skill_file.read_text(encoding="utf-8")
            assert "kairos-ontology-toolkit" in content

        # Should NOT have ontology-hub-specific skills
        assert not (skills_dir / "kairos-design-domain").exists()
        assert not (skills_dir / "kairos-execute-project").exists()


class TestInitDataplatformEdgeCases:
    def test_pyproject_includes_dbt_adapter(self, mock_hub):
        runner = CliRunner()
        dp_dir = mock_hub / "test-dp-adapter"

        _run_in_hub(runner, mock_hub, [
            "init-dataplatform", "test-dp-adapter",
            "--path", str(mock_hub),
            "--platform", "fabric-warehouse",
        ])

        pyproject = (dp_dir / "pyproject.toml").read_text(encoding="utf-8")
        assert "dbt-fabric>=1.9.0" in pyproject
        assert "dbt-core" not in pyproject

    def test_default_name_derived_from_hub(self, mock_hub, tmp_path_factory):
        runner = CliRunner()
        output_dir = tmp_path_factory.mktemp("derived")

        result = _run_in_hub(runner, mock_hub, [
            "init-dataplatform", "--path", str(output_dir),
        ])

        assert result.exit_code == 0, result.output
        assert (output_dir / "test-dataplatform").exists()

    def test_fails_if_dir_exists(self, mock_hub):
        dp_dir = mock_hub / "existing-dp"
        dp_dir.mkdir(exist_ok=True)

        runner = CliRunner()
        result = _run_in_hub(runner, mock_hub, [
            "init-dataplatform", "existing-dp",
            "--path", str(mock_hub),
        ])

        assert result.exit_code != 0
        assert "already exists" in result.output


class TestUpdateDataplatform:
    """Tests for the update command in a dataplatform repo context."""

    def test_update_detects_dataplatform(self, tmp_path):
        """Update should use dataplatform map when dbt_project.yml exists."""
        runner = CliRunner()

        # Create a minimal dataplatform repo structure
        (tmp_path / "dbt_project.yml").write_text("name: test\n", encoding="utf-8")
        github_dir = tmp_path / ".github"
        github_dir.mkdir()

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["update"])
        finally:
            os.chdir(old_cwd)

        assert result.exit_code == 0, result.output
        # Should create copilot-instructions for dataplatform
        ci = github_dir / "copilot-instructions.md"
        assert ci.exists()
        content = ci.read_text(encoding="utf-8")
        assert "Kairos Dataplatform" in content

    def test_update_creates_skill_subset(self, tmp_path):
        """Update in dataplatform repo should only create the skill subset."""
        runner = CliRunner()

        (tmp_path / "dbt_project.yml").write_text("name: test\n", encoding="utf-8")
        (tmp_path / ".github").mkdir()

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["update"])
        finally:
            os.chdir(old_cwd)

        assert result.exit_code == 0, result.output
        skills_dir = tmp_path / ".github" / "skills"

        # Dataplatform skills present
        assert (skills_dir / "kairos-help" / "SKILL.md").exists()
        assert (skills_dir / "kairos-toolkit-ops" / "SKILL.md").exists()

        # Hub-only skills absent
        assert not (skills_dir / "kairos-design-domain").exists()
        assert not (skills_dir / "kairos-execute-project").exists()
