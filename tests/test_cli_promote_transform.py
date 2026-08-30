# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI surface for ``promote-transform`` (issue #634)."""

from __future__ import annotations

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
        textwrap.dedent(
            """
            @prefix party: <https://example.test/party#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
            party:Customer a owl:Class ; rdfs:label "Customer" .
            """
        ).strip(),
        encoding="utf-8",
    )
    return hub


def _dataplatform(tmp_path: Path) -> Path:
    dataplatform = tmp_path / "dataplatform"
    (dataplatform / "models").mkdir(parents=True)
    return dataplatform


def _model_entry(name: str, **overrides) -> dict:
    kairos = {
        "target_class": _TARGET_CLASS,
        "virtual_source_iri": f"https://example.test/virtual/{name}",
        "grain": "one row per customer",
        "grain_key": ["customer_id"],
        "supported_adapters": ["fabric"],
    }
    kairos.update(overrides.pop("kairos", {}))
    entry = {
        "name": name,
        "description": f"Contracted {name}.",
        "config": {"materialized": "view", "contract": {"enforced": True}},
        "meta": {"kairos": kairos},
        "columns": [{"name": "customer_id", "data_type": "string"}],
    }
    entry.update(overrides)
    return entry


def _write_model(dataplatform: Path, name: str, *, sibling_entries: list[dict] | None = None,
                  **overrides) -> tuple[Path, Path]:
    """Write <name>.sql + <name>.yml as a plain dataplatform-authored dbt model."""
    models_dir = dataplatform / "models"
    sql_path = models_dir / f"{name}.sql"
    sql_path.write_text("select 1 as customer_id\n", encoding="utf-8")
    entries = [_model_entry(name, **overrides)]
    if sibling_entries:
        entries = sibling_entries + entries
    yml_path = models_dir / f"{name}.yml"
    yml_path.write_text(
        yaml.safe_dump({"version": 2, "models": entries}, sort_keys=False),
        encoding="utf-8",
    )
    return sql_path, yml_path


def _run(monkeypatch, cwd: Path, *args):
    monkeypatch.chdir(cwd)
    return CliRunner().invoke(cli, ["promote-transform", *args], env=_ENV)


# --- successful promotion -------------------------------------------------------------------


def test_dry_run_reports_destinations_without_writing_files(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    dataplatform = _dataplatform(tmp_path)
    sql_path, _ = _write_model(dataplatform, "int_merged__party")

    result = _run(
        monkeypatch,
        dataplatform,
        str(sql_path),
        "--domain",
        "party",
        "--hub-root",
        str(hub),
        "--dry-run",
    )

    assert result.exit_code == 0, result.output
    dest_dir = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "party"
    assert not (dest_dir / "int_merged__party.sql").exists()
    assert not (dest_dir / "int_merged__party.yml").exists()
    assert "would promote" in result.output.lower()
    assert str(dest_dir / "int_merged__party.sql") in result.output
    assert str(dest_dir / "int_merged__party.yml") in result.output


def test_real_run_writes_files_validates_and_prints_next_steps(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    dataplatform = _dataplatform(tmp_path)
    sql_path, _ = _write_model(dataplatform, "int_merged__party")

    result = _run(
        monkeypatch, dataplatform, str(sql_path), "--domain", "party", "--hub-root", str(hub)
    )

    assert result.exit_code == 0, result.output
    dest_dir = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "party"
    assert (dest_dir / "int_merged__party.sql").is_file()
    assert (dest_dir / "int_merged__party.yml").is_file()
    document = yaml.safe_load((dest_dir / "int_merged__party.yml").read_text(encoding="utf-8"))
    assert document["version"] == 2
    assert [m["name"] for m in document["models"]] == ["int_merged__party"]
    assert "Contract validated" in result.output
    assert "kairos-design-mapping" in result.output
    assert "Decision Log" in result.output
    assert "kairos-ontology decision new" in result.output


def test_non_merged_intermediate_model_skips_decision_log_guidance(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    dataplatform = _dataplatform(tmp_path)
    sql_path, _ = _write_model(dataplatform, "int_crm__party")

    result = _run(
        monkeypatch, dataplatform, str(sql_path), "--domain", "party", "--hub-root", str(hub)
    )

    assert result.exit_code == 0, result.output
    assert "kairos-design-mapping" in result.output
    assert "Decision Log" not in result.output


# --- naming-convention rejection -------------------------------------------------------------


def test_non_conforming_model_name_is_rejected(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    dataplatform = _dataplatform(tmp_path)
    sql_path, _ = _write_model(dataplatform, "stg_crm__party")

    result = _run(
        monkeypatch, dataplatform, str(sql_path), "--domain", "party", "--hub-root", str(hub)
    )

    assert result.exit_code != 0
    assert "naming convention" in result.output


# --- ambiguous properties file --------------------------------------------------------------


def test_ambiguous_properties_file_fails_closed(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    dataplatform = _dataplatform(tmp_path)
    models_dir = dataplatform / "models"
    sql_path = models_dir / "int_merged__party.sql"
    sql_path.write_text("select 1 as customer_id\n", encoding="utf-8")
    entry = _model_entry("int_merged__party")
    (models_dir / "a.yml").write_text(
        yaml.safe_dump({"version": 2, "models": [entry]}, sort_keys=False), encoding="utf-8"
    )
    (models_dir / "b.yml").write_text(
        yaml.safe_dump({"version": 2, "models": [entry]}, sort_keys=False), encoding="utf-8"
    )

    result = _run(
        monkeypatch, dataplatform, str(sql_path), "--domain", "party", "--hub-root", str(hub)
    )

    assert result.exit_code != 0
    assert "ambiguous" in result.output
    dest_dir = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "party"
    assert not dest_dir.exists()


# --- overwrite guard -------------------------------------------------------------------------


def test_destination_already_exists_without_force_is_refused(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    dataplatform = _dataplatform(tmp_path)
    sql_path, _ = _write_model(dataplatform, "int_merged__party")

    dest_dir = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "party"
    dest_dir.mkdir(parents=True)
    (dest_dir / "int_merged__party.sql").write_text("select 2\n", encoding="utf-8")

    result = _run(
        monkeypatch, dataplatform, str(sql_path), "--domain", "party", "--hub-root", str(hub)
    )

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert (dest_dir / "int_merged__party.sql").read_text(encoding="utf-8") == "select 2\n"


def test_destination_already_exists_with_force_is_overwritten(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    dataplatform = _dataplatform(tmp_path)
    sql_path, _ = _write_model(dataplatform, "int_merged__party")

    dest_dir = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "party"
    dest_dir.mkdir(parents=True)
    (dest_dir / "int_merged__party.sql").write_text("select 2\n", encoding="utf-8")
    (dest_dir / "int_merged__party.yml").write_text("stale", encoding="utf-8")

    result = _run(
        monkeypatch,
        dataplatform,
        str(sql_path),
        "--domain",
        "party",
        "--hub-root",
        str(hub),
        "--force",
    )

    assert result.exit_code == 0, result.output
    assert (dest_dir / "int_merged__party.sql").read_text(encoding="utf-8") == (
        "select 1 as customer_id\n"
    )


# --- contract-validation failure / rollback ---------------------------------------------------


def test_contract_validation_failure_rolls_back_both_files(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    dataplatform = _dataplatform(tmp_path)
    # meta.kairos is present (so the model IS selected for contract parsing) but
    # target_class is not a valid HTTP(S) IRI -- an invalid, not missing, block.
    models_dir = dataplatform / "models"
    sql_path = models_dir / "int_merged__party.sql"
    sql_path.write_text("select 1 as customer_id\n", encoding="utf-8")
    entry = _model_entry("int_merged__party", kairos={"target_class": "not-an-iri"})
    (models_dir / "int_merged__party.yml").write_text(
        yaml.safe_dump({"version": 2, "models": [entry]}, sort_keys=False), encoding="utf-8"
    )

    result = _run(
        monkeypatch, dataplatform, str(sql_path), "--domain", "party", "--hub-root", str(hub)
    )

    assert result.exit_code != 0
    assert "failed contract validation" in result.output
    dest_dir = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "party"
    assert not (dest_dir / "int_merged__party.sql").exists()
    assert not (dest_dir / "int_merged__party.yml").exists()


# --- multi-model source yml: only the matching model lands; source untouched -----------------


def test_multi_model_source_yml_only_matching_model_is_promoted(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    dataplatform = _dataplatform(tmp_path)
    sibling = _model_entry("int_merged__other")
    sql_path, yml_path = _write_model(
        dataplatform, "int_merged__party", sibling_entries=[sibling]
    )
    before_bytes = yml_path.read_bytes()

    result = _run(
        monkeypatch, dataplatform, str(sql_path), "--domain", "party", "--hub-root", str(hub)
    )

    assert result.exit_code == 0, result.output
    dest_dir = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "party"
    document = yaml.safe_load((dest_dir / "int_merged__party.yml").read_text(encoding="utf-8"))
    assert [m["name"] for m in document["models"]] == ["int_merged__party"]
    # Source file must be completely unmodified (checksum/content comparison).
    assert yml_path.read_bytes() == before_bytes


# --- --hub-root explicit override -------------------------------------------------------------


def test_hub_root_override_works_outside_a_dataplatform_shaped_cwd(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    sql_path = scratch / "int_merged__party.sql"
    sql_path.write_text("select 1 as customer_id\n", encoding="utf-8")
    entry = _model_entry("int_merged__party")
    (scratch / "int_merged__party.yml").write_text(
        yaml.safe_dump({"version": 2, "models": [entry]}, sort_keys=False), encoding="utf-8"
    )

    result = _run(
        monkeypatch, scratch, str(sql_path), "--domain", "party", "--hub-root", str(hub)
    )

    assert result.exit_code == 0, result.output
    dest_dir = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "party"
    assert (dest_dir / "int_merged__party.sql").is_file()


def test_is_gated_to_the_authoring_skill() -> None:
    assert _SKILL_COVERED_COMMANDS["promote-transform"] == "kairos-develop-dbt-transformation"
