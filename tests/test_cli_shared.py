# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``_read_hub_max_workers`` — hub-level concurrency default (issue #562 Problem 1)."""

from __future__ import annotations

from pathlib import Path

import click
import pytest

from kairos_ontology.cli.shared import _CLI_DEFAULT_MAX_WORKERS, _read_hub_max_workers


def _write_pyproject(path: Path, body: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text(body, encoding="utf-8")


class TestReadHubMaxWorkers:
    def test_none_hub_root_returns_none(self):
        assert _read_hub_max_workers(None) is None

    def test_no_pyproject_returns_none(self, tmp_path):
        assert _read_hub_max_workers(tmp_path) is None

    def test_no_tool_kairos_section_returns_none(self, tmp_path):
        _write_pyproject(tmp_path, "[project]\nname = 'x'\n")
        assert _read_hub_max_workers(tmp_path) is None

    def test_absent_key_returns_none(self, tmp_path):
        _write_pyproject(tmp_path, '[tool.kairos]\naccelerator = "logistics"\n')
        assert _read_hub_max_workers(tmp_path) is None

    def test_valid_value_is_returned(self, tmp_path):
        _write_pyproject(tmp_path, "[tool.kairos]\nmax_workers = 3\n")
        assert _read_hub_max_workers(tmp_path) == 3

    def test_found_only_at_hub_root_parent(self, tmp_path):
        """Mirrors resolve_hub_accelerator_detailed's dual-candidate lookup:
        hub_root may point at the ontology-hub subdirectory while
        pyproject.toml lives one level up."""
        ontology_hub = tmp_path / "ontology-hub"
        ontology_hub.mkdir()
        _write_pyproject(tmp_path, "[tool.kairos]\nmax_workers = 5\n")
        assert _read_hub_max_workers(ontology_hub) == 5

    @pytest.mark.parametrize("literal", ["0", "-1", "2.5", "true"])
    def test_invalid_value_raises(self, tmp_path, literal):
        _write_pyproject(tmp_path, f"[tool.kairos]\nmax_workers = {literal}\n")
        with pytest.raises(click.ClickException, match="positive integer"):
            _read_hub_max_workers(tmp_path)

    def test_malformed_toml_is_treated_as_absent(self, tmp_path):
        _write_pyproject(tmp_path, "[tool.kairos\nmax_workers = 3")
        assert _read_hub_max_workers(tmp_path) is None

    def test_cli_default_constant(self):
        assert _CLI_DEFAULT_MAX_WORKERS == 16
