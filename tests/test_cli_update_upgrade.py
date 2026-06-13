# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the update --upgrade CLI command.

Covers the Windows lock-file handling and the post-upgrade re-exec that refreshes
managed files under the newly-installed toolkit version (instead of the stale
in-process module).
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def _make_hub_pyproject(tmp_path: Path, version: str = "v3.8.0") -> Path:
    """Create a minimal pyproject.toml with a toolkit dependency pin."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test-hub"\n\ndependencies = [\n'
        f'  "kairos-ontology-toolkit @ https://github.com/Cnext-eu/'
        f'kairos-ontology-toolkit/releases/download/{version}/'
        f'kairos_ontology_toolkit-0.0.0-py3-none-any.whl",\n]\n\n'
        '[tool.kairos]\nchannel = "preview"\n',
        encoding="utf-8",
    )
    return pyproject


class TestUpdateUpgradeWindows:
    """Tests for the Windows-specific uv sync skip during --upgrade."""

    @patch("kairos_ontology.cli.main._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.main._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.main._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_windows_skips_uv_sync(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """On Windows, uv sync should be skipped after uv lock succeeds."""
        _make_hub_pyproject(tmp_path)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "win32"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "lock"] in calls
        assert ["uv", "sync"] not in calls

    @patch("kairos_ontology.cli.main._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.main._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.main._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_non_windows_runs_uv_sync(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """On non-Windows, uv sync should still be called after uv lock."""
        _make_hub_pyproject(tmp_path)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        assert "Upgraded to v3.9.0-rc.2" in result.output
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "lock"] in calls
        assert ["uv", "sync"] in calls


class TestUpdateUpgradeReexec:
    """The post-upgrade refresh must re-exec under the NEW toolkit version."""

    @patch("kairos_ontology.cli.main._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.main._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.main._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_reexec_refresh_when_version_changed(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """When the target version differs, refresh is re-run via `uv run`,
        and the stale in-process managed refresh is skipped."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "run", "kairos-ontology", "update"] in calls
        # In-process managed refresh must NOT have run (re-exec owns it now).
        mock_scaffold.assert_not_called()

    @patch("kairos_ontology.cli.main._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.main._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.main._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_reexec_propagates_check_flag(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """`--upgrade --check` re-execs the refresh with --check appended."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade", "--check"])

        assert result.exit_code == 0
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "run", "kairos-ontology", "update", "--check"] in calls

    @patch("kairos_ontology.cli.main._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.main._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.main._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_reexec_exit_code_propagates(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """A non-zero re-exec (e.g. drift under --check) propagates the exit code."""

        def _run(cmd, *args, **kwargs):
            if cmd[:4] == ["uv", "run", "kairos-ontology", "update"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = _run

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade", "--check"])

        assert result.exit_code == 1

    @patch("kairos_ontology.cli.main._toolkit_version", "3.9.0rc2")
    @patch("kairos_ontology.cli.main._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.main._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.main._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_no_reexec_when_version_unchanged(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """A no-op upgrade (target == running) runs the in-process refresh,
        with no re-exec (guards against recursion)."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "run", "kairos-ontology", "update"] not in calls
        # In-process refresh ran (it consulted the managed map).
        mock_scaffold.assert_called()
