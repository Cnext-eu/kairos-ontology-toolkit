# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI surface for ``validate-dbt-contracts`` (issue #504)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.cli.shared import _SKILL_COVERED_COMMANDS

_TARGET_CLASS = "https://example.test/party#Customer"
_ENV = {"KAIROS_SKILL_CONTEXT": "1"}


def _hub(tmp_path: Path) -> Path:
    hub = tmp_path / "ontology-hub"
    ontologies = hub / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    (hub / "integration").mkdir()
    (ontologies / "party.ttl").write_text(
        textwrap.dedent("""
            @prefix party: <https://example.test/party#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
            party:Customer a owl:Class ; rdfs:label "Customer" .
            """).strip(),
        encoding="utf-8",
    )
    return hub


def _write_contract(hub: Path, name: str, **overrides) -> None:
    models = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate"
    models.mkdir(parents=True, exist_ok=True)
    (models / f"{name}.sql").write_text("select 1\n", encoding="utf-8")
    kairos = {
        "target_class": _TARGET_CLASS,
        "virtual_source_iri": f"https://example.test/virtual/{name}",
        "grain": "one row per customer",
        "grain_key": ["customer_id"],
        "supported_adapters": ["fabric-warehouse"],
    }
    kairos.update(overrides)
    (models / f"{name}.yml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "models": [
                    {
                        "name": name,
                        "description": f"Contracted {name}.",
                        "config": {"materialized": "view", "contract": {"enforced": True}},
                        "meta": {"kairos": kairos},
                        "columns": [{"name": "customer_id", "data_type": "string"}],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _run(hub: Path, monkeypatch, *args):
    monkeypatch.chdir(hub)
    return CliRunner().invoke(cli, ["validate-dbt-contracts", *args], env=_ENV)


def test_clean_hub_exits_zero_with_a_json_payload(tmp_path: Path, monkeypatch) -> None:
    hub = _hub(tmp_path)
    _write_contract(hub, "int_merged__customer")

    result = _run(hub, monkeypatch)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert payload["contracted_models"] == ["int_merged__customer"]


def test_unresolvable_target_class_exits_one(tmp_path: Path, monkeypatch) -> None:
    hub = _hub(tmp_path)
    _write_contract(hub, "int_merged__customer", target_class="https://example.test/party#Ghost")

    result = _run(hub, monkeypatch)

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert [f["code"] for f in payload["findings"] if f["severity"] == "error"] == [
        "dbt-contract.target-class-unresolved"
    ]


def test_warnings_alone_still_exit_zero(tmp_path: Path, monkeypatch) -> None:
    """A layering/wiring advisory must not block an author mid-way through the tree."""
    hub = _hub(tmp_path)
    _write_contract(hub, "int_merged__customer")  # authored, but nothing binds it

    result = _run(hub, monkeypatch)

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [f["code"] for f in payload["findings"]] == ["dbt-contract.model-unbound"]
    assert payload["passed"] is True


def test_stdout_is_pure_payload_and_diagnostics_go_to_stderr(tmp_path: Path, monkeypatch) -> None:
    """The documented machine-output contract: `--format json | jq .` must parse."""
    hub = _hub(tmp_path)
    _write_contract(hub, "int_merged__customer", target_class="https://example.test/party#Ghost")

    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["validate-dbt-contracts"], env=_ENV)

    json.loads(result.stdout)  # would raise if a glyph line leaked onto stdout
    assert "❌" not in result.stdout


def test_yaml_format_is_supported(tmp_path: Path, monkeypatch) -> None:
    hub = _hub(tmp_path)
    _write_contract(hub, "int_merged__customer")

    result = _run(hub, monkeypatch, "--format", "yaml")

    assert result.exit_code == 0
    assert yaml.safe_load(result.stdout)["schema_version"] == 1


def test_hub_without_transforms_tree_is_not_an_error(tmp_path: Path, monkeypatch) -> None:
    result = _run(_hub(tmp_path), monkeypatch)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["transforms_present"] is False


def test_outside_a_hub_fails_with_a_clear_message(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["validate-dbt-contracts"], env=_ENV)

    assert result.exit_code == 1
    assert "Cannot locate an ontology hub" in result.output


def test_is_gated_to_the_authoring_skill_not_the_execute_skill() -> None:
    """It lints the tree an author is writing, so the authoring skill should be running it."""
    assert _SKILL_COVERED_COMMANDS["validate-dbt-contracts"] == "kairos-develop-dbt-transformation"
    assert _SKILL_COVERED_COMMANDS["validate-dbt"] == "kairos-execute-validate"
