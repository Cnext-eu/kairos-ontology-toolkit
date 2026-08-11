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
from kairos_ontology.core.hub_inspection import _authored_ttl, gather_hub_input_snapshot
from kairos_ontology.core.next_actions import CompileStatus, DiscoveryConformanceStatus, InputStatus

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
    stdout = result.output[len(result.stderr) :]
    return json.loads(stdout)


def test_next_json_is_clean_on_stdout_with_banner_on_stderr(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--format", "json"])
    assert result.exit_code == 0
    payload = _stdout_json(result)  # would raise if stdout were polluted
    assert payload["schema_version"] == 2
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
    text = binding.read_text(encoding="utf-8").replace("domain: party", "domain: orphan")
    binding.write_text(text, encoding="utf-8")

    snapshot = gather_hub_input_snapshot(hub)
    assert "orphan" in snapshot.binding_only_domains
    orphan = next(d for d in snapshot.domains if d.domain == "orphan")
    assert orphan.ontology is InputStatus.MISSING
    assert orphan.has_bindings is True


def test_gather_snapshot_observes_emitted_project_and_adapter(hub):
    without = gather_hub_input_snapshot(hub)
    assert without.emitted_dbt_project is InputStatus.MISSING
    assert without.adapter == "fabric"

    project = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"
    project.mkdir(parents=True)
    (project / "dbt_project.yml").write_text("name: hub\n", encoding="utf-8")

    with_emit = gather_hub_input_snapshot(hub)
    assert with_emit.emitted_dbt_project is InputStatus.PRESENT


def test_gather_snapshot_observes_discovery_conformance(hub):
    # v5-hub ships a resolved (mode: interactive) discovery artifact.
    resolved = gather_hub_input_snapshot(hub)
    assert resolved.discovery_conformance is DiscoveryConformanceStatus.VALID

    artifact_path = hub / "integration" / "discovery" / "core-concepts-conformance.yaml"
    artifact_path.write_text(
        "\n".join(
            [
                "schema_version: 2",
                "generated_by: test",
                "mode: fleet",
                "archetype:\n  id: x\n  confirmed_by: human",
                "core_concepts:",
                "  - uri: u1",
                "    label: One",
                "    decided_by: ai",
                "    needs_confirmation: true",
            ]
        ),
        encoding="utf-8",
    )
    unresolved = gather_hub_input_snapshot(hub)
    assert unresolved.discovery_conformance is DiscoveryConformanceStatus.UNRESOLVED_FLEET


def test_next_surfaces_resolve_discovery_open_questions_action(hub, monkeypatch):
    artifact_path = hub / "integration" / "discovery" / "core-concepts-conformance.yaml"
    artifact_path.write_text(
        "\n".join(
            [
                "schema_version: 2",
                "generated_by: test",
                "mode: fleet",
                "archetype:\n  id: x\n  confirmed_by: human",
                "core_concepts:",
                "  - uri: u1",
                "    label: One",
                "    decided_by: ai",
                "    needs_confirmation: true",
            ]
        ),
        encoding="utf-8",
    )
    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    action = next(a for a in payload["actions"] if a["kind"] == "resolve-discovery-open-questions")
    assert action["status"] == "blocking"
    assert action["blocking"] is True
    assert action["skill"] == "kairos-design-discovery"


def test_authored_ttl_rejects_scaffold_templates_regardless_of_naming(tmp_path):
    # Issue #288: init's scaffold uses `glossary-template.ttl` (a `-template.ttl` suffix),
    # not the legacy `*.template` convention — both must be rejected as non-authored.
    assert _authored_ttl(tmp_path / "glossary-template.ttl") is False
    assert _authored_ttl(tmp_path / "foo.template") is False
    assert _authored_ttl(tmp_path / "party-discovery.ttl") is True


def test_gather_snapshot_discovery_ignores_scaffold_template_only(hub):
    # Issue #288: a freshly-scaffolded businessdiscovery/ containing only the init-copied
    # glossary-template.ttl (plus README.md) has zero authored evidence and must report
    # MISSING, not PRESENT — otherwise the DD-148 discovery gate is silently disabled.
    discovery_dir = hub / "businessdiscovery"
    discovery_dir.mkdir()
    (discovery_dir / "glossary-template.ttl").write_text("# scaffold\n", encoding="utf-8")
    (discovery_dir / "README.md").write_text("# discovery\n", encoding="utf-8")

    scaffold_only = gather_hub_input_snapshot(hub)
    assert scaffold_only.discovery is InputStatus.MISSING

    (discovery_dir / "party-discovery.ttl").write_text("# authored\n", encoding="utf-8")
    with_authored = gather_hub_input_snapshot(hub)
    assert with_authored.discovery is InputStatus.PRESENT


def test_next_surfaces_optional_validate_dbt_after_emit(hub, monkeypatch):
    project = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"
    project.mkdir(parents=True)
    (project / "dbt_project.yml").write_text("name: hub\n", encoding="utf-8")

    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    gate = next(a for a in payload["actions"] if a["kind"] == "validate-dbt")
    assert gate["status"] == "optional"
    assert gate["command"] == "kairos-ontology validate-dbt --platform fabric"
