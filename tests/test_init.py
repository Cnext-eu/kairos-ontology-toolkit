# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the kairos-ontology init and new-repo CLI commands."""

import json
import subprocess
from pathlib import Path

import pytest
from unittest import mock
from click.testing import CliRunner
from kairos_ontology.cli.main import (
    cli,
    _slugify,
    _stamp_managed,
    _get_managed_version,
    _managed_scaffold_map,
    _tag_to_version,
    _whl_url,
    _resolve_channel,
)
from kairos_ontology.cli.shared import (
    _HUB_WORKFLOW_SOURCES,
    _RETIRED_MANAGED_SCAFFOLD_FILES,
    _RETIRED_SCAFFOLD_DIRECTORIES,
    _SCAFFOLD_DIR,
    _V5_HUB_DIRECTORIES,
    _V5_OUTPUT_DIRECTORIES,
)
from kairos_ontology.core.conformance_artifact import check_discovery_gate
from kairos_ontology.core.hub_inspection import gather_hub_input_snapshot
from kairos_ontology.core.next_actions import InputStatus

V5_SCAFFOLD_DIRECTORIES = {
    "model/ontologies",
    "model/shapes",
    "businessdiscovery",
    "businessdiscovery/_extractions",
    "decisions",
    "integration/bindings",
    "integration/discovery",
    "integration/discovery/bi",
    "integration/sources",
    "integration/transforms/dbt/models",
    "integration/transforms/dbt/macros",
    "integration/transforms/dbt/tests",
    "integration/transforms/dbt/seeds",
}

# Derived/emitted output lives under the sibling publish root, not the hub.
V5_PUBLISH_DIRECTORIES = {
    "medallion/dbt",
    "powerbi",
    "neo4j",
    "azure-search",
    "a2ui",
    "prompt",
    "reports/details",
    "architecture/ddd",
    "architecture/erd",
    "mdm",
}

RETIRED_V5_PATHS = {
    "model/extensions",
    "model/mappings",
    "model/planning",
    "model/governance",
    "integration/preparation",
    "integration/transforms/dbt/evidence",
    "claims",
    "readiness",
    "evidence",
    ".sessions-projection",
    ".sessions-design-import",
    ".sessions-design",
    ".kairos-state",
}


def _assert_v5_hub_contract(hub: Path) -> None:
    for relative in V5_SCAFFOLD_DIRECTORIES:
        assert (hub / relative).is_dir(), relative
    publish_root = hub.parent / "ontology-hub-publish"
    for relative in V5_PUBLISH_DIRECTORIES:
        assert (publish_root / relative).is_dir(), relative
    for relative in RETIRED_V5_PATHS:
        assert not (hub / relative).exists(), relative

    assert (hub / "integration/bindings/README.md").is_file()
    assert (hub / "model/shapes/README.md").is_file()
    assert (hub / "decisions/README.md").is_file()
    assert (hub / "decisions/HUB-DD-template.md.template").is_file()
    assert (hub / "decisions/index.md").is_file()
    feedback = hub.parent / ".import" / "modeling" / "feedback"
    assert (feedback / "README.md").is_file()
    assert (feedback / "FEEDBACK-template.md.template").is_file()
    assert (feedback / "index.md").is_file()
    assert (hub / "catalog-v001.xml").is_file()
    assert (hub / "kairos.yaml").is_file()
    cicd = hub.parent / "CICD.md"
    assert cicd.is_file()
    assert _get_managed_version(cicd.read_text(encoding="utf-8")) is not None
    contributing = hub.parent / "CONTRIBUTING.md"
    assert contributing.is_file()
    assert _get_managed_version(contributing.read_text(encoding="utf-8")) is not None
    assert not (hub / "model/shapes/kairos-prep-shapes.shacl.ttl").exists()
    assert not (hub / "model/shapes/kairos-ext-shapes.shacl.ttl").exists()
    assert not (hub / "model/shapes/kairos-map-shapes.shacl.ttl").exists()


def test_v5_scaffold_directory_contract_is_exact():
    assert set(_V5_HUB_DIRECTORIES) == V5_SCAFFOLD_DIRECTORIES
    assert set(_V5_OUTPUT_DIRECTORIES) == V5_PUBLISH_DIRECTORIES


def test_init_creates_hub_structure(tmp_path):
    """init should create the standard hub directory structure."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--domain", "order"]
            )
            assert result.exit_code == 0

            # Check ontology-hub directories
            hub = Path("ontology-hub")
            _assert_v5_hub_contract(hub)
            assert Path("ontology-hub/integration/transforms/dbt/README.md").is_file()

            # Business discovery (DD-048/DD-056): glossary under hub, .import at repo root
            assert Path("ontology-hub/businessdiscovery").is_dir()
            assert Path(".import/businessdiscovery").is_dir()
            # .import must NOT live under ontology-hub
            assert not Path("ontology-hub/.import").exists()

            # Check README files
            assert Path("ontology-hub/model/ontologies/README.md").is_file()
            assert Path("ontology-hub/model/shapes/README.md").is_file()
            config = Path("ontology-hub/kairos.yaml").read_text(encoding="utf-8")
            assert "version: 5" in config
            assert "adapter: fabric-warehouse" in config
            assert "default_domain: order" in config

            # Check skills installed
            assert Path(".claude/skills/kairos-setup-config/SKILL.md").is_file()
            assert Path(".claude/skills/kairos-design-domain/SKILL.md").is_file()
            assert Path(".claude/skills/kairos-design-discovery/SKILL.md").is_file()
            assert Path(".claude/skills/kairos-execute-validate/SKILL.md").is_file()
            assert Path(".claude/skills/kairos-execute-project/SKILL.md").is_file()
            assert Path(".claude/skills/kairos-develop-dbt-transformation/SKILL.md").is_file()

            # Check copilot instructions
            assert Path(".github/copilot-instructions.md").is_file()
            env_example = Path(".env.example").read_text(encoding="utf-8")
            assert "KAIROS_DBT_CORE_VERSION=>=1.9,<1.10" in env_example
            pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
            assert "flatfile = [" in pyproject
            assert "kairos-ontology-toolkit[flatfile]" in pyproject
            assert "dbt-validate-fabric = [" in pyproject
            assert "dbt-validate-databricks = [" in pyproject

            # No submodule calls (reference models are a pip package, not a submodule)
            call_args_list = [call.args[0] for call in mock_run.call_args_list]
            submodule_calls = [c for c in call_args_list if "submodule" in c]
            assert len(submodule_calls) == 0

            # Check starter ontology
            assert Path("ontology-hub/model/ontologies/order.ttl").is_file()
            content = Path("ontology-hub/model/ontologies/order.ttl").read_text(encoding="utf-8")
            assert "owl:Ontology" in content
            assert "order" in content

            # Check catalog file
            assert Path("ontology-hub/catalog-v001.xml").is_file()
            cat_content = Path("ontology-hub/catalog-v001.xml").read_text(encoding="utf-8")
            assert "urn:oasis:names:tc:entity:xmlns:xml:catalog" in cat_content
            # The catalog must NOT contain a <nextCatalog> element (DD-158).
            # Reference models are resolved from the installed package at runtime.
            import xml.etree.ElementTree as ET
            root = ET.fromstring(cat_content)
            for child in root:
                assert child.tag.split("}")[-1] != "nextCatalog"
            assert "test.com" in cat_content


def test_init_without_domain(tmp_path):
    """init without --domain should still create the structure but no starter ontology."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0

            assert Path("ontology-hub/model/ontologies").is_dir()
            assert Path(".claude/skills/kairos-setup-config/SKILL.md").is_file()
            # Only _foundation.ttl + _master.ttl should exist (no domain starter)
            ttl_files = sorted(Path("ontology-hub/model/ontologies").glob("*.ttl"))
            assert len(ttl_files) == 2
            assert [f.name for f in ttl_files] == ["_foundation.ttl", "_master.ttl"]


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("databricks", "adapter: databricks"),
        ("fabric-warehouse", "adapter: fabric-warehouse"),
        # A deprecated spelling on the flag still lands as the canonical id in the file,
        # so a hub is never born carrying the ambiguous name (DD-215).
        ("fabric", "adapter: fabric-warehouse"),
    ],
)
def test_init_writes_the_selected_adapter(tmp_path, flag: str, expected: str):
    """Before DD-215 every hub was born `fabric` with no flag to change it."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--adapter", flag]
            )
            assert result.exit_code == 0, result.output
            config = Path("ontology-hub/kairos.yaml").read_text(encoding="utf-8")
            assert expected in config


def test_init_rejects_fabric_lakehouse(tmp_path):
    """Lakehouse is Spark SQL; scaffolding it would promise a profile we do not have."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli, ["init", "--company-domain", "test.com", "--adapter", "fabric-lakehouse"]
        )
        assert result.exit_code != 0


def test_init_scaffold_template_only_discovery_is_missing_end_to_end(tmp_path):
    """Issue #288: a freshly-scaffolded hub's only businessdiscovery/ file is init's own
    glossary-template.ttl — that is a scaffold template, not authored evidence. Pin the
    end-to-end property against the real scaffold (not a hand-built fixture) so a future
    rename of the scaffold file cannot silently reintroduce the bug: both the advisory
    `next` snapshot (hub_inspection.gather_hub_input_snapshot) and the hard DD-148 gate
    (conformance_artifact.check_discovery_gate) must agree that discovery hasn't happened.
    """
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--domain", "order"]
            )
            assert result.exit_code == 0

            hub = Path("ontology-hub").resolve()
            assert (hub / "businessdiscovery" / "glossary-template.ttl").is_file()

            snapshot = gather_hub_input_snapshot(hub, run_compile=False)
            assert snapshot.discovery is InputStatus.MISSING

            gate_errors = check_discovery_gate(hub)
            assert gate_errors != []


def test_init_authored_discovery_ttl_flips_snapshot_and_gate_to_satisfied(tmp_path):
    """Counterpart to the MISSING case above: once a real (non-template) discovery .ttl
    exists alongside the scaffold template, both the advisory snapshot and the hard gate
    must report discovery as present/satisfied.
    """
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--domain", "order"]
            )
            assert result.exit_code == 0

            hub = Path("ontology-hub").resolve()
            (hub / "businessdiscovery" / "test-glossary.ttl").write_text(
                "@prefix : <urn:x> .\n", encoding="utf-8"
            )

            snapshot = gather_hub_input_snapshot(hub, run_compile=False)
            assert snapshot.discovery is InputStatus.PRESENT

            assert check_discovery_gate(hub) == []


def test_init_no_overwrite_without_force(tmp_path):
    """init should skip existing files unless --force is set."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Run once
            runner.invoke(cli, ["init", "--company-domain", "test.com", "--domain", "customer"])
            # Modify the ontology to detect if it gets overwritten
            marker = "# MARKER"
            Path("ontology-hub/model/ontologies/customer.ttl").write_text(marker, encoding="utf-8")

            # Run again without --force
            result = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--domain", "customer"]
            )
            assert result.exit_code == 0
            assert (
                Path("ontology-hub/model/ontologies/customer.ttl").read_text(encoding="utf-8")
                == marker
            )


def test_init_force_overwrites(tmp_path):
    """init --force should overwrite existing files."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--company-domain", "test.com", "--domain", "customer"])
            Path("ontology-hub/model/ontologies/customer.ttl").write_text(
                "# MARKER", encoding="utf-8"
            )

            result = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--domain", "customer", "--force"]
            )
            assert result.exit_code == 0
            content = Path("ontology-hub/model/ontologies/customer.ttl").read_text(encoding="utf-8")
            assert "owl:Ontology" in content


# ---------------------------------------------------------------------------
# nested-hub refusal (DD-062)
# ---------------------------------------------------------------------------


def test_init_refuses_to_nest_inside_existing_hub(tmp_path, monkeypatch):
    """init from a content subdir of a split-layout hub must refuse, not nest.

    Regression for the case where `init` treated the content root as a fresh
    repo root and scaffolded an entire second hub inside it, including a
    ``pyproject.toml`` pinning a different toolkit version than the real
    repo-root pin.
    """
    runner = CliRunner()
    hub_root = tmp_path / "cldn-ontology-hub"
    content_root = hub_root / "ontology-hub" / "model" / "ontologies"
    content_root.mkdir(parents=True)
    (hub_root / "pyproject.toml").write_text(
        '[project]\nname = "cldn-ontology-hub"\n\n[tool.kairos]\nchannel = "preview"\n',
        encoding="utf-8",
    )

    content_hub = hub_root / "ontology-hub"
    monkeypatch.chdir(content_hub)
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(cli, ["init", "--company-domain", "cldn.com"])

    assert result.exit_code != 0
    assert "existing Kairos hub was detected" in result.output
    assert str(hub_root.resolve()) in result.output

    # Nothing was scaffolded into the content root.
    assert not (content_hub / "ontology-hub").exists()
    assert not (content_hub / "pyproject.toml").exists()
    assert not (content_hub / ".github").exists()
    assert not (content_hub / ".gitignore").exists()
    # The authoritative repo-root pin is untouched.
    assert 'channel = "preview"' in (hub_root / "pyproject.toml").read_text(encoding="utf-8")


def test_init_allowed_at_the_hub_root_itself(tmp_path):
    """Re-running init at an existing hub *root* stays supported (backfill).

    In package mode (DD-158), there is no clone step — the package is already
    installed. A second init should simply detect the existing hub and refresh
    scaffold files without error.
    """
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            first = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert first.exit_code == 0, first.output

            # cwd is now a managed root (pyproject.toml carries the toolkit pin).
            second = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert second.exit_code == 0, second.output
            assert "existing Kairos hub was detected" not in second.output


# ---------------------------------------------------------------------------
# _slugify helper
# ---------------------------------------------------------------------------


def test_slugify_basic():
    assert _slugify("contoso") == "contoso-ontology-hub"


def test_slugify_with_spaces():
    assert _slugify("Acme Logistics") == "acme-logistics-ontology-hub"


def test_slugify_already_suffixed():
    assert _slugify("contoso-ontology-hub") == "contoso-ontology-hub"


def test_slugify_special_chars():
    assert _slugify("Northwind Traders!") == "northwind-traders-ontology-hub"


# ---------------------------------------------------------------------------
# new-repo command
# ---------------------------------------------------------------------------


def test_new_repo_creates_full_structure(tmp_path):
    """new-repo should create a complete repo directory with all scaffolding."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output

    repo = tmp_path / "contoso-ontology-hub"
    assert repo.is_dir()

    # Hub structure
    _assert_v5_hub_contract(repo / "ontology-hub")
    assert (repo / "ontology-hub" / "integration" / "transforms" / "dbt" / "README.md").is_file()
    config = (repo / "ontology-hub" / "kairos.yaml").read_text(encoding="utf-8")
    assert config.startswith("version: 5\nname: contoso-ontology-hub\n")
    assert "adapter: fabric-warehouse" in config
    assert "modes_served" in config  # documented as a commented template field

    # Business discovery (DD-048/DD-056): glossary under hub, .import at repo root
    assert (repo / "ontology-hub" / "businessdiscovery").is_dir()
    assert (repo / ".import" / "businessdiscovery").is_dir()
    assert not (repo / "ontology-hub" / ".import").exists()

    # No submodule — reference models are a pip package (DD-158)
    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    submodule_calls = [c for c in call_args_list if "submodule" in c and "add" in c]
    assert len(submodule_calls) == 0

    # Copilot
    assert (repo / ".github" / "copilot-instructions.md").is_file()
    assert (repo / ".claude" / "skills" / "kairos-setup-config" / "SKILL.md").is_file()
    assert (repo / ".claude" / "skills" / "kairos-design-discovery" / "SKILL.md").is_file()
    assert (
        repo / ".claude" / "skills" / "kairos-develop-dbt-transformation" / "SKILL.md"
    ).is_file()

    # Repo-level files
    assert (repo / "pyproject.toml").is_file()
    assert (repo / ".gitignore").is_file()
    assert (repo / "README.md").is_file()
    assert (repo / "CICD.md").is_file()
    assert (repo / "CONTRIBUTING.md").is_file()

    # pyproject references the toolkit
    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "kairos-ontology-toolkit" in pyproject
    assert "contoso-ontology-hub" in pyproject
    assert "dbt-validate" in pyproject
    assert '"dbt-core>=1.9,<1.10"' in pyproject
    assert '"dbt-fabric>=1.9,<1.10"' in pyproject
    assert '"dbt-databricks>=1.9,<1.10"' in pyproject
    assert "flatfile = [" in pyproject
    assert "kairos-ontology-toolkit[flatfile]" in pyproject


def test_new_repo_contributing_guide_describes_branch_prefixes(tmp_path):
    """new-repo's managed CONTRIBUTING.md should describe hub branch conventions."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(cli, ["new-repo", "contoso", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output

    contributing = (tmp_path / "contoso-ontology-hub" / "CONTRIBUTING.md").read_text(
        encoding="utf-8"
    )
    assert _get_managed_version(contributing) is not None
    assert "model/<domain>-<topic>" in contributing
    assert "hotfix/<version>-<topic>" in contributing
    assert "kairos-ontology update --upgrade" in contributing


def test_new_repo_publish_gitignore_allows_release_relevant_output(tmp_path):
    """new-repo's .gitignore should track dbt + Power BI output, ignore the rest."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(cli, ["new-repo", "contoso", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output

    gitignore = (tmp_path / "contoso-ontology-hub" / ".gitignore").read_text(encoding="utf-8")
    assert "ontology-hub-publish/**" in gitignore
    assert "!ontology-hub-publish/medallion/dbt/**" in gitignore
    assert "!ontology-hub-publish/powerbi/**" in gitignore
    # Everything else under ontology-hub-publish/ (neo4j, azure-search, reports/details,
    # etc.) stays ignored by the blanket pattern -- no allowlist entry for them.
    assert "!ontology-hub-publish/neo4j/**" not in gitignore
    assert "!ontology-hub-publish/reports/**" not in gitignore


def test_new_repo_fails_if_dir_exists(tmp_path):
    """new-repo should refuse to overwrite an existing directory."""
    (tmp_path / "contoso-ontology-hub").mkdir()
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["new-repo", "contoso", "--path", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_new_repo_rejects_inside_git_repo(tmp_path):
    """new-repo should refuse when the target parent is a subdirectory of a git repo."""
    runner = CliRunner()
    # Simulate being inside a subdirectory of a git repo
    subdir = tmp_path / "some-project" / "src"
    subdir.mkdir(parents=True)

    def fake_run(cmd, **kwargs):
        # git rev-parse returns the repo root (parent of subdir)
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            result = mock.MagicMock(returncode=0, stdout=str(tmp_path / "some-project") + "\n")
            return result
        return mock.MagicMock(returncode=0)

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=fake_run):
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(subdir)],
        )
    assert result.exit_code != 0
    assert "inside an existing git repo" in result.output
    assert "--path" in result.output


def test_new_repo_allows_git_root_as_parent(tmp_path):
    """new-repo should allow creating a repo when parent IS the git root."""
    runner = CliRunner()

    def fake_run(cmd, **kwargs):
        # git rev-parse returns tmp_path as the root — parent == git root
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return mock.MagicMock(returncode=0, stdout=str(tmp_path) + "\n")
        return mock.MagicMock(returncode=0)

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=fake_run):
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    # Should NOT be blocked by the git check (may fail later for other reasons,
    # but the exit should not mention "inside an existing git repo")
    assert "inside an existing git repo" not in (result.output or "")


def test_new_repo_default_org_is_cnext(tmp_path):
    """new-repo should default --org to Cnext-eu."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    gh_create_call = [c for c in call_args_list if "gh" in c and "create" in c]
    assert len(gh_create_call) == 1
    assert "Cnext-eu/contoso-ontology-hub" in gh_create_call[0]


def test_new_repo_creates_git_and_pushes(tmp_path):
    """new-repo should git init, commit, then gh repo create + push."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "test-client", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    assert ["git", "init", "-b", "main"] in call_args_list
    assert ["git", "add", "."] in call_args_list
    assert ["gh", "--version"] in call_args_list
    # No submodule — reference models are a pip package (DD-158)
    submodule_calls = [c for c in call_args_list if "submodule" in c and "add" in c]
    assert len(submodule_calls) == 0
    gh_create_call = [c for c in call_args_list if "gh" in c and "create" in c]
    assert len(gh_create_call) == 1
    assert "--push" in gh_create_call[0]


def test_new_repo_without_domain(tmp_path):
    """new-repo should create structure without any starter .ttl."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "empty-client", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    repo = tmp_path / "empty-client-ontology-hub"
    assert (repo / "ontology-hub" / "model" / "ontologies").is_dir()
    # Only _foundation.ttl + _master.ttl should exist (no domain starter)
    ttl_files = sorted(
        p.name for p in (repo / "ontology-hub" / "model" / "ontologies").glob("*.ttl")
    )
    assert ttl_files == ["_foundation.ttl", "_master.ttl"]


def test_new_repo_custom_org(tmp_path):
    """new-repo --org should use the specified org for gh repo create."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            [
                "new-repo",
                "contoso",
                "--path",
                str(tmp_path),
                "--org",
                "Acme-Corp",
            ],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    gh_create_call = [c for c in call_args_list if "gh" in c and "create" in c]
    assert len(gh_create_call) == 1
    assert "Acme-Corp/contoso-ontology-hub" in gh_create_call[0]


def test_new_repo_default_private(tmp_path):
    """new-repo should default to --private."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    gh_create_call = [
        call.args[0]
        for call in mock_run.call_args_list
        if "gh" in call.args[0] and "create" in call.args[0]
    ]
    assert len(gh_create_call) == 1
    assert "--private" in gh_create_call[0]


def test_new_repo_public_flag(tmp_path):
    """new-repo --public should pass --public to gh."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path), "--public"],
        )
    assert result.exit_code == 0, result.output
    gh_create_call = [
        call.args[0]
        for call in mock_run.call_args_list
        if "gh" in call.args[0] and "create" in call.args[0]
    ]
    assert len(gh_create_call) == 1
    assert "--public" in gh_create_call[0]


# ---------------------------------------------------------------------------
# Managed-file stamping helpers
# ---------------------------------------------------------------------------


def test_stamp_managed_with_frontmatter():
    """Marker should be inserted right after YAML front-matter."""
    content = "---\nname: test\n---\n# Title\n"
    stamped = _stamp_managed(content, "1.2.3")
    assert "<!-- kairos-ontology-toolkit:managed v1.2.3 -->" in stamped
    # Marker should come after the closing ---
    lines = stamped.splitlines()
    close_idx = next(i for i in range(1, len(lines)) if lines[i] == "---")
    assert "kairos-ontology-toolkit:managed" in lines[close_idx + 1]


def test_stamp_managed_without_frontmatter():
    """Marker should be the first line when there is no front-matter."""
    content = "# Hello world\n"
    stamped = _stamp_managed(content, "2.0.0")
    assert stamped.startswith("<!-- kairos-ontology-toolkit:managed v2.0.0 -->")


def test_stamp_managed_replaces_existing():
    """Re-stamping should replace the existing marker, not add a second one."""
    content = "---\nname: x\n---\n<!-- kairos-ontology-toolkit:managed v1.0.0 -->\n# Title\n"
    stamped = _stamp_managed(content, "2.0.0")
    assert stamped.count("kairos-ontology-toolkit:managed") == 1
    assert "v2.0.0" in stamped
    assert "v1.0.0" not in stamped


def test_get_managed_version():
    """Should extract the version from the marker."""
    content = "---\nname: x\n---\n<!-- kairos-ontology-toolkit:managed v1.5.0 -->\n# Title\n"
    assert _get_managed_version(content) == "1.5.0"


def test_get_managed_version_none():
    """Should return None when no marker is present."""
    assert _get_managed_version("# Just a file\n") is None


# ---------------------------------------------------------------------------
# new-repo stamps managed files
# ---------------------------------------------------------------------------


def test_new_repo_stamps_managed_files(tmp_path):
    """new-repo should stamp copilot-instructions and skills with a version marker."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output

    repo = tmp_path / "contoso-ontology-hub"

    # copilot-instructions.md should have the marker
    ci = (repo / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert _get_managed_version(ci) is not None

    # At least one skill should be stamped
    for skill_md in (repo / ".claude" / "skills").rglob("SKILL.md"):
        content = skill_md.read_text(encoding="utf-8")
        assert _get_managed_version(content) is not None, f"{skill_md} not stamped"


# ---------------------------------------------------------------------------
# update command
# ---------------------------------------------------------------------------


def test_update_refreshes_outdated_files(tmp_path):
    """update should overwrite managed files whose version doesn't match."""
    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    # Create fake managed files with an old version marker
    for rel_path, scaffold_src in managed_map.items():
        dst = tmp_path / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        content = scaffold_src.read_text(encoding="utf-8")
        old_stamped = _stamp_managed(content, "0.0.1")
        dst.write_text(old_stamped, encoding="utf-8")

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # Copy the files into the isolated cwd
        for rel_path in managed_map:
            src = tmp_path / rel_path
            tgt = Path(td) / rel_path
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        result = runner.invoke(cli, ["update"])
    assert result.exit_code == 0, result.output
    assert "Updated" in result.output


def test_update_check_reports_without_changing(tmp_path):
    """update --check should report drift but not modify files."""
    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in managed_map.items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, "0.0.1"), encoding="utf-8")

        result = runner.invoke(cli, ["update", "--check"])

        # Files should still have the old version
        for rel_path in managed_map:
            content = (Path(td) / rel_path).read_text(encoding="utf-8")
            assert _get_managed_version(content) == "0.0.1"

    assert result.exit_code != 0  # exit 1 for CI enforcement
    assert "need updating" in result.output


def test_update_check_exit_code_nonzero_on_drift(tmp_path):
    """update --check should exit 1 when files are outdated (for CI)."""
    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in managed_map.items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, "0.0.1"), encoding="utf-8")

        result = runner.invoke(cli, ["update", "--check"])

    assert result.exit_code != 0


def _stage_current_hub_workflows(td) -> None:
    """Write every hub workflow byte-identical to its scaffold source (issue #671).

    `update --check`/`update` now report missing `.github/workflows/*.yml` as drift
    alongside managed files, so an "everything is current" fixture must include them too.
    """
    for rel_path, scaffold_rel in _HUB_WORKFLOW_SOURCES.items():
        dst = Path(td) / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(
            (_SCAFFOLD_DIR / scaffold_rel).read_text(encoding="utf-8"), encoding="utf-8"
        )


class TestClaudeSettingsReconciliation:
    """`update` classification of `.claude/settings.json` (issue #684).

    Nothing covered these branches before: every `update --check` fixture omitted the file, so
    they all took the harmless "missing" path. The platform-divergence bug therefore had no
    test that could have failed.
    """

    #: The last generation that still denied ``Read`` on ontologies/shapes, vendored rather
    #: than resolved from git: CI checks out at ``fetch-depth: 1``, so ``git show <old-sha>``
    #: is unavailable there -- a history-dependent test passes locally and fails only in CI.
    _PRE_659 = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "claude-settings-generations"
        / "04-pre-659-read-denies.json"
    )

    def _historical_settings(self) -> bytes:
        """The pre-#659 scaffold generation, as committed (LF)."""
        return self._PRE_659.read_bytes()

    def _stage(self, td, settings_bytes: bytes) -> None:
        from kairos_ontology import __version__ as ver

        for rel_path, scaffold_src in _managed_scaffold_map().items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(
                _stamp_managed(scaffold_src.read_text(encoding="utf-8"), ver), encoding="utf-8"
            )
        _stage_current_hub_workflows(td)
        settings = Path(td) / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_bytes(settings_bytes)

    @pytest.mark.parametrize("eol", ["lf", "crlf"], ids=["lf-checkout", "crlf-checkout"])
    def test_superseded_generation_is_classified_identically_on_either_line_ending(
        self, tmp_path, eol
    ):
        """The reported bug: same content, different verdict per line ending.

        A Windows checkout (`core.autocrlf=true`) and a Linux one hold byte-different but
        semantically identical files. `update --check` used to exit 1 on one and 0 on the other.
        """
        blob = self._historical_settings()
        if eol == "crlf":
            blob = blob.replace(b"\n", b"\r\n")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            self._stage(td, blob)
            result = runner.invoke(cli, ["update", "--check"])

        assert result.exit_code != 0, result.output
        assert "needs updating" in result.output
        # The report must name the change that is actually pending -- the removal of the `Read`
        # denies -- not the oldest generation's `.ttl`-extension broadening.
        assert "Read" in result.output
        assert "659" in result.output

    def test_replacement_reports_the_deny_rules_it_removes(self, tmp_path):
        """A settings.json rewrite must never be silent about which rules it drops."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            self._stage(td, self._historical_settings())
            result = runner.invoke(cli, ["update"])
            written = (Path(td) / ".claude" / "settings.json").read_text(encoding="utf-8")

        assert result.exit_code == 0, result.output
        assert "Read(./ontology-hub/model/ontologies/**/*.ttl)" in result.output
        assert "Read(" not in written  # the #659 fix landed

    def test_genuinely_customized_settings_are_left_alone_and_do_not_fail_check(self, tmp_path):
        """An unrecognized hash is an advisory, not drift -- it must not flip the exit code."""
        customized = json.dumps(
            {
                "permissions": {"deny": ["Grep(./ontology-hub/model/ontologies/**/*.ttl)"]},
                "env": {"HUB_LOCAL_SETTING": "1"},
            },
            indent=2,
        ).encode("utf-8")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            self._stage(td, customized)
            result = runner.invoke(cli, ["update", "--check"])
            after = (Path(td) / ".claude" / "settings.json").read_bytes()

        assert result.exit_code == 0, result.output
        assert "left alone" in result.output
        assert after == customized


def test_update_check_exit_code_zero_when_current(tmp_path):
    """update --check should exit 0 when everything is up to date."""
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in managed_map.items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, ver), encoding="utf-8")
        _stage_current_hub_workflows(td)

        result = runner.invoke(cli, ["update", "--check"])

    assert result.exit_code == 0, result.output
    assert "up to date" in result.output


def test_update_noop_when_current(tmp_path):
    """update should report up-to-date when versions match."""
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in managed_map.items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, ver), encoding="utf-8")
        _stage_current_hub_workflows(td)
        _stage_git_hygiene(td)

        result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0, result.output
    assert "up to date" in result.output


def _stage_git_hygiene(td) -> None:
    """Copy the shipped .gitignore/.gitattributes verbatim into a fixture repo.

    `update` now creates either when absent and reports template rules an existing one
    lacks (#699), so a fixture that omits them is no longer "current".
    """
    for rel_path, template_name in (
        (".gitignore", "gitignore.template"),
        (".gitattributes", "gitattributes.template"),
    ):
        template = _SCAFFOLD_DIR / template_name
        if template.is_file():
            (Path(td) / rel_path).write_text(
                template.read_text(encoding="utf-8"), encoding="utf-8"
            )


def test_update_creates_missing_git_hygiene_files(tmp_path):
    """#699: a hub scaffolded before these existed never received them.

    `.gitignore` is written only by `init`/`new-repo` and is absent from
    `_managed_scaffold_map()`, so `update --check` reported "All managed files are up to
    date" while the local file was materially behind -- on one real hub, missing both the
    `ontology-hub-publish/**` allowlist and the `**/.import/*` block whose stated purpose
    is keeping PII-adjacent client evidence out of Git.
    """
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in _managed_scaffold_map().items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(
                _stamp_managed(scaffold_src.read_text(encoding="utf-8"), ver), encoding="utf-8"
            )
        _stage_current_hub_workflows(td)

        result = runner.invoke(cli, ["update"])

        assert result.exit_code == 0, result.output
        assert (Path(td) / ".gitattributes").is_file()
        assert (Path(td) / ".gitignore").is_file()
        assert "eol=lf" in (Path(td) / ".gitattributes").read_text(encoding="utf-8")


def test_update_check_reports_an_outdated_gitignore_instead_of_claiming_success(tmp_path):
    """The part that hurt most: silence (#699).

    An existing file is never overwritten -- a hub is expected to add its own rules --
    but the gap must be reported, and must not exit 0.
    """
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in _managed_scaffold_map().items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(
                _stamp_managed(scaffold_src.read_text(encoding="utf-8"), ver), encoding="utf-8"
            )
        _stage_current_hub_workflows(td)
        _stage_git_hygiene(td)
        # A hub predating the `.import` block: its own rules kept, the template's lost.
        (Path(td) / ".gitignore").write_text(".env\n__pycache__/\n", encoding="utf-8")

        result = runner.invoke(cli, ["update", "--check"])

        assert result.exit_code == 1, result.output
        assert ".gitignore is missing" in result.output
        assert "**/.import/*" in result.output
        assert "up to date" not in result.output


def test_update_never_overwrites_a_customized_gitignore(tmp_path):
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in _managed_scaffold_map().items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(
                _stamp_managed(scaffold_src.read_text(encoding="utf-8"), ver), encoding="utf-8"
            )
        _stage_current_hub_workflows(td)
        _stage_git_hygiene(td)
        gitignore = Path(td) / ".gitignore"
        gitignore.write_text(
            gitignore.read_text(encoding="utf-8") + "\n# hub-specific\nlocal-scratch/\n",
            encoding="utf-8",
        )

        runner.invoke(cli, ["update"])

        assert "local-scratch/" in gitignore.read_text(encoding="utf-8")


def test_update_check_reports_missing_workflow_as_drift(tmp_path):
    """update --check must not report success while a scaffolded workflow is missing (#671)."""
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in managed_map.items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, ver), encoding="utf-8")
        _stage_current_hub_workflows(td)
        # Simulate a repo scaffolded before pr-validate.yml existed.
        (Path(td) / ".github" / "workflows" / "pr-validate.yml").unlink()

        result = runner.invoke(cli, ["update", "--check"])

    assert result.exit_code != 0
    assert "scaffolded workflow(s) missing" in result.output
    assert ".github/workflows/pr-validate.yml" in result.output


def test_update_reports_missing_workflow_without_creating_it(tmp_path):
    """Plain `update` must still surface a missing workflow it did not create (#671)."""
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in managed_map.items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, ver), encoding="utf-8")
        _stage_current_hub_workflows(td)
        (Path(td) / ".github" / "workflows" / "pr-validate.yml").unlink()

        result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0, result.output
    assert "scaffolded workflow(s) missing" in result.output
    assert ".github/workflows/pr-validate.yml" in result.output
    assert not (Path(td) / ".github" / "workflows" / "pr-validate.yml").is_file()


def test_update_creates_missing_files(tmp_path):
    """update should create managed files that don't exist locally."""
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        result = runner.invoke(cli, ["update"])

        assert result.exit_code == 0, result.output
        assert "Created" in result.output

        # Verify the files were actually created with correct version stamp
        for rel_path in managed_map:
            created_file = Path(td) / rel_path
            assert created_file.is_file(), f"Expected {rel_path} to be created"
            content = created_file.read_text(encoding="utf-8")
            assert _get_managed_version(content) == ver


def test_update_check_reports_missing_as_drift(tmp_path):
    """update --check should report missing files as drift (exit 1) without creating."""
    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        result = runner.invoke(cli, ["update", "--check"])

        assert result.exit_code != 0
        assert "missing" in result.output

        # Files should NOT have been created
        for rel_path in managed_map:
            assert not (Path(td) / rel_path).is_file()


def test_update_creates_new_skill_file(tmp_path):
    """update should create a newly added skill while leaving existing ones."""
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    managed_map = _managed_scaffold_map()
    skill_paths = [p for p in managed_map if "skills/" in p]

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # Pre-populate all but the last skill (simulating a hub missing one)
        for rel_path, scaffold_src in managed_map.items():
            if rel_path == skill_paths[-1]:
                continue  # skip one skill
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, ver), encoding="utf-8")

        result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0, result.output
    assert "Created 1 new file" in result.output
    assert skill_paths[-1] in result.output


def test_update_removes_stale_managed_skill(tmp_path):
    """update should remove a managed skill that is no longer in the scaffold."""
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # Populate all current managed files at the current version
        for rel_path, scaffold_src in managed_map.items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, ver), encoding="utf-8")

        # Add a stale managed skill (not in scaffold)
        stale_dir = Path(td) / ".claude" / "skills" / "kairos-old-skill"
        stale_dir.mkdir(parents=True, exist_ok=True)
        stale_content = _stamp_managed("# Old Skill\nThis is stale.", "1.0.0")
        (stale_dir / "SKILL.md").write_text(stale_content, encoding="utf-8")

        result = runner.invoke(cli, ["update"])

        # Stale skill directory should be deleted
        assert not stale_dir.exists()

    assert result.exit_code == 0, result.output
    assert "Removed 1 stale" in result.output
    assert "kairos-old-skill" in result.output


def test_update_check_reports_stale_managed_skill(tmp_path):
    """update --check should report stale managed skills without removing them."""
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in managed_map.items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, ver), encoding="utf-8")

        # Add a stale managed skill
        stale_dir = Path(td) / ".claude" / "skills" / "kairos-old-skill"
        stale_dir.mkdir(parents=True, exist_ok=True)
        stale_content = _stamp_managed("# Old Skill\nThis is stale.", "1.0.0")
        (stale_dir / "SKILL.md").write_text(stale_content, encoding="utf-8")

        result = runner.invoke(cli, ["update", "--check"])

        # Stale skill should NOT be deleted (check mode)
        assert stale_dir.exists()

    assert result.exit_code != 0  # exit 1 — stale counts as drift
    assert "stale" in result.output.lower()
    assert "kairos-old-skill" in result.output


def test_update_removes_only_known_retired_scaffold_assets(tmp_path):
    """update removes known retired assets but preserves edited files and user content."""
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        root = Path(td)
        stale_file = root / "ontology-hub/model/governance/release-baseline.yaml"
        stale_file.parent.mkdir(parents=True)
        stale_file.write_text("approval_status: user-approved\n", encoding="utf-8")
        stale_keep = root / "ontology-hub/.sessions-projection/.gitkeep"
        stale_keep.parent.mkdir(parents=True)
        stale_keep.write_bytes(b"")
        user_file = root / "ontology-hub/model/planning/keep-me.txt"
        user_file.parent.mkdir(parents=True)
        user_file.write_text("user-authored\n", encoding="utf-8")
        empty_state = root / "ontology-hub/.kairos-state/phases/source"
        empty_state.mkdir(parents=True)

        result = runner.invoke(cli, ["update"])

        assert result.exit_code == 0, result.output
        assert stale_file.read_text(encoding="utf-8") == "approval_status: user-approved\n"
        assert not stale_keep.exists()
        assert not empty_state.exists()
        assert user_file.read_text(encoding="utf-8") == "user-authored\n"

    assert "retired scaffold asset" in result.output


def test_update_inventory_covers_nested_retired_v4_scaffold_assets():
    expected_files = {
        "ontology-hub/integration/sources/custom-transformations/README.md",
        "ontology-hub/model/mappings/README.md",
        "ontology-hub/model/mappings/custom-transformations/README.md",
        "ontology-hub/model/planning/dbt-transformations/README.md",
    }
    expected_directories = {
        "ontology-hub/integration/sources/custom-transformations",
        "ontology-hub/model/mappings/custom-transformations",
        "ontology-hub/model/planning/dbt-transformations",
    }

    assert expected_files <= _RETIRED_MANAGED_SCAFFOLD_FILES.keys()
    assert expected_directories <= set(_RETIRED_SCAFFOLD_DIRECTORIES)


def test_update_preserves_custom_unmanaged_skill(tmp_path):
    """update should NOT remove a custom skill without the managed marker."""
    from kairos_ontology import __version__ as ver

    runner = CliRunner()
    managed_map = _managed_scaffold_map()

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        for rel_path, scaffold_src in managed_map.items():
            dst = Path(td) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = scaffold_src.read_text(encoding="utf-8")
            dst.write_text(_stamp_managed(content, ver), encoding="utf-8")

        # Add a custom skill WITHOUT managed marker
        custom_dir = Path(td) / ".claude" / "skills" / "my-custom-skill"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "SKILL.md").write_text("# My Custom Skill\nNo marker.")

        result = runner.invoke(cli, ["update"])

        # Custom skill should still exist
        assert custom_dir.exists()
        assert (custom_dir / "SKILL.md").is_file()

    assert result.exit_code == 0, result.output
    assert "my-custom-skill" not in result.output


# ---------------------------------------------------------------------------
# CI workflow scaffold
# ---------------------------------------------------------------------------


def test_new_repo_includes_workflow(tmp_path):
    """new-repo should scaffold the managed-check CI workflow."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    wf = tmp_path / "contoso-ontology-hub" / ".github" / "workflows" / "managed-check.yml"
    assert wf.is_file()
    content = wf.read_text(encoding="utf-8")
    assert "kairos-ontology update --check" in content
    # #589: an unpinned setup-uv version queries github.com's "latest release" API,
    # which 404s on GitHub Enterprise Server (astral-sh/uv doesn't exist there).
    assert "astral-sh/setup-uv@v10.0.1" in content
    assert 'version: "0.12.5"' in content
    assert "uv sync --locked" in content


def test_init_includes_workflow(tmp_path):
    """init should scaffold the managed-check CI workflow."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0
            wf = Path(".github/workflows/managed-check.yml")
            assert wf.is_file()
            content = wf.read_text(encoding="utf-8")
            assert "kairos-ontology update --check" in content
            assert "astral-sh/setup-uv@v10.0.1" in content
            assert 'version: "0.12.5"' in content
            assert "uv sync --locked" in content


def test_new_repo_includes_pr_validate_workflow(tmp_path):
    """new-repo should scaffold the DD-206 §4 pr-validate.yml PR-check workflow."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    wf = tmp_path / "contoso-ontology-hub" / ".github" / "workflows" / "pr-validate.yml"
    assert wf.is_file()
    content = wf.read_text(encoding="utf-8")
    assert "pull_request" in content
    assert "branches: [main]" in content
    assert "uv sync --locked" in content
    assert "astral-sh/setup-uv@v10.0.1" in content
    assert 'version: "0.12.5"' in content


def test_init_pr_validate_workflow_content(tmp_path):
    """init's pr-validate.yml must validate, regenerate-and-diff, then check the dbt package.

    DD-206 §4 ("Hub pull request"): restore deps, validate ontology/SHACL,
    compile-check every bound domain, regenerate the tracked publish output and
    fail on drift, then validate the assembled dbt package.
    """
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0
            wf = Path(".github/workflows/pr-validate.yml")
            assert wf.is_file()
            content = wf.read_text(encoding="utf-8")

            assert "on:" in content
            assert "pull_request:" in content
            assert "branches: [main]" in content

            # Ontology/SHACL/binding validation.
            assert "kairos-ontology validate " in content or "kairos-ontology validate \\" in content
            assert "kairos-ontology compile --all --check --format json" in content

            # Regenerate tracked publish output and fail on drift (only the two
            # tracked lanes under ontology-hub-publish/, per gitignore.template).
            assert "kairos-ontology compile --all --emit --confirm-emit" in content
            assert "git diff --exit-code" in content
            assert "ontology-hub-publish/medallion/dbt" in content
            assert "ontology-hub-publish/powerbi" in content

            # Assembled dbt package validation: the FULL offline gate, not
            # --structural-only, which stops after the ref() scan and so cannot detect a
            # project dbt refuses to parse (#686). Still credential-free -- only the
            # final `dbt compile` wants a warehouse, and it degrades.
            assert "kairos-ontology validate-dbt" in content
            # The invocation, not the prose: the comment above the step explains why the
            # flag was dropped and legitimately names it.
            assert "validate-dbt --structural-only" not in content
            assert "dbt_validate_extra" in content  # extra resolved, never composed

            # The drift gate must fail closed: `git diff --exit-code -- <path>` exits 0
            # when nothing at that path is tracked (#699).
            assert "is not tracked" in content

            # This workflow runs alongside managed-check.yml, not instead of it.
            assert "alongside" in content


def test_init_release_workflow_uses_supported_project_options(tmp_path):
    """The release workflow must not use retired release-evaluation options."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0
            wf = Path(".github/workflows/release-projections.yml")
            assert wf.is_file()
            content = wf.read_text(encoding="utf-8")
            assert "--strict" not in content
            assert "compile-plan-only consumers" in content
            assert content.count('find "ontology-hub-publish/medallion/dbt"') == 2
            assert content.count("-type f -print -quit | grep -q .") == 1
            # DD-206 §8: the hub release ships powerbi-semantic-model.zip beside the
            # dbt artifact for every Gold-configured domain, checksummed, with no
            # dangling archive when no domain is Gold-configured.
            assert "powerbi-semantic-model.zip" in content
            assert "POWERBI_PACKAGE" in content
            assert "package-powerbi-release" in content
            assert "powerbi-semantic-model.zip.sha256" in content
            assert "persist-credentials: false" in content
            assert 'find "ontology-hub-publish/medallion/dbt"' in content
            assert "-type l -print -quit | grep -q ." in content
            assert "rm -f dbt-artifacts.zip" in content
            assert content.index("-type l -print -quit") < content.index("-type f -print -quit")
            # DD-206: the release workflow must verify already-tracked bytes at the
            # tagged commit, never regenerate different bytes after tagging. The old
            # "rm -rf ontology-hub-publish/medallion/dbt" + "compile --all --emit
            # --confirm-emit" regenerate step is gone; pr-validate.yml (the hub PR
            # workflow) is what regenerates and diffs that output, before merge.
            assert "rm -rf ontology-hub-publish/medallion/dbt" not in content
            assert "compile --all --emit" not in content
            assert "validate-dbt" in content
            assert "validate-dbt --structural-only" not in content  # full gate (#686)
            assert "read-only, no regeneration" in content
            # #589: same GHES setup-uv/lockfile fixes as managed-check.yml.
            assert "astral-sh/setup-uv@v10.0.1" in content
            assert 'version: "0.12.5"' in content
            assert "uv sync --locked" in content


def test_init_copilot_setup_steps_workflow_avoids_ghes_and_lockfile_failures(tmp_path):
    """#589: copilot-setup-steps.yml must not use retired/broken CI patterns.

    ``setup-uv@v4`` with no pinned version 404s against GitHub Enterprise Server's
    API when it looks up the "latest" uv release. ``npm ci`` hard-fails because the
    scaffold never ships or generates a ``package-lock.json`` alongside the
    scaffolded ``package.json``. Node 20 is deprecated on GitHub-hosted runners.
    """
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0
            wf = Path(".github/workflows/copilot-setup-steps.yml")
            assert wf.is_file()
            content = wf.read_text(encoding="utf-8")
            assert "astral-sh/setup-uv@v10.0.1" in content
            assert 'version: "0.12.5"' in content
            assert "uv sync --locked" in content
            assert 'node-version: "22"' in content
            assert 'node-version: "20"' not in content
            assert "npm install" in content
            assert "npm ci" not in content


def test_scaffold_emit_invocations_pass_confirm_emit():
    """Every scaffolded ``compile ... --emit`` must also pass ``--confirm-emit`` (#598).

    ``--emit`` gained a mandatory ``--confirm-emit`` companion in #264, but the
    scaffolded release workflow kept the bare form for three weeks: no test asserted
    that a template's CLI invocations were ones the CLI would actually accept, so a
    generated hub's release loop failed on its first domain. This closes that class of
    bug for the whole scaffold tree, not just the one file that regressed.
    """
    import kairos_ontology.scaffold as scaffold_pkg

    scaffold_root = Path(next(iter(scaffold_pkg.__path__)))
    offenders = []
    for path in sorted(scaffold_root.rglob("*")):
        # ``.template`` counts too, and did not before: ``Path("README.md.template").suffix``
        # is ``.template``, so every ``*.md.template`` in the scaffold -- including the hub
        # README, which is the first CLI a new operator copies -- was exempt from this check
        # and shipped a bare ``--emit`` the CLI rejects (#739).
        suffixes = {s.lower() for s in path.suffixes[-2:]}
        if not path.is_file() or not suffixes & {".yml", ".yaml", ".md", ".sh"}:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            # Only real invocations: prose *about* the flag ("do not call `compile
            # --emit` from a design skill") is correct as written and must not trip this.
            if "kairos-ontology compile" not in line or "--emit" not in line:
                continue
            if "--confirm-emit" not in line:
                offenders.append(f"{path.relative_to(scaffold_root)}:{lineno}: {line.strip()}")
    assert not offenders, "scaffolded --emit without --confirm-emit:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# Reference models submodule
# ---------------------------------------------------------------------------


def test_new_repo_ref_models_version(tmp_path):
    """new-repo --ref-models-version should pin that version in pyproject.toml."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            [
                "new-repo",
                "contoso",
                "--path",
                str(tmp_path),
                "--ref-models-version",
                "v1.2.0",
            ],
        )
    assert result.exit_code == 0, result.output

    # The pyproject.toml should contain a referencemodels dependency pin
    repo = tmp_path / "contoso-ontology-hub"
    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "kairos-ontology-referencemodels" in pyproject


def test_new_repo_workflow_no_submodules(tmp_path):
    """new-repo workflow should NOT include submodules: true (no longer needed)."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    wf = tmp_path / "contoso-ontology-hub" / ".github" / "workflows" / "managed-check.yml"
    content = wf.read_text(encoding="utf-8")
    assert "submodules: true" not in content


# ---------------------------------------------------------------------------
# SmartCoding
# ---------------------------------------------------------------------------


def test_new_repo_never_runs_smartcoding(tmp_path):
    """new-repo must not run any update-smartcoding-latest.ps1 script (template removed)."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    pwsh_calls = [c for c in call_args_list if c[0] == "pwsh"]
    assert pwsh_calls == []
    assert not any("update-smartcoding-latest.ps1" in str(c) for c in call_args_list)
    assert not any("update-referencemodels.ps1" in str(c) for c in call_args_list)


def test_init_never_runs_smartcoding(tmp_path):
    """init must not run any update-smartcoding-latest.ps1 script (template removed)."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0

            call_args_list = [call.args[0] for call in mock_run.call_args_list]
            pwsh_calls = [c for c in call_args_list if c[0] == "pwsh"]
            assert pwsh_calls == []
            assert not any("update-smartcoding-latest.ps1" in str(c) for c in call_args_list)


# ---------------------------------------------------------------------------
# Company domain, hub README, master ontology
# ---------------------------------------------------------------------------


def test_init_generates_hub_readme(tmp_path):
    """init --company-domain should create ontology-hub/README.md with company context."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "contoso.com"])
            assert result.exit_code == 0

            readme = Path("ontology-hub/README.md")
            assert readme.is_file()
            content = readme.read_text(encoding="utf-8")
            assert "contoso.com" in content
            assert "Contoso" in content
            assert "https://contoso.com/ont/" in content


def test_init_generates_managed_cicd_guide(tmp_path):
    """init should create the managed root CI/CD guide."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "contoso.com"])
            assert result.exit_code == 0, result.output

            cicd = Path("CICD.md")
            content = cicd.read_text(encoding="utf-8")
            assert _get_managed_version(content) is not None
            assert "full 40-character hub commit SHA" in content
            assert "forward-port" in content
            assert "kairos-ontology update --upgrade" in content
            assert "powerbi-semantic-model.zip" in content
            assert "archive SHA-256" in content
            assert "TMDL normalization" in content


def test_init_preserves_existing_cicd_guide_without_force(tmp_path):
    """init should not replace a pre-existing root CI/CD guide without --force."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("CICD.md").write_text("# Local CI/CD\n", encoding="utf-8")
            result = runner.invoke(cli, ["init", "--company-domain", "contoso.com"])
            assert result.exit_code == 0, result.output
            assert Path("CICD.md").read_text(encoding="utf-8") == "# Local CI/CD\n"


def test_init_generates_master_ontology(tmp_path):
    """init should create ontology-hub/model/ontologies/_master.ttl."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "contoso.com"])
            assert result.exit_code == 0

            master = Path("ontology-hub/model/ontologies/_master.ttl")
            assert master.is_file()
            content = master.read_text(encoding="utf-8")
            assert "owl:Ontology" in content
            assert "contoso.com/ont/master" in content
            assert "Contoso" in content
            # DD-072: scaffold ontology carries an editable provenance header.
            assert content.startswith("#")
            assert "kairos-ontology-toolkit" in content
            assert "safe to edit" in content.lower()


def test_init_starter_uses_company_domain(tmp_path):
    """init --domain should use the company domain in the starter ontology namespace."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "--company-domain", "acme.io", "--domain", "customer"]
            )
            assert result.exit_code == 0

            content = Path("ontology-hub/model/ontologies/customer.ttl").read_text(encoding="utf-8")
            assert "https://acme.io/ont/customer#" in content
            assert "https://acme.io/ont/customer>" in content


def test_init_requires_company_domain(tmp_path):
    """init should fail when --company-domain is not provided."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            assert result.exit_code != 0
            assert "company-domain" in result.output.lower() or "required" in result.output.lower()


def test_new_repo_generates_hub_readme(tmp_path):
    """new-repo should create ontology-hub/README.md with derived company context."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output

    repo = tmp_path / "contoso-ontology-hub"
    readme = repo / "ontology-hub" / "README.md"
    assert readme.is_file()
    content = readme.read_text(encoding="utf-8")
    assert "contoso.com" in content
    assert "Contoso" in content


def test_new_repo_generates_master_ontology(tmp_path):
    """new-repo should create ontology-hub/model/ontologies/_master.ttl."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output

    repo = tmp_path / "contoso-ontology-hub"
    master = repo / "ontology-hub" / "model" / "ontologies" / "_master.ttl"
    assert master.is_file()
    content = master.read_text(encoding="utf-8")
    assert "owl:Ontology" in content
    assert "contoso.com/ont/master" in content


def test_new_repo_custom_company_domain(tmp_path):
    """new-repo --company-domain should override the derived domain."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            [
                "new-repo",
                "contoso",
                "--path",
                str(tmp_path),
                "--company-domain",
                "contoso.io",
            ],
        )
    assert result.exit_code == 0, result.output

    repo = tmp_path / "contoso-ontology-hub"
    readme = repo / "ontology-hub" / "README.md"
    content = readme.read_text(encoding="utf-8")
    assert "contoso.io" in content
    assert "contoso.com" not in content


# ---------------------------------------------------------------------------
# Branch protection on new-repo
# ---------------------------------------------------------------------------


def test_new_repo_configures_branch_protection(tmp_path):
    """new-repo should call gh api to configure branch protection on main."""
    runner = CliRunner()

    call_log = []

    def side_effect(cmd, *args, **kwargs):
        call_log.append(cmd)
        result = mock.MagicMock(returncode=0)
        # For text=True calls (like git rev-parse), return str stdout
        if kwargs.get("text"):
            result.stdout = ""
            result.stderr = ""
        elif "gh" in cmd and "api" in cmd and "protection" in " ".join(cmd):
            if "--method" not in cmd:
                result.stdout = (
                    b'{"required_pull_request_reviews": {"required_approving_review_count": 1}}'
                )
            else:
                result.stdout = b"{}"
            result.stderr = b""
        else:
            result.stdout = b""
            result.stderr = b""
        return result

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=side_effect):
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    assert "Branch protection enabled on main" in result.output
    assert "Require PR with 1 reviewer" in result.output

    # Verify gh api calls were made for protection
    str_calls = [" ".join(c) for c in call_log if isinstance(c, list)]
    assert any("PATCH" in c and "/repos/" in c for c in str_calls)
    assert any("PUT" in c and "protection" in c for c in str_calls)


def test_new_repo_skip_protection_flag(tmp_path):
    """new-repo --skip-protection should skip branch protection configuration."""
    runner = CliRunner()

    def side_effect(cmd, *args, **kwargs):
        result = mock.MagicMock(returncode=0)
        if kwargs.get("text"):
            result.stdout = ""
            result.stderr = ""
        else:
            result.stdout = b""
            result.stderr = b""
        return result

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=side_effect):
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path), "--skip-protection"],
        )
    assert result.exit_code == 0, result.output
    assert "Branch protection" not in result.output
    assert "Configuring branch protection" not in result.output


def test_new_repo_protection_failure_is_non_fatal(tmp_path):
    """new-repo should warn (not crash) if branch protection fails."""
    runner = CliRunner()

    def side_effect(cmd, *args, **kwargs):
        if kwargs.get("text"):
            return mock.MagicMock(returncode=0, stdout="", stderr="")
        # Fail on gh api PUT for protection, succeed on everything else
        if isinstance(cmd, list) and "gh" in cmd and "--method" in cmd:
            if "PUT" in cmd and "protection" in " ".join(cmd):
                raise subprocess.CalledProcessError(
                    1, cmd, stderr=b"Resource not accessible by integration"
                )
        return mock.MagicMock(returncode=0, stdout=b"{}", stderr=b"")

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=side_effect):
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    assert "Could not set branch protection" in result.output
    assert "Repository created" in result.output


# -- _tag_to_version / _whl_url PEP 440 conversion tests ----------------------


class TestTagToVersion:
    """Ensure git tags are properly converted to PEP 440 version strings."""

    def test_stable_tag(self):
        assert _tag_to_version("v3.8.1") == "3.8.1"

    def test_rc_tag(self):
        assert _tag_to_version("v3.9.0-rc.1") == "3.9.0rc1"

    def test_rc_tag_multi_digit(self):
        assert _tag_to_version("v3.9.0-rc.12") == "3.9.0rc12"

    def test_beta_tag(self):
        assert _tag_to_version("v5.0.0-beta.2") == "5.0.0b2"

    def test_alpha_tag(self):
        assert _tag_to_version("v5.0.0-alpha.1") == "5.0.0a1"

    def test_no_v_prefix(self):
        assert _tag_to_version("3.8.1") == "3.8.1"

    def test_whl_url_stable(self):
        url = _whl_url("v3.8.1")
        assert "3.8.1-py3-none-any.whl" in url
        assert "/v3.8.1/" in url

    def test_whl_url_rc(self):
        url = _whl_url("v3.9.0-rc.1")
        assert "3.9.0rc1-py3-none-any.whl" in url
        assert "/v3.9.0-rc.1/" in url


class TestResolveChannel:
    """Ensure channel resolution picks the highest version, not lexicographic first."""

    def test_preview_picks_highest_rc(self):
        """rc12 should be picked over rc9 (numeric sort, not string sort)."""
        with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout="v3.9.0rc9\nv3.9.0rc8\nv3.9.0rc12\nv3.9.0rc11\nv3.9.0rc10\nv3.8.1\n",
            )
            result = _resolve_channel("preview")
            assert result == "v3.9.0rc12"

    def test_stable_skips_prereleases(self):
        """Stable should skip all rc tags and pick the latest stable."""
        with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout="v3.9.0rc12\nv3.9.0rc9\nv3.8.1\nv3.8.0\nv3.7.0\n",
            )
            result = _resolve_channel("stable")
            assert result == "v3.8.1"

    def test_stable_fallback_when_all_prerelease(self):
        """If all releases are pre-release, stable falls back to highest."""
        with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout="v3.9.0rc12\nv3.9.0rc9\nv3.9.0rc1\n",
            )
            result = _resolve_channel("stable")
            assert result == "v3.9.0rc12"

    def test_explicit_ref_passthrough(self):
        """Explicit refs should be returned as-is."""
        assert _resolve_channel("v2.16.0") == "v2.16.0"
        assert _resolve_channel("main") == "main"


# ---------------------------------------------------------------------------
# init: reference-models package mode (DD-158)
# ---------------------------------------------------------------------------


def test_init_does_not_clone_reference_models(tmp_path):
    """init must never git clone reference models (DD-158 — package mode)."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0, result.output

            assert not Path("ontology-reference-models").exists()

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    clone_calls = [c for c in call_args_list if c[0] == "git" and "clone" in c]
    assert len(clone_calls) == 0


def test_init_no_submodule_calls(tmp_path):
    """init should never call git submodule (reference models are a pip package)."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0

            # No submodule calls at all
            call_args_list = [call.args[0] for call in mock_run.call_args_list]
            submodule_calls = [c for c in call_args_list if "submodule" in c]
            assert len(submodule_calls) == 0


def test_init_skip_refmodels_flag_exits_cleanly(tmp_path):
    """--skip-refmodels must not attempt any clone, and must still exit 0."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--skip-refmodels"]
            )
            assert result.exit_code == 0, result.output
            assert not Path("ontology-reference-models").exists()

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    assert not any(c[0] == "git" and "clone" in c for c in call_args_list)


def test_init_pyproject_has_refmodels_dependency(tmp_path):
    """The scaffolded pyproject.toml must list kairos-ontology-referencemodels (DD-158)."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0, result.output

            pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
            assert "kairos-ontology-referencemodels" in pyproject


def test_init_no_inventory_pre_generation(tmp_path):
    """init must not pre-generate reference-model inventories (DD-158).

    Inventories are generated on-demand by compile / check-inventory.
    """
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0, result.output

            assert not Path("ontology-hub/referencemodels-unpacked").exists()
            assert "Generated" not in result.output


def test_init_skip_refmodels_skips_inventory_generation_too(tmp_path):
    """--skip-refmodels must skip inventory generation cleanly, no crash."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--skip-refmodels"]
            )
            assert result.exit_code == 0, result.output
            assert not Path("ontology-hub/referencemodels-unpacked").exists()
            assert "Generated" not in result.output


def test_scaffold_glossary_template_parses():
    """The scaffold glossary template (DD-048) must be valid Turtle with altLabels."""
    import kairos_ontology
    from rdflib import Graph
    from rdflib.namespace import SKOS

    scaffold = Path(kairos_ontology.__file__).parent / "scaffold"
    template = scaffold / "ontology-hub" / "businessdiscovery" / "glossary-template.ttl"
    assert template.is_file()

    g = Graph()
    g.parse(template, format="turtle")
    alt_labels = list(g.triples((None, SKOS.altLabel, None)))
    assert alt_labels, "glossary template should contain skos:altLabel triples"


def test_scaffold_imports_businessdiscovery_readme_present():
    """The repo-root .import/businessdiscovery scaffold README (DD-048) must exist."""
    import kairos_ontology

    scaffold = Path(kairos_ontology.__file__).parent / "scaffold"
    readme = scaffold / "import" / "businessdiscovery" / "README.md"
    assert readme.is_file()


# ---------------------------------------------------------------------------
# Closing banner (issue #327 sub-finding 2): "initialized" only on a fresh hub
# ---------------------------------------------------------------------------


def test_init_fresh_hub_prints_initialized_banner(tmp_path):
    """A brand-new hub should still see the original "initialized" banner."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert result.exit_code == 0, result.output
            assert "✅ Ontology hub initialized!" in result.output
            assert "added to existing ontology hub" not in result.output


def test_init_domain_on_existing_hub_prints_added_banner_not_initialized(tmp_path):
    """Adding a domain to a live hub must not read like a fresh scaffold re-run (#327).

    Regression for: `init --domain <name>` against an already-existing hub
    unconditionally printed "✅ Ontology hub initialized!", indistinguishable
    from a first-time scaffold. It should instead report that the domain was
    added to the existing hub.
    """
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            first = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert first.exit_code == 0, first.output
            assert "✅ Ontology hub initialized!" in first.output

            second = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--domain", "party"]
            )
            assert second.exit_code == 0, second.output
            assert "✅ Domain 'party' added to existing ontology hub!" in second.output
            assert "Ontology hub initialized!" not in second.output


def test_init_no_domain_on_existing_hub_prints_refreshed_banner(tmp_path):
    """Re-running `init` with no --domain on an existing hub reports a refresh, not init."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            first = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert first.exit_code == 0, first.output

            second = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert second.exit_code == 0, second.output
            assert "✅ Existing ontology hub scaffold refreshed!" in second.output
            assert "Ontology hub initialized!" not in second.output


# ---------------------------------------------------------------------------
# init --domain auto-syncs _master.ttl's owl:imports (issue #393)
# ---------------------------------------------------------------------------


def test_init_domain_syncs_master_ttl_import(tmp_path):
    """A fresh `init --domain` scaffold must also be imported by _master.ttl."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["init", "--company-domain", "test.com", "--domain", "customer"],
            )
            assert result.exit_code == 0, result.output
            assert "Synced owl:imports" in result.output

            master = Path("ontology-hub/model/ontologies/_master.ttl")
            content = master.read_text(encoding="utf-8")
            assert "owl:imports <https://test.com/ont/customer>" in content


def test_init_domain_master_sync_is_idempotent_on_rerun(tmp_path):
    """Re-running `init --domain` for the same domain must not duplicate the import."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            first = runner.invoke(
                cli,
                ["init", "--company-domain", "test.com", "--domain", "customer"],
            )
            assert first.exit_code == 0, first.output

            # No --force: the domain ontology and _master.ttl already exist and are
            # left alone, but the (idempotent) sync step still runs.
            second = runner.invoke(
                cli,
                ["init", "--company-domain", "test.com", "--domain", "customer"],
            )
            assert second.exit_code == 0, second.output
            assert "already imports" in second.output

            from kairos_ontology.core.master_ontology import list_active_master_imports

            master = Path("ontology-hub/model/ontologies/_master.ttl")
            # Exactly one *live* import -- the commented-out scaffold example also
            # mentions this domain's own company-domain-substituted URL as sample
            # text, so a raw substring count would over-count; the whole point of
            # list_active_master_imports is to see past that.
            assert list_active_master_imports(master) == {"https://test.com/ont/customer"}
            content = master.read_text(encoding="utf-8")
            assert content.count("<https://test.com/ont/master> owl:imports") == 1


def test_init_domain_master_sync_multiple_domains_sequentially(tmp_path):
    """Adding a second domain must preserve the first import and untouched content."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            first = runner.invoke(
                cli,
                ["init", "--company-domain", "test.com", "--domain", "customer"],
            )
            assert first.exit_code == 0, first.output

            master = Path("ontology-hub/model/ontologies/_master.ttl")
            before = master.read_text(encoding="utf-8")
            assert "rdfs:label" in before
            provenance_first_line = before.splitlines()[0]

            second = runner.invoke(
                cli,
                ["init", "--company-domain", "test.com", "--domain", "order"],
            )
            assert second.exit_code == 0, second.output

            after = master.read_text(encoding="utf-8")
            assert "owl:imports <https://test.com/ont/customer>" in after
            assert "owl:imports <https://test.com/ont/order>" in after
            # Everything from the first write must still be present verbatim
            # (provenance header / rdfs:label survive untouched) -- only new
            # content was inserted.
            assert after.splitlines()[0] == provenance_first_line
            assert "rdfs:label" in after
            for line in before.splitlines():
                assert line in after.splitlines()


def test_init_domain_missing_master_ttl_warns_and_does_not_crash(tmp_path, monkeypatch):
    """A hub with no _master.ttl at sync time must not crash `init --domain`.

    In normal operation _master.ttl always already exists by the time the
    domain-registration block runs (init's own step 7 recreates it if missing,
    since only an existing dst + no --force skips that write). To exercise the
    genuinely-missing guard, the scaffold's own master template is removed
    (via a monkeypatched _SCAFFOLD_DIR copy) so step 7 has nothing to (re)write
    from, leaving _master.ttl absent by the time --domain runs.
    """
    import shutil as _shutil
    import kairos_ontology.cli.setup as setup_mod

    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            first = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert first.exit_code == 0, first.output

            master = Path("ontology-hub/model/ontologies/_master.ttl")
            master.unlink()

            scaffold_copy = tmp_path / "_scaffold_no_master_template"
            _shutil.copytree(setup_mod._SCAFFOLD_DIR, scaffold_copy)
            (
                scaffold_copy / "ontology-hub" / "model" / "ontologies" / "master.ttl.template"
            ).unlink()
            monkeypatch.setattr(setup_mod, "_SCAFFOLD_DIR", scaffold_copy)

            second = runner.invoke(
                cli,
                ["init", "--company-domain", "test.com", "--domain", "customer"],
            )
            assert second.exit_code == 0, second.output
            assert "_master.ttl not found" in second.output
            assert not master.exists()


def test_init_domain_malformed_master_ttl_skips_sync_safely(tmp_path):
    """A corrupted _master.ttl must not crash `init --domain`, and must stay untouched."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            first = runner.invoke(cli, ["init", "--company-domain", "test.com"])
            assert first.exit_code == 0, first.output

            master = Path("ontology-hub/model/ontologies/_master.ttl")
            corrupt = "this is not valid turtle at all {{{ owl:imports <><><"
            master.write_text(corrupt, encoding="utf-8")

            second = runner.invoke(
                cli,
                ["init", "--company-domain", "test.com", "--domain", "customer"],
            )
            assert second.exit_code == 0, second.output
            assert "Could not sync _master.ttl automatically" in second.output
            assert master.read_text(encoding="utf-8") == corrupt
