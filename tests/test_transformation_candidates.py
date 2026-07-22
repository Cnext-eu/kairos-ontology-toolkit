# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for transformation-candidate inventory and readiness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.status import PHASE_ORDER, scan_hub_status
from kairos_ontology.core.transformation_candidates import (
    AssessmentApproval,
    CandidateAssessment,
    CandidateInventory,
    TransformationCandidate,
    TransformationCandidateError,
    evaluate_transformation_readiness,
    inventory_transformation_candidates,
    load_candidate_inventory,
    write_candidate_inventory,
)


def _hub(root: Path) -> Path:
    hub = root / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "integration").mkdir()
    (hub / "output").mkdir()
    return hub


def test_inventory_scans_only_explicit_model_roots_and_objective_signals(tmp_path):
    hub = _hub(tmp_path)
    project = tmp_path / "evidence"
    (project / "models").mkdir(parents=True)
    (project / "macros").mkdir()
    (project / "tests").mkdir()
    (project / "dbt_project.yml").write_text("name: evidence\n", encoding="utf-8")
    model = project / "models" / "customer_rollup.sql"
    model.write_text(
        "select customer_id, count(*) as n\n"
        "from {{ source('crm', 'orders') }}\n"
        "group by customer_id\n",
        encoding="utf-8",
    )
    (project / "macros" / "helper.sql").write_text("select 1", encoding="utf-8")
    (project / "tests" / "assertion.sql").write_text("select 1", encoding="utf-8")

    inventory = inventory_transformation_candidates(
        hub,
        [project],
        repository_root=tmp_path,
    )

    assert inventory.projection_authority is False
    assert inventory.roots == ("evidence",)
    assert len(inventory.candidates) == 1
    candidate = inventory.candidates[0]
    assert candidate.id == "evidence/models/customer_rollup.sql"
    assert candidate.facts.artifact_path == candidate.id
    assert candidate.facts.detected_operations == ("aggregate",)
    assert {item.name for item in candidate.facts.resource_references} >= {
        "crm.orders",
    }


def test_inventory_rejects_outside_roots_and_overlapping_identities(tmp_path):
    hub = _hub(tmp_path)
    models = tmp_path / "models"
    models.mkdir()
    (models / "one.sql").write_text("select 1", encoding="utf-8")

    with pytest.raises(TransformationCandidateError, match="inside repository"):
        inventory_transformation_candidates(
            hub,
            [tmp_path.parent],
            repository_root=tmp_path,
        )
    with pytest.raises(TransformationCandidateError, match="duplicate candidate identity"):
        inventory_transformation_candidates(
            hub,
            [models, models / "one.sql"],
            repository_root=tmp_path,
        )


def test_inventory_rejects_dbt_model_path_outside_explicit_root(tmp_path):
    hub = _hub(tmp_path)
    project = tmp_path / "evidence"
    project.mkdir()
    outside = tmp_path / "unselected-models"
    outside.mkdir()
    (outside / "orders.sql").write_text("select 1", encoding="utf-8")
    (project / "dbt_project.yml").write_text(
        "name: evidence\nmodel-paths:\n  - ../unselected-models\n",
        encoding="utf-8",
    )

    with pytest.raises(TransformationCandidateError, match="escapes the explicit"):
        inventory_transformation_candidates(hub, [project], repository_root=tmp_path)


def test_inventory_rejects_non_utf8_sql_with_controlled_error(tmp_path):
    hub = _hub(tmp_path)
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_bytes(b"select '\xff'")

    with pytest.raises(TransformationCandidateError, match="SQL must be UTF-8"):
        inventory_transformation_candidates(hub, [models], repository_root=tmp_path)


def test_rescan_preserves_assessment_but_checksum_requires_reassessment(tmp_path):
    hub = _hub(tmp_path)
    models = tmp_path / "models"
    models.mkdir()
    artifact = models / "orders.sql"
    artifact.write_text("select * from raw.orders", encoding="utf-8")
    first = inventory_transformation_candidates(hub, [models], repository_root=tmp_path)
    facts = first.candidates[0].facts
    assessed = CandidateAssessment(
        status="deferred",
        replacement_scope=("https://example.test/bronze#orders",),
        rationale="The direct slice remains authoritative.",
        confidence="high",
        assessed_sha256=facts.sha256,
        distinct_grain_statement="Candidate is monthly; direct slice is order grain.",
    )
    write_candidate_inventory(
        hub,
        CandidateInventory(
            roots=first.roots,
            candidates=(TransformationCandidate(first.candidates[0].id, facts, assessed),),
        ),
    )
    artifact.write_text("select * from raw.orders where active = 1", encoding="utf-8")

    rescanned = inventory_transformation_candidates(hub, [models], repository_root=tmp_path)
    write_candidate_inventory(hub, rescanned)
    candidate = rescanned.candidates[0]
    assert candidate.assessment == assessed
    assert candidate.facts.sha256 != assessed.assessed_sha256
    report = evaluate_transformation_readiness(hub, stage="mapping")
    assert report.assessment_required
    assert report.is_blocking
    assert "checksum changed" in report.candidates[0].reasons[0]


def test_rename_yields_orphan_and_new_candidate(tmp_path):
    hub = _hub(tmp_path)
    models = tmp_path / "models"
    models.mkdir()
    old = models / "old.sql"
    old.write_text("select 1", encoding="utf-8")
    write_candidate_inventory(
        hub,
        inventory_transformation_candidates(hub, [models], repository_root=tmp_path),
    )
    old.rename(models / "new.sql")

    rescanned = inventory_transformation_candidates(hub, [models], repository_root=tmp_path)

    assert [candidate.id for candidate in rescanned.candidates] == [
        "models/new.sql",
        "models/old.sql",
    ]
    assert rescanned.candidates[0].facts.present is True
    assert rescanned.candidates[1].facts.present is False


def test_implemented_status_requires_discovered_contract(tmp_path):
    hub = _hub(tmp_path)
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_text("select 1", encoding="utf-8")
    inventory = inventory_transformation_candidates(hub, [models], repository_root=tmp_path)
    facts = inventory.candidates[0].facts
    assessment = CandidateAssessment(
        status="implemented",
        semantic_target="https://example.test/ontology#Order",
        authority_classification="operational-source",
        rationale="Implemented as a governed contract.",
        confidence="high",
        evidence=("Reviewed contract and source grain.",),
        approval=AssessmentApproval("reviewer", "2026-07-22T20:00:00Z"),
        assessed_sha256=facts.sha256,
        implemented_model_name="orders",
    )
    write_candidate_inventory(
        hub,
        CandidateInventory(
            roots=inventory.roots,
            candidates=(
                TransformationCandidate(inventory.candidates[0].id, facts, assessment),
            ),
        ),
    )

    report = evaluate_transformation_readiness(hub, stage="silver")

    assert report.is_blocking
    assert "no discovered dbt contract" in report.candidates[0].reasons[0]


def test_implemented_candidate_can_reference_renamed_contract(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    models = tmp_path / "models"
    models.mkdir()
    (models / "legacy_orders.sql").write_text("select 1", encoding="utf-8")
    inventory = inventory_transformation_candidates(hub, [models], repository_root=tmp_path)
    facts = inventory.candidates[0].facts
    assessment = CandidateAssessment(
        status="implemented",
        semantic_target="https://example.test/ontology#Order",
        authority_classification="operational-source",
        rationale="Implemented with the canonical dbt model name.",
        confidence="high",
        evidence=("Reviewed contract and source grain.",),
        approval=AssessmentApproval("reviewer", "2026-07-22T20:00:00Z"),
        assessed_sha256=facts.sha256,
        implemented_model_name="int_orders_conformed",
    )
    write_candidate_inventory(
        hub,
        CandidateInventory(
            roots=inventory.roots,
            candidates=(
                TransformationCandidate(inventory.candidates[0].id, facts, assessment),
            ),
        ),
    )

    class _Contract:
        replaces_sources = ()

    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates._implemented_models",
        lambda _hub: ({"int_orders_conformed": _Contract()}, None),
    )
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates.sync_dbt_contracts",
        lambda _hub, check: type("_SyncReport", (), {"has_drift": False})(),
    )

    report = evaluate_transformation_readiness(hub, stage="mapping")

    assert report.is_blocking is False


def test_every_assessed_status_requires_checksum(tmp_path):
    hub = _hub(tmp_path)
    path = hub / "model" / "planning" / "dbt-transformations" / "candidates.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "schema_version: 1\n"
        "projection_authority: false\n"
        "roots: []\n"
        "candidates:\n"
        "  - id: evidence/orders.sql\n"
        "    facts:\n"
        "      artifact_path: evidence/orders.sql\n"
        f"      sha256: {'a' * 64}\n"
        "      proposed_model_name: orders\n"
        "    assessment:\n"
        "      status: rejected\n"
        "      rationale: Direct source is authoritative.\n",
        encoding="utf-8",
    )

    with pytest.raises(TransformationCandidateError, match="assessed_sha256 is required"):
        load_candidate_inventory(hub)


def test_status_is_additive_and_does_not_add_lifecycle_phase(tmp_path):
    hub = _hub(tmp_path)
    without_inventory = scan_hub_status(hub).to_dict()
    assert "transformation_candidates" not in without_inventory
    assert [phase["phase"] for phase in without_inventory["phases"]] == list(PHASE_ORDER)

    models = hub / "evidence"
    models.mkdir()
    (models / "candidate.sql").write_text("select 1", encoding="utf-8")
    write_candidate_inventory(hub, inventory_transformation_candidates(hub, [models]))
    with_inventory = scan_hub_status(hub).to_dict()

    assert with_inventory["transformation_candidates"]["projection_authority"] is False
    assert with_inventory["transformation_candidates"]["candidate_count"] == 1
    assert with_inventory["transformation_candidates"]["assessment_status_counts"] == {
        "unassessed": 1
    }
    assert [phase["phase"] for phase in with_inventory["phases"]] == list(PHASE_ORDER)


def test_status_reports_malformed_inventory_without_hiding_lifecycle_state(tmp_path):
    hub = _hub(tmp_path)
    inventory_path = hub / "model" / "planning" / "dbt-transformations" / "candidates.yaml"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text("schema_version: invalid\n", encoding="utf-8")

    status = scan_hub_status(hub).to_dict()

    assert "schema_version must be 1" in status["transformation_candidates"]["error"]
    assert [phase["phase"] for phase in status["phases"]] == list(PHASE_ORDER)


def test_readiness_cli_is_non_writing_and_returns_blocking_exit(tmp_path):
    hub = _hub(tmp_path)
    models = hub / "evidence"
    models.mkdir()
    (models / "joined.sql").write_text(
        "select * from one join two on one.id = two.id",
        encoding="utf-8",
    )
    inventory = inventory_transformation_candidates(hub, [models])
    facts = inventory.candidates[0].facts
    accepted = CandidateAssessment(
        status="accepted",
        semantic_target="https://example.test/ontology#Order",
        authority_classification="operational-source",
        replacement_scope=("https://example.test/bronze#one",),
        rationale="The joined model replaces the source.",
        confidence="high",
        evidence=("Reviewed imported SQL and source grain.",),
        approval=AssessmentApproval("reviewer", "2026-07-22T20:00:00Z"),
        assessed_sha256=facts.sha256,
    )
    path = write_candidate_inventory(
        hub,
        CandidateInventory(
            roots=inventory.roots,
            candidates=(TransformationCandidate(inventory.candidates[0].id, facts, accepted),),
        ),
    )
    before = path.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "check-transformation-readiness",
            "--stage",
            "mapping",
            "--table",
            "https://example.test/bronze#one",
            "--hub",
            str(hub),
            "--format",
            "json",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["is_blocking"] is True
    assert path.read_bytes() == before
    assert load_candidate_inventory(hub) is not None


def test_inventory_cli_uses_approved_command_name(tmp_path):
    hub = _hub(tmp_path)
    evidence = hub / "evidence"
    evidence.mkdir()
    (evidence / "orders.sql").write_text("select 1", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "inventory-dbt-candidates",
            "--from",
            str(evidence),
            "--hub",
            str(hub),
            "--repository-root",
            str(hub),
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    assert load_candidate_inventory(hub) is not None
    assert "inventory-transformation-candidates" not in CliRunner().invoke(
        cli,
        ["--help"],
    ).output
