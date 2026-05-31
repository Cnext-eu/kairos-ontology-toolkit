# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the update-refmodels CLI command."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def hub_structure(tmp_path):
    """Create a minimal hub directory structure."""
    ref_dir = tmp_path / "model" / "reference-models"
    ref_dir.mkdir(parents=True)
    (ref_dir / "old-file.ttl").write_text("# old content")
    return tmp_path


class TestUpdateRefmodels:
    """Tests for kairos-ontology update-refmodels command."""

    def test_help_text(self, runner):
        """Command should have descriptive help."""
        result = runner.invoke(cli, ["update-refmodels", "--help"])
        assert result.exit_code == 0
        assert "reference models" in result.output.lower()
        assert "--ref" in result.output
        assert "--dest" in result.output

    def test_git_not_found(self, runner, hub_structure):
        """Should fail gracefully when git is not installed."""
        with patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")
            result = runner.invoke(
                cli, ["update-refmodels", "--dest", str(hub_structure / "model" / "reference-models")]
            )
            assert result.exit_code != 0
            assert "git is not installed" in result.output

    def test_clone_failure(self, runner, hub_structure):
        """Should report error when git clone fails."""
        dest = str(hub_structure / "model" / "reference-models")

        def mock_run_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "--version":
                return MagicMock(returncode=0)
            if cmd[0] == "git" and cmd[1] == "clone":
                return MagicMock(returncode=1, stderr="fatal: remote not found")
            return MagicMock(returncode=0)

        with patch("kairos_ontology.cli.main.subprocess.run", side_effect=mock_run_side_effect):
            result = runner.invoke(cli, ["update-refmodels", "--ref", "v99.99.99", "--dest", dest])
            assert result.exit_code != 0
            assert "clone failed" in result.output

    def test_successful_update(self, runner, hub_structure, tmp_path):
        """Should successfully update reference models on happy path."""
        dest = hub_structure / "model" / "reference-models"

        # Create a fake temp directory that simulates what git would produce
        fake_clone_dir = tmp_path / "fake-clone"
        fake_refmodels = fake_clone_dir / "ontology-reference-models"
        fake_refmodels.mkdir(parents=True)
        (fake_refmodels / "party.ttl").write_text("# Party reference model")
        (fake_refmodels / "VERSION").write_text("1.2.0\n")

        call_count = {"n": 0}

        def mock_run_side_effect(cmd, **kwargs):
            call_count["n"] += 1
            if cmd[0] == "git" and cmd[1] == "--version":
                return MagicMock(returncode=0)
            if cmd[0] == "git" and cmd[1] == "clone":
                # Simulate the clone by copying our fake content into the target
                clone_dest = Path(cmd[-1])
                import shutil
                if clone_dest.exists():
                    shutil.rmtree(clone_dest)
                shutil.copytree(fake_clone_dir, clone_dest)
                return MagicMock(returncode=0)
            if cmd[0] == "git" and "sparse-checkout" in cmd:
                return MagicMock(returncode=0)
            if cmd[0] == "git" and "rev-parse" in cmd:
                return MagicMock(returncode=0, stdout="abc123def456\n")
            return MagicMock(returncode=0)

        with patch("kairos_ontology.cli.main.subprocess.run", side_effect=mock_run_side_effect):
            result = runner.invoke(cli, ["update-refmodels", "--dest", str(dest)])

        assert result.exit_code == 0, f"Failed with: {result.output}"
        assert "Reference models updated" in result.output
        assert "abc123def456" in result.output
        assert "1.2.0" in result.output
        # Old content should be replaced
        assert not (dest / "old-file.ttl").exists()
        # New content should be present
        assert (dest / "party.ttl").exists()

    def test_missing_remote_folder(self, runner, hub_structure, tmp_path):
        """Should fail when the expected folder is not in the cloned repo."""
        dest = hub_structure / "model" / "reference-models"

        # Clone dir exists but without the expected subfolder
        fake_clone_dir = tmp_path / "fake-clone-empty"
        fake_clone_dir.mkdir(parents=True)
        (fake_clone_dir / "some-other-folder").mkdir()

        def mock_run_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "--version":
                return MagicMock(returncode=0)
            if cmd[0] == "git" and cmd[1] == "clone":
                clone_dest = Path(cmd[-1])
                import shutil
                if clone_dest.exists():
                    shutil.rmtree(clone_dest)
                shutil.copytree(fake_clone_dir, clone_dest)
                return MagicMock(returncode=0)
            if cmd[0] == "git" and "sparse-checkout" in cmd:
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        with patch("kairos_ontology.cli.main.subprocess.run", side_effect=mock_run_side_effect):
            result = runner.invoke(cli, ["update-refmodels", "--dest", str(dest)])

        assert result.exit_code != 0
        assert "not found in cloned repo" in result.output

    def test_default_ref_is_main(self, runner, hub_structure, tmp_path):
        """Default ref should be 'main'."""
        dest = hub_structure / "model" / "reference-models"

        fake_clone_dir = tmp_path / "fake-clone2"
        fake_refmodels = fake_clone_dir / "ontology-reference-models"
        fake_refmodels.mkdir(parents=True)
        (fake_refmodels / "test.ttl").write_text("# test")

        captured_cmds = []

        def mock_run_side_effect(cmd, **kwargs):
            captured_cmds.append(cmd)
            if cmd[0] == "git" and cmd[1] == "--version":
                return MagicMock(returncode=0)
            if cmd[0] == "git" and cmd[1] == "clone":
                clone_dest = Path(cmd[-1])
                import shutil
                if clone_dest.exists():
                    shutil.rmtree(clone_dest)
                shutil.copytree(fake_clone_dir, clone_dest)
                return MagicMock(returncode=0)
            if cmd[0] == "git" and "sparse-checkout" in cmd:
                return MagicMock(returncode=0)
            if cmd[0] == "git" and "rev-parse" in cmd:
                return MagicMock(returncode=0, stdout="deadbeef\n")
            return MagicMock(returncode=0)

        with patch("kairos_ontology.cli.main.subprocess.run", side_effect=mock_run_side_effect):
            result = runner.invoke(cli, ["update-refmodels", "--dest", str(dest)])

        assert result.exit_code == 0
        # Find the clone command and verify --branch main is used
        clone_cmd = [c for c in captured_cmds if "clone" in c]
        assert any("main" in str(c) for c in clone_cmd)
