"""Tests for the kairos-ontology init and new-repo CLI commands."""

import os
from pathlib import Path
from unittest import mock
from click.testing import CliRunner
from kairos_ontology.cli.main import (
    cli, _slugify, _stamp_managed, _get_managed_version, _managed_scaffold_map,
)


def test_init_creates_hub_structure(tmp_path):
    """init should create the standard hub directory structure."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--domain", "order"])
            assert result.exit_code == 0

            # Check ontology-hub directories
            assert Path("ontology-hub/ontologies").is_dir()
            assert Path("ontology-hub/shapes").is_dir()
            assert Path("ontology-hub/mappings").is_dir()
            assert Path("ontology-hub/output/dbt").is_dir()
            assert Path("ontology-hub/output/neo4j").is_dir()
            assert Path("ontology-hub/output/azure-search").is_dir()
            assert Path("ontology-hub/output/a2ui").is_dir()
            assert Path("ontology-hub/output/prompt").is_dir()

            # Check README files
            assert Path("ontology-hub/ontologies/README.md").is_file()
            assert Path("ontology-hub/shapes/README.md").is_file()
            assert Path("ontology-hub/mappings/README.md").is_file()

            # Check skills installed
            assert Path(".github/skills/hub-setup/SKILL.md").is_file()
            assert Path(".github/skills/ontology-modeling/SKILL.md").is_file()
            assert Path(".github/skills/ontology-validation/SKILL.md").is_file()
            assert Path(".github/skills/projection-generation/SKILL.md").is_file()

            # Check copilot instructions
            assert Path(".github/copilot-instructions.md").is_file()

            # Check submodule add was called
            call_args_list = [call.args[0] for call in mock_run.call_args_list]
            submodule_calls = [
                c for c in call_args_list if "submodule" in c and "add" in c
            ]
            assert len(submodule_calls) == 1
            assert "ontology-reference-models" in submodule_calls[0]

            # Check starter ontology
            assert Path("ontology-hub/ontologies/order.ttl").is_file()
            content = Path("ontology-hub/ontologies/order.ttl").read_text(encoding="utf-8")
            assert "owl:Ontology" in content
            assert "order" in content


def test_init_without_domain(tmp_path):
    """init without --domain should still create the structure but no starter ontology."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0

            assert Path("ontology-hub/ontologies").is_dir()
            assert Path(".github/skills/hub-setup/SKILL.md").is_file()
            # No ontology files should be created
            assert list(Path("ontology-hub/ontologies").glob("*.ttl")) == []


def test_init_no_overwrite_without_force(tmp_path):
    """init should skip existing files unless --force is set."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Run once
            runner.invoke(cli, ["init", "--domain", "customer"])
            # Modify the ontology to detect if it gets overwritten
            marker = "# MARKER"
            Path("ontology-hub/ontologies/customer.ttl").write_text(marker, encoding="utf-8")

            # Run again without --force
            result = runner.invoke(cli, ["init", "--domain", "customer"])
            assert result.exit_code == 0
            assert Path("ontology-hub/ontologies/customer.ttl").read_text(encoding="utf-8") == marker


def test_init_force_overwrites(tmp_path):
    """init --force should overwrite existing files."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init", "--domain", "customer"])
            Path("ontology-hub/ontologies/customer.ttl").write_text("# MARKER", encoding="utf-8")

            result = runner.invoke(cli, ["init", "--domain", "customer", "--force"])
            assert result.exit_code == 0
            content = Path("ontology-hub/ontologies/customer.ttl").read_text(encoding="utf-8")
            assert "owl:Ontology" in content


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
            ["new-repo", "contoso", "--path", str(tmp_path),
             "--template", ""],
        )
    assert result.exit_code == 0, result.output

    repo = tmp_path / "contoso-ontology-hub"
    assert repo.is_dir()

    # Hub structure
    assert (repo / "ontology-hub" / "ontologies").is_dir()
    assert (repo / "ontology-hub" / "shapes" / "README.md").is_file()
    assert (repo / "ontology-hub" / "mappings" / "README.md").is_file()
    assert (repo / "ontology-hub" / "output" / "dbt").is_dir()

    # Submodule add was called for reference models
    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    submodule_calls = [c for c in call_args_list if "submodule" in c and "add" in c]
    assert len(submodule_calls) == 1
    assert "ontology-reference-models" in submodule_calls[0]

    # Copilot
    assert (repo / ".github" / "copilot-instructions.md").is_file()
    assert (repo / ".github" / "skills" / "quickstart" / "SKILL.md").is_file()
    assert (repo / ".github" / "skills" / "hub-setup" / "SKILL.md").is_file()

    # Repo-level files
    assert (repo / "pyproject.toml").is_file()
    assert (repo / ".gitignore").is_file()
    assert (repo / "README.md").is_file()

    # pyproject references the toolkit
    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "kairos-ontology-toolkit" in pyproject
    assert "contoso-ontology-hub" in pyproject


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


def test_new_repo_default_org_is_cnext(tmp_path):
    """new-repo should default --org to Cnext-eu."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path),
             "--template", ""],
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
            ["new-repo", "test-client", "--path", str(tmp_path),
             "--template", ""],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    assert ["git", "init"] in call_args_list
    assert ["git", "add", "."] in call_args_list
    assert ["gh", "--version"] in call_args_list
    # Submodule should be added between git init and git add
    submodule_calls = [c for c in call_args_list if "submodule" in c and "add" in c]
    assert len(submodule_calls) == 1
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
            ["new-repo", "empty-client", "--path", str(tmp_path), "--template", ""],
        )
    assert result.exit_code == 0, result.output
    repo = tmp_path / "empty-client-ontology-hub"
    assert (repo / "ontology-hub" / "ontologies").is_dir()
    assert list((repo / "ontology-hub" / "ontologies").glob("*.ttl")) == []


def test_new_repo_custom_org(tmp_path):
    """new-repo --org should use the specified org for gh repo create."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso",
             "--path", str(tmp_path), "--org", "Acme-Corp", "--template", ""],
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
            ["new-repo", "contoso", "--path", str(tmp_path), "--template", ""],
        )
    assert result.exit_code == 0, result.output
    gh_create_call = [
        call.args[0] for call in mock_run.call_args_list
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
            ["new-repo", "contoso", "--path", str(tmp_path), "--public", "--template", ""],
        )
    assert result.exit_code == 0, result.output
    gh_create_call = [
        call.args[0] for call in mock_run.call_args_list
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
            ["new-repo", "contoso", "--path", str(tmp_path),
             "--template", ""],
        )
    assert result.exit_code == 0, result.output

    repo = tmp_path / "contoso-ontology-hub"

    # copilot-instructions.md should have the marker
    ci = (repo / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert _get_managed_version(ci) is not None

    # At least one skill should be stamped
    for skill_md in (repo / ".github" / "skills").rglob("SKILL.md"):
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

        result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0, result.output
    assert "up to date" in result.output


def test_update_reports_missing_files(tmp_path):
    """update should warn about managed files that don't exist locally."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0, result.output
    assert "missing" in result.output


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
            ["new-repo", "contoso", "--path", str(tmp_path), "--template", ""],
        )
    assert result.exit_code == 0, result.output
    wf = tmp_path / "contoso-ontology-hub" / ".github" / "workflows" / "managed-check.yml"
    assert wf.is_file()
    content = wf.read_text(encoding="utf-8")
    assert "kairos-ontology update --check" in content


def test_init_includes_workflow(tmp_path):
    """init should scaffold the managed-check CI workflow."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0
            wf = Path(".github/workflows/managed-check.yml")
            assert wf.is_file()
            content = wf.read_text(encoding="utf-8")
            assert "kairos-ontology update --check" in content


# ---------------------------------------------------------------------------
# Reference models submodule
# ---------------------------------------------------------------------------


def test_new_repo_ref_models_version(tmp_path):
    """new-repo --ref-models-version should checkout that ref in the submodule."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path),
             "--ref-models-version", "v1.2.0", "--template", ""],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    # Should have git checkout v1.2.0 inside the submodule
    checkout_calls = [c for c in call_args_list if "checkout" in c]
    assert len(checkout_calls) == 1
    assert "v1.2.0" in checkout_calls[0]


def test_init_submodule_skips_existing(tmp_path):
    """init should skip submodule add when ontology-reference-models/ already has content."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Pre-create the directory with content (simulates existing submodule)
            refs = Path("ontology-reference-models")
            refs.mkdir()
            (refs / "catalog-v001.xml").write_text("<catalog/>", encoding="utf-8")

            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0

            # Submodule add should NOT have been called
            call_args_list = [call.args[0] for call in mock_run.call_args_list]
            submodule_calls = [
                c for c in call_args_list if "submodule" in c and "add" in c
            ]
            assert len(submodule_calls) == 0


def test_new_repo_workflow_has_submodules(tmp_path):
    """new-repo workflow should include submodules: true in checkout step."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path), "--template", ""],
        )
    assert result.exit_code == 0, result.output
    wf = tmp_path / "contoso-ontology-hub" / ".github" / "workflows" / "managed-check.yml"
    content = wf.read_text(encoding="utf-8")
    assert "submodules: true" in content


# ---------------------------------------------------------------------------
# Template + SmartCoding
# ---------------------------------------------------------------------------


def test_new_repo_template_creates_from_template(tmp_path):
    """new-repo with default --template should use gh repo create --template --clone."""
    runner = CliRunner()
    repo_dir = tmp_path / "contoso-ontology-hub"

    def _side_effect(cmd, **kwargs):
        # gh repo create --clone creates the directory
        if cmd[0] == "gh" and "create" in cmd and "--clone" in cmd:
            repo_dir.mkdir(parents=True, exist_ok=True)
        return mock.MagicMock(returncode=0)

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=_side_effect):
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    assert repo_dir.is_dir()
    assert (repo_dir / "ontology-hub" / "ontologies").is_dir()


def test_new_repo_template_gh_create_has_template_flag(tmp_path):
    """new-repo with --template should pass --template and --clone to gh repo create."""
    runner = CliRunner()
    repo_dir = tmp_path / "contoso-ontology-hub"

    def _side_effect(cmd, **kwargs):
        if cmd[0] == "gh" and "create" in cmd and "--clone" in cmd:
            repo_dir.mkdir(parents=True, exist_ok=True)
        return mock.MagicMock(returncode=0)

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=_side_effect) as mock_run:
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path),
             "--template", "my-custom-template"],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    gh_create_call = [c for c in call_args_list if "gh" in c and "create" in c]
    assert len(gh_create_call) == 1
    assert "--template" in gh_create_call[0]
    assert "--clone" in gh_create_call[0]
    assert "Cnext-eu/my-custom-template" in gh_create_call[0]


def test_new_repo_template_no_git_init(tmp_path):
    """new-repo with --template should NOT run git init (--clone does that)."""
    runner = CliRunner()
    repo_dir = tmp_path / "contoso-ontology-hub"

    def _side_effect(cmd, **kwargs):
        if cmd[0] == "gh" and "create" in cmd and "--clone" in cmd:
            repo_dir.mkdir(parents=True, exist_ok=True)
        return mock.MagicMock(returncode=0)

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=_side_effect) as mock_run:
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    assert ["git", "init"] not in call_args_list
    # Should still commit + push
    assert ["git", "add", "."] in call_args_list
    push_calls = [c for c in call_args_list if c == ["git", "push"]]
    assert len(push_calls) == 1


def test_new_repo_template_full_org_slash(tmp_path):
    """new-repo --template owner/repo should use the full ref as-is."""
    runner = CliRunner()
    repo_dir = tmp_path / "contoso-ontology-hub"

    def _side_effect(cmd, **kwargs):
        if cmd[0] == "gh" and "create" in cmd and "--clone" in cmd:
            repo_dir.mkdir(parents=True, exist_ok=True)
        return mock.MagicMock(returncode=0)

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=_side_effect) as mock_run:
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path),
             "--template", "OtherOrg/other-template"],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    gh_create_call = [c for c in call_args_list if "gh" in c and "create" in c]
    assert "OtherOrg/other-template" in gh_create_call[0]


def test_new_repo_smartcoding_runs_when_script_exists(tmp_path):
    """new-repo should run update-smartcoding-latest.ps1 when present."""
    runner = CliRunner()
    repo_dir = tmp_path / "contoso-ontology-hub"

    def _side_effect(cmd, **kwargs):
        if cmd[0] == "gh" and "create" in cmd and "--clone" in cmd:
            repo_dir.mkdir(parents=True, exist_ok=True)
            # Template would provide this script
            (repo_dir / "update-smartcoding-latest.ps1").write_text(
                "# smartcoding", encoding="utf-8"
            )
        return mock.MagicMock(returncode=0)

    with mock.patch("kairos_ontology.cli.main.subprocess.run", side_effect=_side_effect) as mock_run:
        result = runner.invoke(
            cli,
            ["new-repo", "contoso", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output

    call_args_list = [call.args[0] for call in mock_run.call_args_list]
    pwsh_calls = [c for c in call_args_list if c[0] == "pwsh"]
    assert len(pwsh_calls) == 1
    assert "update-smartcoding-latest.ps1" in str(pwsh_calls[0])


def test_init_smartcoding_runs_when_script_exists(tmp_path):
    """init should run update-smartcoding-latest.ps1 when present in cwd."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Pre-create the script (as if repo was created from template)
            Path("update-smartcoding-latest.ps1").write_text(
                "# smartcoding", encoding="utf-8"
            )
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0

            call_args_list = [call.args[0] for call in mock_run.call_args_list]
            pwsh_calls = [c for c in call_args_list if c[0] == "pwsh"]
            assert len(pwsh_calls) == 1


def test_init_smartcoding_skipped_when_no_script(tmp_path):
    """init should NOT run smartcoding update when script is absent."""
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0

            call_args_list = [call.args[0] for call in mock_run.call_args_list]
            pwsh_calls = [c for c in call_args_list if c[0] == "pwsh"]
            assert len(pwsh_calls) == 0
