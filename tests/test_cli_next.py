# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for ``kairos-ontology next`` (DD-137)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.hub_inspection import gather_hub_input_snapshot
from kairos_ontology.core.next_actions import CompileStatus, InputStatus

_HUB = Path(__file__).parent / "scenarios" / "v5-hub"


@pytest.fixture()
def hub(tmp_path: Path) -> Path:
    dest = tmp_path / "hub"
    shutil.copytree(_HUB, dest)
    (dest / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    return dest


def _invoke(hub: Path, monkeypatch, args):
    monkeypatch.chdir(hub)
    return CliRunner().invoke(cli, ["next", *args])


def _stdout_json(result):
    """Return parsed stdout JSON, proving stdout is clean once stderr is removed.

    The test runner merges stdout+stderr into ``result.output`` while keeping
    ``result.stderr`` separate; at the OS level stdout carries only the JSON.
    """
    stdout = result.output[len(result.stderr):]
    return json.loads(stdout)


def test_next_json_is_clean_on_stdout_with_banner_on_stderr(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--format", "json"])
    assert result.exit_code == 0
    payload = _stdout_json(result)  # would raise if stdout were polluted
    assert payload["schema_version"] == 1
    assert payload["compile_ran"] is True
    assert "DD-137" in result.stderr
    kinds = {action["kind"] for action in payload["actions"]}
    assert "compile-emit" in kinds


def test_next_text_reports_inputs_and_actions(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, [])
    assert result.exit_code == 0
    assert "next-action proposal" in result.output
    assert "compile-emit" in result.output
    assert "party" in result.output


def test_next_no_compile_marks_downstream_indeterminate(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--no-compile", "--format", "json"])
    payload = _stdout_json(result)
    assert payload["compile_ran"] is False
    statuses = {action["kind"]: action["status"] for action in payload["actions"]}
    assert statuses.get("run-check") == "indeterminate"
    assert "compile-emit" not in statuses


def test_next_domain_filter_restricts_domains(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--domain", "does-not-exist", "--format", "json"])
    payload = _stdout_json(result)
    domains = {action["domain"] for action in payload["actions"] if action["domain"]}
    assert "party" not in domains


def test_next_hub_not_found_is_operational_error(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    result = CliRunner().invoke(cli, ["next", "--format", "json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"] == "hub-not-found"


def test_gather_snapshot_reports_passing_domain(hub):
    snapshot = gather_hub_input_snapshot(hub)
    assert snapshot.hub_root == str(hub.resolve())
    party = next(d for d in snapshot.domains if d.domain == "party")
    assert party.ontology is InputStatus.PRESENT
    assert party.has_bindings is True
    assert party.compile_status is CompileStatus.PASSED


def test_gather_snapshot_flags_binding_without_ontology(hub):
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    text = binding.read_text(encoding="utf-8").replace(
        "domain: party", "domain: orphan"
    )
    binding.write_text(text, encoding="utf-8")

    snapshot = gather_hub_input_snapshot(hub)
    assert "orphan" in snapshot.binding_only_domains
    orphan = next(d for d in snapshot.domains if d.domain == "orphan")
    assert orphan.ontology is InputStatus.MISSING
    assert orphan.has_bindings is True
