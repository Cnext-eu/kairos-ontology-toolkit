# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the _warn_if_outside_venv startup guard.

Since #587 the guard is identity-based: inside a managed hub it compares
``sys.prefix`` against the hub's own ``.venv`` instead of merely asking "am I in
*some* venv?". A pipx / ``uv tool`` global install IS a venv, which the old
mechanism check waved through. Outside a managed hub the old bare-global
heuristic remains as a fallback. Every test pins ``cwd`` to a tmp directory:
pytest's own cwd is the toolkit repo, which is itself a managed root with a
``.venv`` and would otherwise leak into ``find_managed_root()``.
"""

from pathlib import Path
from unittest.mock import patch

import os
import sys

import pytest

from kairos_ontology.cli.main import _warn_if_outside_venv


def _make_managed_hub(root: Path) -> Path:
    """Create a minimal toolkit-managed hub root with its own .venv."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test-hub"\n\n[tool.kairos]\n', encoding="utf-8"
    )
    (root / ".venv").mkdir()
    return root


def test_no_warning_when_running_the_hubs_own_venv(capsys, tmp_path, monkeypatch):
    """(a) sys.prefix IS the managed hub's .venv — nothing to warn about."""
    hub = _make_managed_hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    with (
        patch.object(sys, "prefix", str(hub / ".venv")),
        patch.object(sys, "base_prefix", "/usr"),
    ):
        _warn_if_outside_venv()
    assert capsys.readouterr().err == ""


@pytest.mark.skipif(os.name != "nt", reason="drive-letter case is a Windows-only concern")
def test_no_warning_when_only_the_drive_letter_case_differs(capsys, tmp_path, monkeypatch):
    """Same venv path with swapped drive-letter case (c: vs C:) is the same identity.

    The comparison goes through ``os.path.normcase``: on Windows the drive-letter
    case can vary between invocations, and a case-sensitive compare would warn on
    every legitimate ``uv run``.
    """
    hub = _make_managed_hub(tmp_path / "hub")
    venv_path = str(hub / ".venv")
    assert venv_path[1] == ":", venv_path  # sanity: expected a drive-letter path
    drive = venv_path[0]
    swapped = (drive.lower() if drive.isupper() else drive.upper()) + venv_path[1:]
    monkeypatch.chdir(hub)
    with (
        patch.object(sys, "prefix", swapped),
        patch.object(sys, "base_prefix", "/usr"),
    ):
        _warn_if_outside_venv()
    assert capsys.readouterr().err == ""


def test_warning_when_running_a_foreign_venv_inside_a_hub(capsys, tmp_path, monkeypatch):
    """(b) pipx-style install: a venv, but not THIS hub's venv — warn (#587).

    The old mechanism check (``sys.prefix != sys.base_prefix``) returned early
    here; this is the exact gap the identity comparison closes.
    """
    hub = _make_managed_hub(tmp_path / "hub")
    pipx_venv = tmp_path / "pipx" / "venvs" / "kairos-ontology"
    pipx_venv.mkdir(parents=True)
    monkeypatch.chdir(hub)
    with (
        patch.object(sys, "prefix", str(pipx_venv)),
        patch.object(sys, "base_prefix", "/usr"),
    ):
        _warn_if_outside_venv()
    err = capsys.readouterr().err
    assert "not this hub's uv-managed environment" in err
    assert "kairos-ontology-referencemodels" in err
    assert "uv run kairos-ontology" in err


def test_warning_when_bare_global_python_inside_a_hub(capsys, tmp_path, monkeypatch):
    """A bare system Python inside a managed hub gets the identity warning too."""
    hub = _make_managed_hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    with patch.object(sys, "prefix", "/usr"), patch.object(sys, "base_prefix", "/usr"):
        _warn_if_outside_venv()
    err = capsys.readouterr().err
    assert "not this hub's uv-managed environment" in err
    assert "uv run kairos-ontology" in err


def test_warning_when_run_from_hub_subdirectory(capsys, tmp_path, monkeypatch):
    """find_managed_root walks up, so a content subdirectory still triggers the guard."""
    hub = _make_managed_hub(tmp_path / "hub")
    subdir = hub / "model" / "ontologies"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    with (
        patch.object(sys, "prefix", str(tmp_path / "other-venv")),
        patch.object(sys, "base_prefix", "/usr"),
    ):
        _warn_if_outside_venv()
    assert "not this hub's uv-managed environment" in capsys.readouterr().err


def test_no_warning_in_a_venv_outside_any_managed_root(capsys, tmp_path, monkeypatch):
    """(c) no managed root anywhere and inside some venv — stay silent."""
    monkeypatch.chdir(tmp_path)
    with (
        patch.object(sys, "prefix", "/some/venv"),
        patch.object(sys, "base_prefix", "/usr"),
    ):
        _warn_if_outside_venv()
    assert capsys.readouterr().err == ""


def test_no_warning_when_no_local_venv(capsys, tmp_path, monkeypatch):
    """No warning when no .venv directory exists nearby (and no managed root)."""
    monkeypatch.chdir(tmp_path)
    with patch.object(sys, "prefix", "/usr"), patch.object(sys, "base_prefix", "/usr"):
        _warn_if_outside_venv()
    assert capsys.readouterr().err == ""


def test_legacy_warning_when_outside_venv(capsys, tmp_path, monkeypatch):
    """(d) legacy fallback: bare global Python + local .venv, no managed root — still warns."""
    (tmp_path / ".venv").mkdir()
    monkeypatch.chdir(tmp_path)
    with patch.object(sys, "prefix", "/usr"), patch.object(sys, "base_prefix", "/usr"):
        _warn_if_outside_venv()
    err = capsys.readouterr().err
    assert "Running outside the uv-managed project environment" in err
    assert "Run `uv run kairos-ontology`; no manual activation is needed." in err


def test_legacy_warning_when_venv_in_parent(capsys, tmp_path, monkeypatch):
    """Legacy fallback also fires when the .venv is in the parent directory."""
    (tmp_path / ".venv").mkdir()
    child = tmp_path / "ontology-hub"
    child.mkdir()
    monkeypatch.chdir(child)
    with patch.object(sys, "prefix", "/usr"), patch.object(sys, "base_prefix", "/usr"):
        _warn_if_outside_venv()
    err = capsys.readouterr().err
    assert "Running outside the uv-managed project environment" in err
