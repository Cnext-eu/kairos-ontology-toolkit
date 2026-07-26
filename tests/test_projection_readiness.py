# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Release 2 fail-fast projection-readiness tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.projection_readiness import (
    ProjectionReadinessReport,
    _ordered_diagnostics,
    _remediation_plan,
    check_projection,
)
from kairos_ontology.core.projector import ProjectionRunError, run_projections
from kairos_ontology.core.projector import ProjectionReport


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_readiness_json_is_stable_and_versioned():
    report = ProjectionReadinessReport(
        toolkit_version="4.7.0rc6",
        status="ready",
        targets=("dbt",),
        domains=("party",),
        platform="fabric",
        accelerator="bsp",
        namespace="https://example.test/party#",
    )

    assert report.to_json() == report.to_json()
    payload = json.loads(report.to_json())
    assert payload["schema_version"] == "1.1"
    assert payload["mode"] == "fail_fast"
    assert payload["persisted"] is False


def test_schema_1_0_report_remains_readable_without_new_collections():
    report = ProjectionReadinessReport.from_dict(
        {
            "schema_version": "1.0",
            "toolkit_version": "4.7.0rc5",
            "status": "blocked",
            "targets": ["dbt"],
            "domains": ["party"],
            "platform": "fabric",
            "accelerator": "",
            "namespace": "",
            "blocker": {"stage": "planning", "message": "legacy blocker"},
        }
    )

    assert report.schema_version == "1.0"
    assert report.blocker is not None
    assert report.blocker.message == "legacy blocker"
    assert report.diagnostics == ()
    assert report.remediation_plan == ()


def test_check_projection_cli_option_parity_and_json(tmp_path, monkeypatch):
    hub = tmp_path / "ontology-hub"
    ontology = hub / "model" / "ontologies" / "party.ttl"
    ontology.parent.mkdir(parents=True)
    ontology.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> . "
        "<https://example.test/party> a owl:Ontology .",
        encoding="utf-8",
    )
    captured = {}

    def fake_check(**kwargs):
        captured.update(kwargs)
        return ProjectionReadinessReport(
            toolkit_version="test",
            status="ready",
            targets=("dbt",),
            domains=("party",),
            platform=kwargs["platform"],
            accelerator=kwargs["accelerator"] or "",
            namespace=kwargs["namespace"] or "",
        )

    monkeypatch.setattr(
        "kairos_ontology.core.projection_readiness.check_projection", fake_check
    )
    monkeypatch.setattr(
        "kairos_ontology.core.reference_modules.resolve_hub_accelerator",
        lambda **kwargs: kwargs["explicit"],
    )
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(
        cli,
        [
            "check-projection",
            "--ontology",
            str(ontology),
            "--target",
            "dbt",
            "--adapter",
            "databricks",
            "--accelerator",
            "bsp",
            "--namespace",
            "https://example.test/party#",
            "--json-output",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    assert captured["ontologies_path"] == ontology
    assert captured["platform"] == "databricks"
    assert captured["accelerator"] == "bsp"
    assert captured["namespace"] == "https://example.test/party#"
    assert json.loads(result.output)["schema_version"] == "1.1"


def test_check_projection_has_same_first_planning_error_as_project(
    temp_dir, ontology_files, monkeypatch, capsys
):
    message = "policy.first-blocker: deterministic failure [DD-test]"

    def fail(*args, **kwargs):
        raise ValueError(message)

    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_dbt_projector.plan_dbt_projection",
        fail,
    )
    readiness = check_projection(
        ontologies_path=ontology_files["customer"],
        catalog_path=None,
        output_path=temp_dir / "check-output",
        target="dbt",
        namespace=None,
        platform="fabric",
        emit_aspirational_stubs=False,
        degraded=False,
        ref_models_dir=None,
        accelerator=None,
    )
    assert readiness.blocker is not None
    assert readiness.blocker.message == message

    with pytest.raises(ProjectionRunError):
        run_projections(
            ontologies_path=ontology_files["customer"],
            catalog_path=None,
            output_path=temp_dir / "project-output",
            target="dbt",
        )
    assert message in capsys.readouterr().out


def test_blocked_cli_json_is_machine_readable_and_nonzero(tmp_path, monkeypatch):
    ontology = tmp_path / "broken.ttl"
    ontology.write_text("not valid Turtle @@@", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        [
            "check-projection",
            "--ontology",
            str(ontology),
            "--target",
            "dbt",
            "--json-output",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "blocked"
    assert payload["blocker"]["stage"] == "load"


def test_scenario_check_projection_reports_collected_blockers_without_writes(monkeypatch):
    hub = Path(__file__).parent / "scenarios" / "acme-hub"
    before = _snapshot(hub)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli,
        ["check-projection", "--target", "dbt", "--json-output"],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "blocked"
    assert payload["diagnostics"]
    assert _snapshot(hub) == before


def test_scenario_scoped_gate_writes_nothing_and_exposes_owner(monkeypatch):
    hub = Path(__file__).parent / "scenarios" / "acme-hub"
    before = _snapshot(hub)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli,
        [
            "check-projection",
            "--target",
            "dbt",
            "--scope",
            "source",
            "--json-output",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["scope"] == "source"
    assert payload["owner_skill"] == "kairos-design-source"
    assert payload["prerequisites"] == []
    assert _snapshot(hub) == before


def test_scenario_bound_silver_confirmation_writes_nothing(monkeypatch):
    hub = Path(__file__).parent / "scenarios" / "acme-hub"
    before = _snapshot(hub)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli,
        [
            "check-projection",
            "--target",
            "silver",
            "--scope",
            "silver",
            "--json-output",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["scope"] == "silver"
    assert payload["owner_skill"] == "kairos-design-silver"
    assert _snapshot(hub) == before


@pytest.mark.parametrize(
    ("target", "expected_mode"),
    [
        ("dbt", "collect"),
        ("silver", "collect"),
        ("powerbi", "collect"),
        ("neo4j", "fail_fast"),
    ],
)
def test_check_projection_selects_collection_only_for_converted_targets(
    tmp_path, monkeypatch, target, expected_mode
):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return ProjectionReport(
            toolkit_version="test",
            targets_requested=[target],
            domains={
                "party": {
                    "file": "party.ttl",
                    "triples": 1,
                    "namespace": "https://example.test/party#",
                    "status": "ok",
                }
            },
        )

    monkeypatch.setattr(
        "kairos_ontology.core.projector.run_projections",
        fake_run,
    )
    report = check_projection(
        ontologies_path=tmp_path,
        catalog_path=None,
        output_path=tmp_path / "output",
        target=target,
        namespace=None,
        platform="fabric",
        emit_aspirational_stubs=False,
        degraded=False,
        ref_models_dir=None,
        accelerator=None,
    )

    assert captured["diagnostic_mode"] == expected_mode
    assert report.mode == expected_mode


def test_check_projection_blocks_on_all_collected_release_rules(
    temp_dir, ontology_files, monkeypatch
):
    blocking_rules = (
        ("DD-109-runtime", "runtime policy is incomplete"),
        ("DD-106-prep-cast", "preparation cast is unsupported"),
        ("DD-107-adapter-capability", "mapping capability is unavailable"),
    )

    def collected_plan(*_args, **_kwargs):
        return None, SimpleNamespace(
            release=SimpleNamespace(blocking_rules=blocking_rules)
        )

    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_dbt_projector.plan_dbt_projection",
        collected_plan,
    )
    output = temp_dir / "check-output"
    projection = run_projections(
        ontologies_path=ontology_files["customer"],
        catalog_path=None,
        output_path=output,
        target="dbt",
        check_only=True,
        diagnostic_mode="collect",
    )
    assert projection.projections[0]["status"] == "error"
    assert len(projection.projections[0]["diagnostics"]) == 3

    report = check_projection(
        ontologies_path=ontology_files["customer"],
        catalog_path=None,
        output_path=output,
        target="dbt",
        namespace=None,
        platform="fabric",
        emit_aspirational_stubs=False,
        degraded=False,
        ref_models_dir=None,
        accelerator=None,
    )

    assert not report.ready
    assert report.status == "blocked"
    assert report.blocker is not None
    assert report.blocker.message == "DD-109-runtime: runtime policy is incomplete"
    assert [item["rule_id"] for item in report.diagnostics] == [
        "DD-106-prep-cast",
        "DD-107-adapter-capability",
        "DD-109-runtime",
    ]
    assert all(item["blocking"] for item in report.diagnostics)
    assert len(report.remediation_plan) == 3
    assert {item["id"] for item in report.diagnostics} == {
        item["id"] for item in projection.projections[0]["diagnostics"]
    }
    assert not output.exists()


def test_check_projection_cli_exits_nonzero_for_collected_release_blocker(
    temp_dir, ontology_files, monkeypatch
):
    def collected_plan(*_args, **_kwargs):
        return None, SimpleNamespace(
            release=SimpleNamespace(
                blocking_rules=(("DD-114-policy", "policy approval is missing"),)
            )
        )

    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_dbt_projector.plan_dbt_projection",
        collected_plan,
    )
    monkeypatch.chdir(temp_dir)
    result = CliRunner().invoke(
        cli,
        [
            "check-projection",
            "--ontology",
            str(ontology_files["customer"]),
            "--target",
            "dbt",
            "--json-output",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "blocked"
    assert payload["diagnostics"][0]["rule_id"] == "DD-114-policy"


def test_check_projection_green_collected_plan_remains_ready(
    temp_dir, ontology_files, monkeypatch
):
    def green_plan(*_args, **_kwargs):
        return None, SimpleNamespace(
            release=SimpleNamespace(blocking_rules=())
        )

    monkeypatch.setattr(
        "kairos_ontology.core.projections.medallion_dbt_projector.plan_dbt_projection",
        green_plan,
    )
    report = check_projection(
        ontologies_path=ontology_files["customer"],
        catalog_path=None,
        output_path=temp_dir / "check-output",
        target="dbt",
        namespace=None,
        platform="fabric",
        emit_aspirational_stubs=False,
        degraded=False,
        ref_models_dir=None,
        accelerator=None,
    )

    assert report.ready
    assert report.status == "ready"
    assert report.diagnostics == ()


def test_phase_scope_is_a_view_of_shared_diagnostic_ids(tmp_path, monkeypatch):
    diagnostics = [
        {
            "id": "shared-prep",
            "code": "prep.cast-invalid",
            "rule_id": "DD-test",
            "severity": "error",
            "blocking": True,
            "stage": "preparation",
            "owner_skill": "kairos-design-source",
            "resource_uri": "urn:source",
            "predicate_uri": "",
            "message": "invalid cast",
            "evidence": [],
            "depends_on": [],
            "remediation": "Fix cast.",
            "evaluation_status": "failed",
        },
        {
            "id": "shared-runtime",
            "code": "incremental.ordering-missing",
            "rule_id": "DD-test",
            "severity": "error",
            "blocking": True,
            "stage": "runtime",
            "owner_skill": "kairos-design-silver",
            "resource_uri": "urn:silver",
            "predicate_uri": "",
            "message": "missing ordering",
            "evidence": [],
            "depends_on": [],
            "remediation": "Fix runtime.",
            "evaluation_status": "failed",
        },
    ]

    def fake_run(**_kwargs):
        return ProjectionReport(
            toolkit_version="test",
            targets_requested=["dbt"],
            domains={"party": {"status": "ok"}},
            projections=[
                {
                    "target": "dbt",
                    "domain": "party",
                    "status": "error",
                    "error": "blocked",
                    "diagnostics": diagnostics,
                }
            ],
        )

    monkeypatch.setattr("kairos_ontology.core.projector.run_projections", fake_run)
    common = {
        "ontologies_path": tmp_path,
        "catalog_path": None,
        "output_path": tmp_path / "output",
        "target": "dbt",
        "namespace": None,
        "platform": "fabric",
        "emit_aspirational_stubs": False,
        "degraded": False,
        "ref_models_dir": None,
        "accelerator": None,
    }

    complete = check_projection(**common)
    source = check_projection(**common, scope="source")

    assert [item["id"] for item in complete.diagnostics] == [
        "shared-prep",
        "shared-runtime",
    ]
    assert [item["id"] for item in source.diagnostics] == ["shared-prep"]
    assert source.owner_skill == "kairos-design-source"
    assert source.prerequisites == ()


def test_phase_scope_suppresses_out_of_scope_blocker(tmp_path, monkeypatch):
    def fake_run(**_kwargs):
        return ProjectionReport(
            toolkit_version="test",
            targets_requested=["dbt"],
            domains={"party": {"status": "ok"}},
            projections=[
                {
                    "target": "dbt",
                    "domain": "party",
                    "status": "error",
                    "error": "runtime only",
                    "diagnostics": [
                        {
                            "id": "runtime-only",
                            "code": "incremental.ordering-missing",
                            "stage": "runtime",
                            "blocking": True,
                            "message": "runtime only",
                        }
                    ],
                }
            ],
        )

    monkeypatch.setattr("kairos_ontology.core.projector.run_projections", fake_run)
    report = check_projection(
        ontologies_path=tmp_path,
        catalog_path=None,
        output_path=tmp_path / "output",
        target="dbt",
        namespace=None,
        platform="fabric",
        emit_aspirational_stubs=False,
        degraded=False,
        ref_models_dir=None,
        accelerator=None,
        scope="source",
    )

    assert report.ready
    assert report.diagnostics == ()


def test_four_independent_roots_are_stable_and_cascades_are_not_tasks():
    diagnostics = [
        {
            "id": "fk-cascade",
            "code": "foreign_keys.not-evaluated",
            "stage": "temporal_fk",
            "owner_skill": "kairos-design-silver",
            "resource_uri": "",
            "predicate_uri": "",
            "message": "FK checks require identity",
            "blocking": False,
            "depends_on": ["runtime-root"],
            "remediation": "",
        },
        {
            "id": "runtime-root",
            "code": "incremental.ordering-missing",
            "stage": "runtime",
            "owner_skill": "kairos-design-silver",
            "resource_uri": "urn:runtime",
            "predicate_uri": "",
            "message": "runtime root",
            "blocking": True,
            "depends_on": [],
            "remediation": "Complete incremental policy.",
        },
        {
            "id": "mapping-root",
            "code": "mapping.unknown-source-column",
            "stage": "mapping",
            "owner_skill": "kairos-design-mapping",
            "resource_uri": "urn:mapping",
            "predicate_uri": "",
            "message": "mapping root",
            "blocking": True,
            "depends_on": [],
            "remediation": "Correct the mapping.",
        },
        {
            "id": "prep-root",
            "code": "prep.missing-policy",
            "stage": "preparation",
            "owner_skill": "kairos-design-source",
            "resource_uri": "urn:source",
            "predicate_uri": "",
            "message": "prep root",
            "blocking": True,
            "depends_on": [],
            "remediation": "Author preparation policy.",
        },
        {
            "id": "fk-root",
            "code": "temporal-fk.policy-missing",
            "stage": "temporal_fk",
            "owner_skill": "kairos-design-silver",
            "resource_uri": "urn:fk",
            "predicate_uri": "",
            "message": "FK root",
            "blocking": True,
            "depends_on": [],
            "remediation": "Author temporal FK policy.",
        },
    ]

    ordered = _ordered_diagnostics(diagnostics)
    assert [item["id"] for item in ordered] == [
        "prep-root",
        "mapping-root",
        "runtime-root",
        "fk-cascade",
        "fk-root",
    ]
    plan = _remediation_plan(ordered)
    assert [item.diagnostic_ids for item in plan] == [
        ("prep-root",),
        ("mapping-root",),
        ("runtime-root",),
        ("fk-root",),
    ]


def test_missing_target_semantic_key_is_one_task_for_all_impacted_fks():
    diagnostics = tuple(
        {
            "id": f"fk-{index}",
            "code": "temporal-fk.target-semantic-key-missing",
            "stage": "temporal_fk",
            "owner_skill": "kairos-design-silver",
            "resource_uri": resource,
            "message": "Target semantic key is missing",
            "blocking": True,
            "depends_on": [],
            "remediation": "Define the target semantic key.",
        }
        for index, resource in enumerate(("urn:fk:customer", "urn:fk:supplier"))
    )

    plan = _remediation_plan(diagnostics)

    assert len(plan) == 1
    assert plan[0].diagnostic_ids == ("fk-0", "fk-1")
    assert plan[0].impacted_resources == ("urn:fk:customer", "urn:fk:supplier")
