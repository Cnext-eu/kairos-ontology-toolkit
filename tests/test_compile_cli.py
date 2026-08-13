# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for the v5 compile command."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.observability import reset_logging

from .test_compiler_kernel import _hub


@pytest.fixture(autouse=True)
def _clean_logging():
    # `cli`'s root group installs handlers and sets `propagate = False` on the
    # `kairos_ontology` logger (see configure_logging()); the normal teardown path
    # only runs on a *successful* invocation (Click's result_callback). A test in
    # this file that hits a `click.exceptions.Exit`/`SystemExit` path (e.g. the
    # discovery-gate failures below) skips that teardown and would otherwise leak
    # `propagate = False` into whichever test runs next in the session, starving
    # its `caplog` of records (see test_cli_exception_boundary.py's identical
    # fixture for the same reason).
    reset_logging()
    yield
    reset_logging()


def test_compile_requires_exactly_one_mode(tmp_path):
    hub = _hub(tmp_path)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=hub):
        missing = runner.invoke(cli, ["compile", "party"])
        conflicting = runner.invoke(cli, ["compile", "party", "--check", "--emit"])
    assert missing.exit_code == 2
    assert conflicting.exit_code == 2
    assert "exactly one" in missing.output
    assert "cannot be combined" in conflicting.output


def test_compile_check_and_explain_may_be_combined(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    before = {path.relative_to(hub) for path in hub.rglob("*")}

    combined = CliRunner().invoke(cli, ["compile", "party", "--check", "--explain"])
    after = {path.relative_to(hub) for path in hub.rglob("*")}

    assert combined.exit_code == 0, combined.output
    assert "compile check passed" in combined.output
    assert "entity binding(s)" in combined.output
    assert before == after


def test_compile_check_and_explain_json_includes_both(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli, ["compile", "party", "--check", "--explain", "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["mode"] == "check+explain"
    assert payload["diagnostics"] == []
    assert payload["explain"]["entities"][0]["name"] == "crm-customer"


def test_compile_json_payload_includes_operation_id(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli, ["compile", "party", "--check", "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "operation_id" in payload
    assert isinstance(payload["operation_id"], str)
    assert payload["operation_id"]  # non-empty when CLI is the entry point


def test_compile_explain_and_emit_cannot_be_combined(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--explain", "--emit"])

    assert result.exit_code == 2
    assert "cannot be combined" in result.output


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


def test_compile_bare_emit_requires_confirm_emit_flag(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit"])
    assert result.exit_code == 2
    assert "--confirm-emit" in result.output
    assert not (hub.parent / "ontology-hub-publish").exists()


def test_compile_emit_with_confirm_emit_succeeds(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert result.exit_code == 0, result.output


def test_compile_returns_nonzero_for_diagnostics(tmp_path, monkeypatch):
    hub = _hub(tmp_path, broken_column=True)
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--check"])
    assert result.exit_code == 1
    assert "safety.column-unresolved" in result.output


def test_compile_emit_writes_unified_dbt_project_preserving_unowned_files(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    output = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"
    unrelated = output / "invoice" / "user.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert result.exit_code == 0, result.output
    assert (output / "models/silver/party/customer.sql").is_file()
    assert (output / ".kairos-compile-manifest.party.json").is_file()
    assert (output / ".kairos-compile-manifest.shared.json").is_file()
    assert not (output / "party").exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_compile_emit_rejects_an_explicit_directory_argument(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit", "some/dir"])
    # --emit is a pure flag; the extra token is parsed as a second DOMAIN argument
    # and rejected, so no folder can be created under the hub.
    assert result.exit_code != 0
    assert not (hub / "some").exists()
    assert not (hub / "ontology-hub-publish").exists()


def test_compile_bare_emit_targets_publish_root_without_warning(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert result.exit_code == 0, result.output
    assert "outside this hub" not in result.stderr
    expected = hub.parent / "ontology-hub-publish/medallion/dbt/models/silver/party/customer.sql"
    assert expected.is_file()
    # Never nested inside the hub.
    assert not (hub / "ontology-hub-publish").exists()


def test_compile_emit_from_repo_root_lands_in_sibling_publish_root(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    hub = _hub(repository / "ontology-hub")
    monkeypatch.chdir(repository)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert result.exit_code == 0, result.output
    expected = repository / "ontology-hub-publish/medallion/dbt/models/silver/party/customer.sql"
    assert expected.is_file()
    assert not (hub / "ontology-hub-publish").exists()


# ---------------------------------------------------------------------------
# Issue #389/#390: `compile <domain>` is inherently single-domain, so an unresolved
# DD-148 judgment tagged to an unrelated domain must no longer block it; one tagged to
# the compiled domain, or left cross-cutting (no likely_domains), still must.
# ---------------------------------------------------------------------------


def test_compile_check_succeeds_when_unresolved_judgment_tagged_to_other_domain(
    tmp_path, monkeypatch
):
    from discovery_fixtures import write_discovery_artifact_with_unresolved_judgment

    hub = _hub(tmp_path)
    write_discovery_artifact_with_unresolved_judgment(hub, likely_domains=["customs"])
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--check"])

    assert result.exit_code == 0, result.output
    assert "compile check passed" in result.output


def test_compile_check_fails_when_unresolved_judgment_tagged_to_compiled_domain(
    tmp_path, monkeypatch
):
    from discovery_fixtures import write_discovery_artifact_with_unresolved_judgment

    hub = _hub(tmp_path)
    write_discovery_artifact_with_unresolved_judgment(hub, likely_domains=["party"])
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--check"])

    assert result.exit_code != 0
    assert "Unresolved discovery item" in result.output


def test_compile_check_fails_when_unresolved_judgment_is_cross_cutting(tmp_path, monkeypatch):
    from discovery_fixtures import write_discovery_artifact_with_unresolved_judgment

    hub = _hub(tmp_path)
    write_discovery_artifact_with_unresolved_judgment(hub)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--check"])

    assert result.exit_code != 0
    assert "Unresolved discovery item" in result.output
