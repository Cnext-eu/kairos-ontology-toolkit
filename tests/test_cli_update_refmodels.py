# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the update-refmodels CLI command (package mode, DD-158, DD-200).

The command resolves the latest published release tag the same way scaffolding
does (issue #551), installs that exact wheel via ``uv pip install <url>``, reads
the installed version via ``importlib.metadata``, rewrites the pin in
``pyproject.toml``, and runs ``uv lock``.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli

_REFMODELS_PIN_V118 = (
    '"kairos-ontology-referencemodels @ '
    "https://github.com/Cnext-eu/kairos-ontology-referencemodels/releases/download/"
    'v1.18.0/kairos_ontology_referencemodels-1.18.0-py3-none-any.whl"'
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def hub_with_pyproject(tmp_path):
    """Create a minimal hub dir with a pyproject.toml containing a refmodels pin."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f"dependencies = [\n    {_REFMODELS_PIN_V118},\n]\n",
        encoding="utf-8",
    )
    return tmp_path


class TestUpdateRefmodelsHelp:
    def test_help_text(self, runner):
        result = runner.invoke(cli, ["update-refmodels", "--help"])
        assert result.exit_code == 0
        assert "reference-models" in result.output.lower()
        assert "--version" in result.output


class TestUpdateRefmodelsUpgrade:
    """Default (no --version): resolve the latest release tag, install that exact
    wheel (never the pip index, which has no kairos-ontology-referencemodels
    package to find — issue #551), rewrite the pin, and uv lock."""

    def test_successful_upgrade(self, runner, hub_with_pyproject, monkeypatch):
        """Happy path: tag resolved, install succeeds, pin rewritten, lock called."""
        monkeypatch.chdir(hub_with_pyproject)
        with (
            patch(
                "kairos_ontology.cli.operations._resolve_refmodels_tag",
                return_value="v1.20.0",
            ),
            patch("kairos_ontology.cli.operations.subprocess.run") as mock_run,
            patch("kairos_ontology.cli.operations.importlib.metadata") as mock_meta,
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
            ]
            mock_meta.version.return_value = "1.20.0"

            result = runner.invoke(cli, ["update-refmodels"])

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "Reference models updated" in result.output
        assert "1.20.0" in result.output

        # Verify the exact resolved wheel was installed, not --upgrade by bare name
        install_args = mock_run.call_args_list[0].args[0]
        assert "pip" in install_args
        assert "install" in install_args
        assert "--upgrade" not in install_args
        assert any("v1.20.0" in str(a) for a in install_args)

        # Verify uv lock was called
        assert mock_run.call_args_list[1].args[0] == ["uv", "lock"]

        # Verify pyproject.toml pin was rewritten
        content = (hub_with_pyproject / "pyproject.toml").read_text(encoding="utf-8")
        assert "v1.20.0" in content
        assert "v1.18.0" not in content

    def test_unresolvable_tag_raises(self, runner, hub_with_pyproject, monkeypatch):
        """No published release could be listed at all -- refuse, pin unchanged."""
        monkeypatch.chdir(hub_with_pyproject)
        with patch(
            "kairos_ontology.cli.operations._resolve_refmodels_tag", return_value=None
        ):
            result = runner.invoke(cli, ["update-refmodels"])
            assert result.exit_code != 0
            assert "Could not resolve a reference-models release" in result.output

        content = (hub_with_pyproject / "pyproject.toml").read_text(encoding="utf-8")
        assert "v1.18.0" in content

    def test_install_failure_raises(self, runner, hub_with_pyproject, monkeypatch):
        """uv pip install failure should raise a ClickException."""
        monkeypatch.chdir(hub_with_pyproject)
        with (
            patch(
                "kairos_ontology.cli.operations._resolve_refmodels_tag",
                return_value="v1.20.0",
            ),
            patch("kairos_ontology.cli.operations.subprocess.run") as mock_run,
            patch("kairos_ontology.cli.operations.importlib.metadata"),
        ):
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="ERROR: package not found"
            )

            result = runner.invoke(cli, ["update-refmodels"])
            assert result.exit_code != 0
            assert "uv pip install failed" in result.output

    def test_lock_failure_raises(self, runner, hub_with_pyproject, monkeypatch):
        """uv lock failure should raise a ClickException."""
        monkeypatch.chdir(hub_with_pyproject)
        with (
            patch(
                "kairos_ontology.cli.operations._resolve_refmodels_tag",
                return_value="v1.20.0",
            ),
            patch("kairos_ontology.cli.operations.subprocess.run") as mock_run,
            patch("kairos_ontology.cli.operations.importlib.metadata") as mock_meta,
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=1, stdout="", stderr="lock conflict"),
            ]
            mock_meta.version.return_value = "1.20.0"

            result = runner.invoke(cli, ["update-refmodels"])
            assert result.exit_code != 0
            assert "uv lock failed" in result.output

    def test_package_not_found_after_install(self, runner, hub_with_pyproject, monkeypatch):
        """importlib.metadata.PackageNotFoundError after install should raise."""
        import importlib.metadata as md
        monkeypatch.chdir(hub_with_pyproject)
        with (
            patch(
                "kairos_ontology.cli.operations._resolve_refmodels_tag",
                return_value="v1.20.0",
            ),
            patch("kairos_ontology.cli.operations.subprocess.run") as mock_run,
            patch("kairos_ontology.cli.operations.importlib.metadata") as mock_meta,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mock_meta.version.side_effect = md.PackageNotFoundError(
                "kairos-ontology-referencemodels"
            )
            mock_meta.PackageNotFoundError = md.PackageNotFoundError

            result = runner.invoke(cli, ["update-refmodels"])
            assert result.exit_code != 0
            assert "not found after install" in result.output


class TestUpdateRefmodelsVersion:
    """--version <tag>: install specific wheel URL + pin rewrite + lock."""

    def test_specific_version(self, runner, hub_with_pyproject, monkeypatch):
        """--version v1.20.0 installs the specific wheel URL."""
        monkeypatch.chdir(hub_with_pyproject)
        with (
            patch("kairos_ontology.cli.operations.subprocess.run") as mock_run,
            patch("kairos_ontology.cli.operations.importlib.metadata") as mock_meta,
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
            ]
            mock_meta.version.return_value = "1.20.0"

            result = runner.invoke(cli, ["update-refmodels", "--version", "v1.20.0"])

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Verify install used the wheel URL, not --upgrade
        install_args = mock_run.call_args_list[0].args[0]
        assert "pip" in install_args
        assert "install" in install_args
        assert any("v1.20.0" in str(a) for a in install_args)

        # Verify pyproject.toml pin rewritten to v1.20.0
        content = (hub_with_pyproject / "pyproject.toml").read_text(encoding="utf-8")
        assert "v1.20.0" in content
        assert "v1.18.0" not in content
