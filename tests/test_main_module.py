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


def test_ensure_utf8_stdio():
    """Verify _ensure_utf8_stdio sets stdout/stderr to UTF-8."""
    from kairos_ontology.cli.main import _ensure_utf8_stdio

    _ensure_utf8_stdio()
    if hasattr(sys.stdout, "encoding"):
        assert sys.stdout.encoding.lower().replace("-", "") == "utf8"
    if hasattr(sys.stderr, "encoding"):
        assert sys.stderr.encoding.lower().replace("-", "") == "utf8"


def test_unicode_print_does_not_raise(capsys):
    """Verify Unicode emoji can be printed without UnicodeEncodeError."""
    from kairos_ontology.cli.main import _ensure_utf8_stdio

    _ensure_utf8_stdio()
    print("✓ ✅ 🚀 📦 ⚠️ ✗ ❌")
    captured = capsys.readouterr()
    assert "✓" in captured.out
