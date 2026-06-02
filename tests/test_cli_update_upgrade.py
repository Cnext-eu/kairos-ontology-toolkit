# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the update --upgrade CLI command (Windows lock-file handling)."""

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

        # uv lock succeeds
        lock_result = MagicMock(returncode=0, stdout="", stderr="")
        mock_run.return_value = lock_result

        with patch("sys.platform", "win32"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                # Re-create pyproject in the isolated fs
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        assert "will activate on next uv run" in result.output

        # Only uv lock should have been called, NOT uv sync
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

        # Both uv lock and uv sync succeed
        success = MagicMock(returncode=0, stdout="", stderr="")
        mock_run.return_value = success

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        assert "Upgraded to v3.9.0-rc.2" in result.output

        # Both uv lock and uv sync should have been called
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "lock"] in calls
        assert ["uv", "sync"] in calls
