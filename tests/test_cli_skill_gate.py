# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the CLI soft skill-gate (_warn_if_no_skill_context)."""

import pytest

from kairos_ontology.cli.main import (
    _SKILL_COVERED_COMMANDS,
    _SKILL_CONTEXT_ENV_VARS,
    _warn_if_no_skill_context,
)


@pytest.fixture(autouse=True)
def _clear_skill_env(monkeypatch):
    """Ensure no skill-context sentinel leaks in from the environment."""
    for var in _SKILL_CONTEXT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_warns_for_skill_managed_command(capsys):
    _warn_if_no_skill_context("project")
    err = capsys.readouterr().err
    assert "skill-managed" in err
    assert "kairos-execute-project" in err
    assert "KAIROS_SKILL_CONTEXT=1" in err


def test_silent_for_ungated_command(capsys):
    """Commands without an owning skill (CLI exceptions) never warn."""
    for cmd in ("import-tmdl", "coverage-report", "propose-alignment", "lifecycle"):
        _warn_if_no_skill_context(cmd)
    assert capsys.readouterr().err == ""


def test_silent_for_unknown_subcommand(capsys):
    _warn_if_no_skill_context("does-not-exist")
    assert capsys.readouterr().err == ""


def test_silent_for_none_subcommand(capsys):
    """Group invoked with no subcommand (e.g. --help) must not warn."""
    _warn_if_no_skill_context(None)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("env_var", _SKILL_CONTEXT_ENV_VARS)
def test_sentinel_env_var_suppresses_warning(capsys, monkeypatch, env_var):
    monkeypatch.setenv(env_var, "1")
    _warn_if_no_skill_context("project")
    assert capsys.readouterr().err == ""


def test_empty_sentinel_does_not_suppress(capsys, monkeypatch):
    """An empty/falsey env var value is treated as 'not set'."""
    monkeypatch.setenv("KAIROS_SKILL_CONTEXT", "")
    _warn_if_no_skill_context("validate")
    assert "skill-managed" in capsys.readouterr().err


@pytest.mark.parametrize("cmd,skill", sorted(_SKILL_COVERED_COMMANDS.items()))
def test_every_gated_command_names_its_skill(capsys, cmd, skill):
    _warn_if_no_skill_context(cmd)
    err = capsys.readouterr().err
    assert "skill-managed" in err
    assert skill in err


def test_cli_exceptions_are_not_gated():
    """Documented CLI-only commands must stay out of the gate map."""
    for cmd in (
        "import-tmdl",
        "coverage-report",
        "propose-alignment",
        "generate-inventory",
        "check-inventory",
        "catalog-test",
        "lifecycle",
    ):
        assert cmd not in _SKILL_COVERED_COMMANDS
