# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for python -m kairos_ontology invocation support."""

import runpy
import sys
from unittest.mock import patch


def test_main_module_is_importable():
    import kairos_ontology.__main__  # noqa: F401


def test_main_module_exposes_cli():
    from kairos_ontology.__main__ import cli

    assert callable(cli)


def test_main_module_runs_via_runpy():
    """Verify the module can be executed via runpy (same mechanism as python -m)."""
    with patch("kairos_ontology.cli.main.cli") as mock_cli:
        mock_cli.side_effect = SystemExit(0)
        try:
            runpy.run_module("kairos_ontology", run_name="__main__", alter_sys=True)
        except SystemExit as exc:
            assert exc.code == 0
        mock_cli.assert_called_once()
