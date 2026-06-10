# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the _warn_if_outside_venv startup guard."""

import sys
from pathlib import Path
from unittest.mock import patch

from kairos_ontology.cli.main import _warn_if_outside_venv


def test_no_warning_inside_venv(capsys):
    """No warning when sys.prefix differs from sys.base_prefix (venv active)."""
    with patch.object(sys, "prefix", "/some/venv"), \
         patch.object(sys, "base_prefix", "/usr"):
        _warn_if_outside_venv()
    assert capsys.readouterr().err == ""


def test_no_warning_when_no_local_venv(capsys, tmp_path, monkeypatch):
    """No warning when no .venv directory exists nearby."""
    monkeypatch.chdir(tmp_path)
    with patch.object(sys, "prefix", "/usr"), \
         patch.object(sys, "base_prefix", "/usr"):
        _warn_if_outside_venv()
    assert capsys.readouterr().err == ""


def test_warning_when_outside_venv(capsys, tmp_path, monkeypatch):
    """Warning emitted when .venv exists but we're not inside it."""
    (tmp_path / ".venv").mkdir()
    monkeypatch.chdir(tmp_path)
    with patch.object(sys, "prefix", "/usr"), \
         patch.object(sys, "base_prefix", "/usr"):
        _warn_if_outside_venv()
    err = capsys.readouterr().err
    assert "Running outside the project .venv" in err
    assert "uv run" in err


def test_warning_when_venv_in_parent(capsys, tmp_path, monkeypatch):
    """Warning emitted when .venv is in the parent directory."""
    (tmp_path / ".venv").mkdir()
    child = tmp_path / "ontology-hub"
    child.mkdir()
    monkeypatch.chdir(child)
    with patch.object(sys, "prefix", "/usr"), \
         patch.object(sys, "base_prefix", "/usr"):
        _warn_if_outside_venv()
    err = capsys.readouterr().err
    assert "Running outside the project .venv" in err
