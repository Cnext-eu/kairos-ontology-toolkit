# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for the v5 compile command."""

from __future__ import annotations

import json

from click.testing import CliRunner

from kairos_ontology.cli.main import cli

from .test_compiler_kernel import _hub


def test_compile_requires_exactly_one_mode(tmp_path):
    hub = _hub(tmp_path)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=hub):
        missing = runner.invoke(cli, ["compile", "party"])
        conflicting = runner.invoke(cli, ["compile", "party", "--check", "--explain"])
    assert missing.exit_code == 2
    assert conflicting.exit_code == 2
    assert "exactly one" in missing.output


def test_compile_check_and_json_explain_are_write_free(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    before = {path.relative_to(hub) for path in hub.rglob("*")}
    checked = CliRunner().invoke(cli, ["compile", "party", "--check"])
    explained = CliRunner().invoke(cli, ["compile", "party", "--explain", "--format", "json"])
    after = {path.relative_to(hub) for path in hub.rglob("*")}
    assert checked.exit_code == 0, checked.output
    assert "compile check passed" in checked.output
    assert explained.exit_code == 0, explained.output
    payload = json.loads(explained.stdout)
    assert payload["succeeded"] is True
    assert payload["explain"]["entities"][0]["name"] == "crm-customer"
    assert before == after


def test_compile_resolves_nested_hub_from_repository_root(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    hub = _hub(repository / "ontology-hub")
    monkeypatch.chdir(repository)

    result = CliRunner().invoke(cli, ["compile", "party", "--check"])

    assert result.exit_code == 0, result.output
    assert "compile check passed" in result.output
    assert hub.is_dir()


def test_compile_returns_nonzero_for_diagnostics(tmp_path, monkeypatch):
    hub = _hub(tmp_path, broken_column=True)
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--check"])
    assert result.exit_code == 1
    assert "safety.column-unresolved" in result.output


def test_compile_emit_writes_only_owned_domain_subtree(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    output = tmp_path / "generated"
    unrelated = output / "invoice" / "user.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", str(output)])
    assert result.exit_code == 0, result.output
    target = output / "party"
    assert (target / "models/silver/party/customer.sql").is_file()
    assert (target / ".kairos-compile-manifest.json").is_file()
    assert unrelated.read_text(encoding="utf-8") == "keep"
