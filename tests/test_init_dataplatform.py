# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for init-dataplatform CLI command and dataplatform scaffold."""

import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.cli.setup import _activate_profile_platform


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
        "@prefix ap: <https://kairos.cnext.eu/source/adminpulse#> .\n"
        "@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        'ap:adminpulse a kairos-bronze:SourceSystem ; rdfs:label "adminpulse" .\n'
        "ap:tblClient a kairos-bronze:SourceTable ;\n"
        "    kairos-bronze:sourceSystem ap:adminpulse ;\n"
        '    kairos-bronze:tableName "tblClient" ;\n'
        '    rdfs:label "tblClient" .\n'
        "ap:tblInvoice a kairos-bronze:SourceTable ;\n"
        "    kairos-bronze:sourceSystem ap:adminpulse ;\n"
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
        cwd=tmp_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/TestOrg/test-ontology-hub.git"],
        cwd=tmp_path,
        capture_output=True,
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
        result = runner.invoke(
            cli,
            [
                "init-dataplatform",
                "test-dataplatform",
                "--path",
                str(mock_hub),
            ],
        )
    finally:
        os.chdir(old_cwd)

    assert result.exit_code == 0, result.output
    return dp_dir


class TestActivateProfilePlatform:
    """Unit tests for the marker-driven profiles.yml.example toggle helper."""

    TEMPLATE = (
        "{PROJECT_NAME}:\n"
        "  target: dev\n"
        "  outputs:\n"
        "\n"
        "# --- PLATFORM: alpha ---\n"
        "    # Alpha docs\n"
        "    # @config\n"
        "    dev:\n"
        "      type: alpha\n"
        "      value: 1\n"
        "    # @endconfig\n"
        "      # always a comment\n"
        "# --- END PLATFORM ---\n"
        "\n"
        "# --- PLATFORM: beta ---\n"
        "    # Beta docs\n"
        "    # @config\n"
        "    # dev:\n"
        "    #   type: beta\n"
        "    #   value: 2\n"
        "    # @endconfig\n"
        "# --- END PLATFORM ---\n"
    )

    def test_activates_requested_platform_only(self):
        out = _activate_profile_platform(self.TEMPLATE, "beta")
        assert "\n      type: beta\n" in out
        assert "\n      type: alpha" not in out
        assert "#   type: alpha" in out
        assert "#   type: beta" not in out

    def test_leaves_non_config_comment_untouched_when_active(self):
        out = _activate_profile_platform(self.TEMPLATE, "alpha")
        assert "type: alpha" in out
        assert "# always a comment" in out

    def test_strips_marker_lines(self):
        out = _activate_profile_platform(self.TEMPLATE, "alpha")
        assert "@config" not in out
        assert "@endconfig" not in out
        assert "PLATFORM:" not in out

    def test_only_one_active_block(self):
        import re

        out = _activate_profile_platform(self.TEMPLATE, "beta")
        active_types = [m.group(1) for m in re.finditer(r"^\s*type:\s*(\S+)", out, re.MULTILINE)]
        assert active_types == ["beta"]


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
        assert (dp_dir / "CICD.md").exists()
        assert (dp_dir / "CONTRIBUTING.md").exists()

    def test_creates_downstream_only_models_dir_not_custom(self, dataplatform_output):
        dp_dir = dataplatform_output
        assert (dp_dir / "models" / "downstream_only").is_dir()
        assert not (dp_dir / "models" / "custom").exists()

    def test_cicd_guide_is_managed_and_describes_exact_sha_promotion(
        self, dataplatform_output
    ):
        cicd = (dataplatform_output / "CICD.md").read_text(encoding="utf-8")
        assert "kairos-ontology-toolkit:managed" in cicd
        assert "full 40-character hub commit SHA" in cicd
        assert "DEV build -> approval -> UAT build" in cicd
        assert "forward-port" in cicd
        assert "kairos-ontology update --upgrade" in cicd
        assert "powerbi-semantic-model.zip" in cicd
        assert "both `SemanticModel` and `Report`" in cicd
        assert "downstream deployment is read-only" in cicd

    def test_contributing_guide_is_managed_and_describes_branch_prefixes(
        self, dataplatform_output
    ):
        contributing = (dataplatform_output / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "kairos-ontology-toolkit:managed" in contributing
        assert "bump/hub-" in contributing
        assert "hotfix/" in contributing
        assert "kairos-ontology update --upgrade" in contributing

    def test_packages_yml_has_hub_reference(self, dataplatform_output):
        packages = (dataplatform_output / "packages.yml").read_text(encoding="utf-8")
        assert "TestOrg" in packages or "test-ontology-hub" in packages

    def test_sources_yml_populated_from_vocabulary(self, dataplatform_output):
        sources = (dataplatform_output / "models" / "_sources.yml").read_text(encoding="utf-8")
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
        skills_dir = dataplatform_output / ".claude" / "skills"
        assert skills_dir.exists()

        expected = [
            "kairos-develop-dataplatform",
            "kairos-package-dataplatform",
            "kairos-help",
            "kairos-diagnose-status",
            "kairos-toolkit-ops",
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

    def test_fabric_deploy_workflow_created(self, dataplatform_output):
        wf = dataplatform_output / ".github" / "workflows" / "deploy-powerbi-semantic-model.yml"
        assert wf.exists()
        content = wf.read_text(encoding="utf-8")
        assert "powerbi-semantic-model.zip" in content
        assert "fabric-cicd" in content
        # DD-206 #12 item 10: normalization moved into hub Gold emission; the
        # dataplatform side no longer scaffolds or invokes a mutating helper script.
        assert "package_fabric_semantic_model.py" not in content
        assert "TestOrg" in content
        assert "test-ontology-hub" in content
        assert "v1.2.0" in content

    def test_fabric_deploy_settings_example_created(self, dataplatform_output):
        cfg = dataplatform_output / ".github" / "fabric" / "deployment-settings.json.example"
        assert cfg.exists()
        content = cfg.read_text(encoding="utf-8")
        assert "FABRIC_WORKSPACE_ID" in content
        assert "test-ontology-hub" in content
        assert "v1.2.0" in content

    def test_fabric_package_script_is_not_scaffolded(self, dataplatform_output):
        """DD-206 #12 item 10: the mutating packaging helper is gone from the hub
        scaffold; TMDL/PBIP normalization now happens once, in hub Gold emission.
        """
        script = dataplatform_output / "scripts" / "package_fabric_semantic_model.py"
        assert not script.exists()


class TestInitDataplatformEdgeCases:
    def test_pyproject_includes_dbt_adapter(self, mock_hub):
        runner = CliRunner()
        dp_dir = mock_hub / "test-dp-adapter"

        _run_in_hub(
            runner,
            mock_hub,
            [
                "init-dataplatform",
                "test-dp-adapter",
                "--path",
                str(mock_hub),
                "--platform",
                "fabric-warehouse",
            ],
        )

        pyproject = (dp_dir / "pyproject.toml").read_text(encoding="utf-8")
        assert "dbt-fabric>=1.9.0" in pyproject
        assert "dbt-core" not in pyproject

    def test_default_name_derived_from_hub(self, mock_hub, tmp_path_factory):
        runner = CliRunner()
        output_dir = tmp_path_factory.mktemp("derived")

        result = _run_in_hub(
            runner,
            mock_hub,
            [
                "init-dataplatform",
                "--path",
                str(output_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        assert (output_dir / "test-dataplatform").exists()

    def test_fails_if_dir_exists(self, mock_hub):
        dp_dir = mock_hub / "existing-dp"
        dp_dir.mkdir(exist_ok=True)

        runner = CliRunner()
        result = _run_in_hub(
            runner,
            mock_hub,
            [
                "init-dataplatform",
                "existing-dp",
                "--path",
                str(mock_hub),
            ],
        )

        assert result.exit_code != 0
        assert "already exists" in result.output


class TestProfilesExamplePlatformSelection:
    """The generated .dbt/profiles.yml.example is pre-activated for --platform."""

    def _profiles_example(self, mock_hub, name, platform=None):
        runner = CliRunner()
        args = ["init-dataplatform", name, "--path", str(mock_hub)]
        if platform is not None:
            args += ["--platform", platform]
        result = _run_in_hub(runner, mock_hub, args)
        assert result.exit_code == 0, result.output
        return (mock_hub / name / ".dbt" / "profiles.yml.example").read_text(encoding="utf-8")

    @staticmethod
    def _active_types(content):
        """Return the set of dbt adapter `type:` values that are NOT commented out."""
        import re

        return {
            m.group(1)
            for line in content.splitlines()
            if (m := re.match(r"^\s*type:\s*(\S+)", line))
        }

    def test_default_platform_activates_fabric_lakehouse(self, mock_hub):
        content = self._profiles_example(mock_hub, "dp-default")
        assert self._active_types(content) == {"fabric"}
        assert '"{your-lakehouse-name}"' in content
        assert "authentication: CLI" in content

    def test_fabric_warehouse_platform_activates_warehouse_block(self, mock_hub):
        content = self._profiles_example(mock_hub, "dp-fabric-wh", platform="fabric-warehouse")
        assert self._active_types(content) == {"fabric"}
        assert '"{your-warehouse-name}"' in content
        assert "authentication: ServicePrincipal" in content

    def test_databricks_platform_activates_databricks_block(self, mock_hub):
        content = self._profiles_example(mock_hub, "dp-databricks", platform="databricks")
        assert self._active_types(content) == {"databricks"}
        assert '"{your-catalog}"' in content

    def test_generated_example_is_valid_yaml_with_one_active_target(self, mock_hub):
        import yaml

        content = self._profiles_example(mock_hub, "dp-yaml-check", platform="databricks")
        parsed = yaml.safe_load(content)
        [outputs] = [v["outputs"] for v in parsed.values()]
        assert list(outputs.keys()) == ["dev"]
        assert outputs["dev"]["type"] == "databricks"

    def test_no_leftover_marker_lines(self, mock_hub):
        content = self._profiles_example(mock_hub, "dp-markers", platform="fabric-lakehouse")
        assert "@config" not in content
        assert "PLATFORM:" not in content

    def test_example_includes_cross_platform_profiles_dir_guidance(self, mock_hub):
        content = self._profiles_example(mock_hub, "dp-guidance", platform="fabric-lakehouse")
        assert 'PowerShell: $env:DBT_PROFILES_DIR = ".dbt"' in content
        assert "bash/zsh:   export DBT_PROFILES_DIR=.dbt" in content

    def test_secret_fields_use_env_var_placeholders(self, mock_hub):
        content = self._profiles_example(mock_hub, "dp-secrets", platform="fabric-warehouse")
        assert "env_var('DBT_FABRIC_TENANT_ID')" in content
        assert "env_var('DBT_FABRIC_CLIENT_ID')" in content
        assert "env_var('DBT_FABRIC_CLIENT_SECRET')" in content

        dbx_content = self._profiles_example(mock_hub, "dp-secrets-dbx", platform="databricks")
        assert "env_var('DBT_DATABRICKS_TOKEN')" in dbx_content


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
        cicd = tmp_path / "CICD.md"
        assert cicd.exists()
        assert "kairos-ontology-toolkit:managed" in cicd.read_text(encoding="utf-8")

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
        skills_dir = tmp_path / ".claude" / "skills"

        # Dataplatform skills present
        assert (skills_dir / "kairos-help" / "SKILL.md").exists()
        assert (skills_dir / "kairos-toolkit-ops" / "SKILL.md").exists()

        # Hub-only skills absent
        assert not (skills_dir / "kairos-design-domain").exists()
        assert not (skills_dir / "kairos-execute-project").exists()
