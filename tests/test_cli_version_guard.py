# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the running-vs-pinned toolkit version guard (Fix 2).

Catches users who run a globally-installed (often older) toolkit instead of
`uv run kairos-ontology`, silently using a different version than the hub pins.
"""

from pathlib import Path
from unittest.mock import patch

from kairos_ontology.cli import main as cli_main
from kairos_ontology.cli.main import (
    _read_pinned_toolkit_version,
    _warn_if_version_mismatch,
)


def _write_pyproject_whl(tmp_path: Path, tag: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test-hub"\n\ndependencies = [\n'
        f'  "kairos-ontology-toolkit @ https://github.com/Cnext-eu/'
        f'kairos-ontology-toolkit/releases/download/{tag}/'
        f'kairos_ontology_toolkit-0.0.0-py3-none-any.whl",\n]\n',
        encoding="utf-8",
    )


def _write_pyproject_git(tmp_path: Path, tag: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test-hub"\n\ndependencies = [\n'
        f'  "kairos-ontology-toolkit @ git+https://github.com/Cnext-eu/'
        f'kairos-ontology-toolkit.git@{tag}",\n]\n',
        encoding="utf-8",
    )


class TestReadPinnedVersion:
    def test_parses_whl_pin(self, tmp_path, monkeypatch):
        _write_pyproject_whl(tmp_path, "v3.11.0")
        monkeypatch.chdir(tmp_path)
        assert _read_pinned_toolkit_version() == "3.11.0"

    def test_parses_prerelease_tag(self, tmp_path, monkeypatch):
        _write_pyproject_whl(tmp_path, "v3.12.0-rc.1")
        monkeypatch.chdir(tmp_path)
        assert _read_pinned_toolkit_version() == "3.12.0rc1"

    def test_parses_legacy_git_pin(self, tmp_path, monkeypatch):
        _write_pyproject_git(tmp_path, "v3.10.0")
        monkeypatch.chdir(tmp_path)
        assert _read_pinned_toolkit_version() == "3.10.0"

    def test_none_when_no_pyproject(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _read_pinned_toolkit_version() is None

    def test_none_when_no_toolkit_pin(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test-hub"\ndependencies = ["rdflib"]\n',
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        assert _read_pinned_toolkit_version() is None


class TestWarnVersionMismatch:
    def test_warns_when_running_older_than_pin(self, tmp_path, monkeypatch, capsys):
        _write_pyproject_whl(tmp_path, "v999.0.0")
        monkeypatch.chdir(tmp_path)
        _warn_if_version_mismatch()
        err = capsys.readouterr().err
        assert "v999.0.0" in err
        assert "OLDER than" in err
        assert "uv run" in err

    def test_no_warn_when_versions_match(self, tmp_path, monkeypatch, capsys):
        _write_pyproject_whl(tmp_path, f"v{cli_main._toolkit_version}")
        monkeypatch.chdir(tmp_path)
        _warn_if_version_mismatch()
        assert capsys.readouterr().err == ""

    def test_no_warn_when_no_pin(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        _warn_if_version_mismatch()
        assert capsys.readouterr().err == ""

    def test_warns_different_when_running_newer(self, tmp_path, monkeypatch, capsys):
        _write_pyproject_whl(tmp_path, "v0.0.1")
        monkeypatch.chdir(tmp_path)
        with patch.object(cli_main, "_toolkit_version", "3.12.0"):
            _warn_if_version_mismatch()
        err = capsys.readouterr().err
        assert "v0.0.1" in err
        assert "different from" in err
