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


class _ReadyDecision:
    id = "canonical-grain"
    status = "developer_approved"
    evidence = ("reviewed-evidence",)
    verified_by = ("unit_test_canonical_grain",)


class _Replacement:
    def __init__(self, table_iri: str) -> None:
        self.table_iri = table_iri


class _ReadyContract:
    def __init__(
        self,
        *,
        virtual_source_iri: str = "https://example.test/virtual#orders",
        replaces_sources: tuple[_Replacement, ...] = (),
    ) -> None:
        self.virtual_source_iri = virtual_source_iri
        self.replaces_sources = replaces_sources
        self.decisions = (_ReadyDecision(),)
        self.identity_verified = True


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
        decisions = (
            type(
                "_Decision",
                (),
                {
                    "id": "canonical-grain",
                    "status": "developer_approved",
                    "evidence": ("reviewed-evidence",),
                    "verified_by": ("unit_test_canonical_grain",),
                },
            )(),
        )

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


@pytest.mark.parametrize("inventory_exists", [False, True])
def test_scoped_readiness_surfaces_unrelated_contract_as_nonblocking_diagnostic(
    tmp_path,
    monkeypatch,
    inventory_exists,
):
    """A contract outside the requested ``--table`` scope stays visible for awareness
    (no dependency closure is added — direct table/virtual-source overlap remains the
    sole scope authority) but never blocks this scoped gate.
    """
    hub = _hub(tmp_path)
    if inventory_exists:
        write_candidate_inventory(hub, CandidateInventory())
    contract = _ReadyContract(
        replaces_sources=(_Replacement("https://example.test/bronze#orders"),),
    )
    # A genuine authored/policy error (no decision evidence at all), unrelated to
    # contract-output identity, so scope inclusion/exclusion stays the only variable.
    contract.decisions = ()
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates._implemented_models",
        lambda _hub: ({"int_orders": contract}, None),
    )
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates.sync_dbt_contracts",
        lambda _hub, check: type("_SyncReport", (), {"has_drift": False})(),
    )

    unrelated = evaluate_transformation_readiness(
        hub,
        stage="mapping",
        table_scope=("https://example.test/bronze#customers",),
    )
    replacement = evaluate_transformation_readiness(
        hub,
        stage="mapping",
        table_scope=("https://example.test/bronze#orders",),
    )
    virtual = evaluate_transformation_readiness(
        hub,
        stage="mapping",
        table_scope=("https://example.test/virtual#orders",),
    )

    assert [item.id for item in unrelated.candidates] == ["contract:int_orders"]
    assert unrelated.candidates[0].is_blocking is False
    assert unrelated.candidates[0].reasons  # still visible for review, not suppressed
    assert unrelated.is_blocking is False
    assert [item.id for item in replacement.candidates] == ["contract:int_orders"]
    assert replacement.is_blocking is True
    assert [item.id for item in virtual.candidates] == ["contract:int_orders"]
    assert virtual.is_blocking is True


@pytest.mark.parametrize(
    ("stage", "expected_blocking"),
    [("mapping", False), ("release", True)],
)
def test_in_scope_unverified_contract_identity_is_release_only(
    tmp_path,
    monkeypatch,
    stage,
    expected_blocking,
):
    """DD-119: an in-scope contract whose only issue is unverified identity must not
    pass mapping readiness merely because table scoping excluded it — it is genuinely
    in scope here and is evaluated, but the finding only blocks ``release``.
    """
    hub = _hub(tmp_path)
    # No replaces_sources: keeps the scope check isolated to the virtual-source IRI and
    # avoids the unrelated replacement-completion check that silver/release also run.
    contract = _ReadyContract()
    contract.identity_verified = False
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates._implemented_models",
        lambda _hub: ({"int_orders": contract}, None),
    )
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates.sync_dbt_contracts",
        lambda _hub, check: type("_SyncReport", (), {"has_drift": False})(),
    )

    report = evaluate_transformation_readiness(
        hub,
        stage=stage,
        table_scope=("https://example.test/virtual#orders",),
    )

    assert [item.id for item in report.candidates] == ["contract:int_orders"]
    assert "identity.contract-unverified" in report.candidates[0].reasons[0]
    assert report.is_blocking is expected_blocking
    assert report.candidates[0].is_blocking is expected_blocking


@pytest.mark.parametrize("contract_is_inventoried", [False, True])
@pytest.mark.parametrize(
    ("stage", "expected_blocking"),
    [("mapping", False), ("silver", True), ("release", True)],
)
def test_noninventoried_replacement_completion_uses_stage_semantics(
    tmp_path,
    monkeypatch,
    contract_is_inventoried,
    stage,
    expected_blocking,
):
    hub = _hub(tmp_path)
    contract = _ReadyContract(
        replaces_sources=(_Replacement("https://example.test/bronze#orders"),),
    )
    expected_id = "contract:int_orders"
    if contract_is_inventoried:
        models = hub / "evidence"
        models.mkdir()
        (models / "orders.sql").write_text("select 1", encoding="utf-8")
        inventory = inventory_transformation_candidates(hub, [models])
        candidate = inventory.candidates[0]
        assessment = CandidateAssessment(
            status="implemented",
            semantic_target="https://example.test/ontology#Order",
            authority_classification="operational-source",
            replacement_scope=("https://example.test/bronze#orders",),
            rationale="Implemented as a governed replacement.",
            confidence="high",
            evidence=("Reviewed contract and source grain.",),
            approval=AssessmentApproval("reviewer", "2026-07-22T20:00:00Z"),
            assessed_sha256=candidate.facts.sha256,
            implemented_model_name="int_orders",
        )
        write_candidate_inventory(
            hub,
            CandidateInventory(
                roots=inventory.roots,
                candidates=(
                    TransformationCandidate(candidate.id, candidate.facts, assessment),
                ),
            ),
        )
        expected_id = candidate.id
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates._implemented_models",
        lambda _hub: ({"int_orders": contract}, None),
    )
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates.sync_dbt_contracts",
        lambda _hub, check: type("_SyncReport", (), {"has_drift": False})(),
    )
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates._replacement_scope_completion_reasons",
        lambda _hub, _scope: ("replacement incomplete",),
    )

    report = evaluate_transformation_readiness(
        hub,
        stage=stage,
        table_scope=("https://example.test/bronze#orders",),
    )

    assert report.is_blocking is expected_blocking
    assert report.candidates[0].id == expected_id
    assert report.candidates[0].reasons == (
        ("replacement incomplete",) if expected_blocking else ()
    )


@pytest.mark.parametrize("inventory_exists", [False, True])
def test_unscoped_readiness_checks_existing_contract_without_candidate(
    tmp_path,
    monkeypatch,
    inventory_exists,
):
    hub = _hub(tmp_path)
    if inventory_exists:
        write_candidate_inventory(hub, CandidateInventory())
    contract = _ReadyContract()
    contract.identity_verified = False
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates._implemented_models",
        lambda _hub: ({"int_orders": contract}, None),
    )
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates.sync_dbt_contracts",
        lambda _hub, check: type("_SyncReport", (), {"has_drift": False})(),
    )

    report = evaluate_transformation_readiness(hub, stage="mapping")

    # DD-119: unverified contract-output identity alone is release-only evidence and
    # never blocks mapping readiness, but the contract must still be checked and the
    # finding must still be visible for review.
    assert report.is_blocking is False
    assert report.candidates[0].id == "contract:int_orders"
    assert report.candidates[0].is_blocking is False
    assert "identity.contract-unverified" in report.candidates[0].reasons[0]


@pytest.mark.parametrize(
    ("stage", "invoices_blocking", "overall_blocking"),
    [("mapping", False, False), ("release", True, True)],
)
def test_two_domain_scope_isolates_blocked_domain_from_ready_domain(
    tmp_path,
    monkeypatch,
    stage,
    invoices_blocking,
    overall_blocking,
):
    """Generic two-domain regression (mapping-scope).

    ``clients`` has a blocked contract (missing decision evidence) while ``invoices``
    is a direct, contract-clean source-table scope whose only finding is unverified
    contract-output identity. Restricting ``--table`` to the ``invoices`` scope must
    keep the mapping-ready domain ungated: the unrelated ``clients`` blocker stays
    visible only as a non-blocking diagnostic (no dependency closure — direct
    table/virtual-source overlap remains the sole scope authority), and the in-scope
    unverified identity finding follows the DD-119 release-only semantics already
    implemented, verified here in a multi-domain context.
    """
    hub = _hub(tmp_path)
    clients_contract = _ReadyContract(
        virtual_source_iri="https://example.test/virtual#clients",
        replaces_sources=(_Replacement("https://example.test/bronze#clients_raw"),),
    )
    clients_contract.decisions = ()  # blocked: no approved decision evidence at all
    invoices_contract = _ReadyContract(
        virtual_source_iri="https://example.test/virtual#invoices",
        replaces_sources=(_Replacement("https://example.test/bronze#invoices_raw"),),
    )
    invoices_contract.identity_verified = False  # only finding: unverified identity

    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates._implemented_models",
        lambda _hub: (
            {"int_clients": clients_contract, "int_invoices": invoices_contract},
            None,
        ),
    )
    monkeypatch.setattr(
        "kairos_ontology.core.transformation_candidates.sync_dbt_contracts",
        lambda _hub, check: type("_SyncReport", (), {"has_drift": False})(),
    )

    report = evaluate_transformation_readiness(
        hub,
        stage=stage,
        table_scope=("https://example.test/bronze#invoices_raw",),
    )

    by_id = {item.id: item for item in report.candidates}
    assert set(by_id) == {"contract:int_clients", "contract:int_invoices"}

    # Unrelated blocked domain: visible for review, never blocks this scoped gate.
    clients_result = by_id["contract:int_clients"]
    assert clients_result.is_blocking is False
    assert any(
        "transformation.evidence-missing" in reason for reason in clients_result.reasons
    )

    # In-scope domain: unverified identity alone follows release-only semantics.
    invoices_result = by_id["contract:int_invoices"]
    assert any(
        "identity.contract-unverified" in reason for reason in invoices_result.reasons
    )
    assert invoices_result.is_blocking is invoices_blocking

    assert report.is_blocking is overall_blocking


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
    before_files = {
        item.relative_to(hub).as_posix(): item.read_bytes()
        for item in hub.rglob("*")
        if item.is_file()
    }

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
    payload = json.loads(result.output)
    assert payload["is_blocking"] is True
    assert payload["owner_skill"] == "kairos-develop-dbt-transformation"
    assert payload["prerequisites"] == ["source", "mapping"]
    assert payload["shared_readiness"]["scope"] == "transformation"
    assert payload["shared_readiness"]["phase_details"]["transformation_readiness"][
        "candidates"
    ] == payload["candidates"]
    assert path.read_bytes() == before
    assert {
        item.relative_to(hub).as_posix(): item.read_bytes()
        for item in hub.rglob("*")
        if item.is_file()
    } == before_files
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
