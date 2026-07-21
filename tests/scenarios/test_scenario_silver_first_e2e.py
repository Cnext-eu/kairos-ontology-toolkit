# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Authoritative Silver-first lifecycle scenario (DD-090/094/095/096/101/102)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

from kairos_ontology.cli.main import cli
from kairos_ontology.core.claim_projection_sync import evaluate_projection_sync
from kairos_ontology.core.claim_registry import (
    ClaimRegistry,
    load_registry,
    validate_registry,
    validation_errors,
    write_registry,
)
from kairos_ontology.core.conformance_artifact import read_artifact, validate_artifact
from kairos_ontology.core.dbt_validation import validate_dbt_project
from kairos_ontology.core.derive_claims import class_claim_id, run_derive_claims
from kairos_ontology.core.lifecycle_gate import evaluate_lifecycle_gate
from kairos_ontology.core.projections.shared import KAIROS_EXT
from kairos_ontology.core.projector import ProjectionRunError, run_projections
from kairos_ontology.core.status import scan_hub_status
from kairos_ontology.core.validator import run_validation

from .conftest import HUB_ROOT

FIXTURES = Path(__file__).parent / "fixtures" / "silver-first"
FIXED_GENERATED_AT = "2026-07-21T20:00:00Z"
CLIENT_URI = "https://acme.example/ontology/client#Client"
TRADE_PARTY_URI = "https://refmodel.example/ontology/party#TradeParty"
TRADE_PARTY_IMPORT = "https://refmodel.example/ontology/party"
OUTCOME_CODES = [
    "conforms",
    "conforms-with-rename",
    "partial",
    "deviates",
    "not-applicable",
]


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _project(hub: Path, *, strict: bool = False) -> None:
    run_projections(
        ontologies_path=hub / "model" / "ontologies" / "client.ttl",
        catalog_path=hub / "catalog-v001.xml",
        output_path=hub / "output",
        target="dbt",
        emit_aspirational_stubs=True,
        strict=strict,
    )


def _lifecycle_gate(hub: Path):
    return evaluate_lifecycle_gate(
        hub_root=hub,
        claims_dir=hub / "model" / "claims",
        analysis_dir=hub / "integration" / "sources" / "_analysis",
        sources_dir=hub / "integration" / "sources",
        mappings_dir=hub / "model" / "mappings",
        ontologies_dir=hub / "model" / "ontologies",
        extensions_dir=hub / "model" / "extensions",
        domains_filter=["client"],
        check_mdm_anchor=False,
        check_ownership=False,
        no_source_coverage=True,
    )


def _validate_hub(hub: Path) -> None:
    run_validation(
        ontologies_path=hub / "model" / "ontologies",
        shapes_path=hub / "model" / "shapes",
        catalog_path=hub / "catalog-v001.xml",
        do_syntax=True,
        do_shacl=False,
        do_consistency=False,
        report_path=hub / "output" / "validation-report.json",
    )


def _check_release(hub: Path):
    return CliRunner().invoke(
        cli,
        [
            "check-release",
            "--claims-dir",
            str(hub / "model" / "claims"),
            "--analysis-dir",
            str(hub / "integration" / "sources" / "_analysis"),
            "--sources",
            str(hub / "integration" / "sources"),
            "--mappings",
            str(hub / "model" / "mappings"),
            "--domains",
            "client",
            "--no-source-coverage",
            "--no-mdm-anchor",
            "--no-ownership",
        ],
    )


def _validate_with_real_dbt(project: Path):
    executable = shutil.which("dbt")
    if executable is None:
        pytest.fail("dbt is required for the Silver-first scenario")

    calls: list[str] = []

    def recording_runner(args, **kwargs):
        calls.append(args[1])
        return subprocess.run(args, **kwargs)

    result = validate_dbt_project(
        project,
        "fabric",
        executable=executable,
        runner=recording_runner,
    )
    assert calls == ["deps", "parse", "compile"]
    assert result.compile_status in {"passed", "environment_blocked"}
    return result


@pytest.mark.slow
def test_authoritative_silver_first_lifecycle(tmp_path, monkeypatch):
    """Conformance proposals become governed stubs, bindings, then releasable dbt."""
    committed_authorities = {
        "model": _snapshot(HUB_ROOT / "model"),
        "discovery": _snapshot(HUB_ROOT / "integration" / "discovery"),
    }
    monkeypatch.setenv("KAIROS_GENERATED_AT", FIXED_GENERATED_AT)

    hub = tmp_path / "acme-hub"
    shutil.copytree(HUB_ROOT, hub)
    monkeypatch.chdir(hub)
    shutil.copy2(
        FIXTURES / "core-concepts-conformance.yaml",
        hub / "integration" / "discovery" / "core-concepts-conformance.yaml",
    )
    shutil.copy2(FIXTURES / "catalog-v001.xml", hub / "catalog-v001.xml")
    analysis_dir = hub / "integration" / "sources" / "_analysis"
    analysis_dir.mkdir()

    mappings_dir = hub / "model" / "mappings"
    staged_mappings = hub / ".scenario-staging" / "mappings"
    staged_mappings.mkdir(parents=True)
    for mapping in mappings_dir.glob("*.ttl"):
        shutil.move(mapping, staged_mappings / mapping.name)
    assert not list(mappings_dir.glob("*.ttl"))

    # 1-2. Validated discovery deterministically creates proposals only.
    conformance_path = (
        hub / "integration" / "discovery" / "core-concepts-conformance.yaml"
    )
    conformance = read_artifact(conformance_path)
    assert validate_artifact(conformance, OUTCOME_CODES) == []
    assert conformance["scorecard"]["total"] == len(conformance["core_concepts"]) == 8

    claims_path = hub / "model" / "claims" / "client-claims.yaml"
    write_registry(ClaimRegistry(domain="client"), claims_path)
    derive = run_derive_claims(
        claims_path.parent,
        conformance_path=conformance_path,
        max_workers=1,
    )
    assert derive.total_conformance_proposals == 7
    proposed_bytes = claims_path.read_bytes()
    proposed = load_registry(claims_path)
    assert all(claim.status == "proposed" for claim in proposed.claims)
    proposed_by_id = {claim.id: claim for claim in proposed.claims}
    assert proposed_by_id["client-customer"].disposition == "claim"
    assert '"rename_to":"Client"' in (
        proposed_by_id["client-customer"].evidence_sources[0].note or ""
    )
    assert proposed_by_id["client-tradeparty"].disposition == "claim"
    assert '"tier":"recommended"' in (
        proposed_by_id["client-tradeparty"].evidence_sources[0].note or ""
    )
    assert class_claim_id("client", "CashDrawer") not in {
        claim.id for claim in proposed.claims
    }

    rerun = run_derive_claims(
        claims_path.parent,
        conformance_path=conformance_path,
        max_workers=1,
    )
    assert rerun.written == []
    assert claims_path.read_bytes() == proposed_bytes

    # A proposal has no materialization authority, even with stub emission enabled.
    _project(hub)
    preapproval_silver = (
        hub / "output" / "medallion" / "dbt" / "models" / "silver" / "client"
    )
    assert not list(preapproval_silver.glob("*.sql"))
    shutil.rmtree(hub / "output")

    # 3. This copied fixture is the explicit human-governance boundary. Production
    # derive-claims never performs this proposed -> approved transition.
    approved_fixture = FIXTURES / "client-claims-approved.yaml"
    approved = load_registry(approved_fixture)
    assert not validation_errors(validate_registry(approved))
    assert {claim.id for claim in approved.claims} == {
        claim.id for claim in proposed.claims
    }
    approved_by_id = {claim.id: claim for claim in approved.claims}
    assert {
        claim.id for claim in approved.claims if claim.status == "approved"
    } == {"client-customer", "client-tradeparty"}
    assert approved_by_id["client-customer"].class_uri == CLIENT_URI
    assert approved_by_id["client-customer"].origin == "authored"
    assert approved_by_id["client-tradeparty"].class_uri == TRADE_PARTY_URI
    assert all(
        approved_by_id[claim.id].evidence_sources == claim.evidence_sources
        for claim in proposed.claims
    )

    shutil.copy2(approved_fixture, claims_path)
    approved_bytes = claims_path.read_bytes()
    run_derive_claims(
        claims_path.parent,
        conformance_path=conformance_path,
        max_workers=1,
        force=True,
    )
    assert claims_path.read_bytes() == approved_bytes

    # 4. Managed synchronization adds only the approved imported concept.
    sync_before = evaluate_projection_sync(
        claims_dir=claims_path.parent,
        ontologies_dir=hub / "model" / "ontologies",
        extensions_dir=hub / "model" / "extensions",
        domains_filter=["client"],
    )
    assert sync_before.domains[0].missing_imports == [TRADE_PARTY_IMPORT]
    assert sync_before.domains[0].missing_includes == [TRADE_PARTY_URI]

    sync_result = CliRunner().invoke(
        cli,
        [
            "claims-to-silver-ext",
            "--claims-dir",
            str(claims_path.parent),
            "--ontologies",
            str(hub / "model" / "ontologies"),
            "--extensions",
            str(hub / "model" / "extensions"),
            "--domains",
            "client",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert sync_result.exit_code == 0, sync_result.output

    ontology_path = hub / "model" / "ontologies" / "client.ttl"
    extension_path = hub / "model" / "extensions" / "client-silver-ext.ttl"
    ontology_graph = Graph().parse(ontology_path, format="turtle")
    extension_graph = Graph().parse(extension_path, format="turtle")
    ontology_subject = next(ontology_graph.subjects(RDF.type, OWL.Ontology))
    assert URIRef(TRADE_PARTY_IMPORT) in set(
        ontology_graph.objects(ontology_subject, OWL.imports)
    )
    assert extension_graph.value(
        URIRef(TRADE_PARTY_URI), KAIROS_EXT.silverInclude
    )
    assert str(
        extension_graph.value(
            URIRef("https://acme.example/ontology/client#CorporateClient"),
            KAIROS_EXT.silverTableName,
        )
    ) == "corporate_client"

    ontology_text = ontology_path.read_text(encoding="utf-8")
    extension_text = extension_path.read_text(encoding="utf-8")
    assert ontology_text.count("# >>> kairos-managed") == 1
    assert extension_text.count("# >>> kairos-managed") == 1
    assert "PaymentToken" not in ontology_text + extension_text
    sync_after = evaluate_projection_sync(
        claims_dir=claims_path.parent,
        ontologies_dir=hub / "model" / "ontologies",
        extensions_dir=hub / "model" / "extensions",
        domains_filter=["client"],
    )
    assert not sync_after.is_blocking

    sync_again = CliRunner().invoke(
        cli,
        [
            "claims-to-silver-ext",
            "--claims-dir",
            str(claims_path.parent),
            "--ontologies",
            str(hub / "model" / "ontologies"),
            "--extensions",
            str(hub / "model" / "extensions"),
            "--domains",
            "client",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert sync_again.exit_code == 0, sync_again.output
    assert ontology_path.read_text(encoding="utf-8") == ontology_text
    assert extension_path.read_text(encoding="utf-8") == extension_text

    # 5-6. No mappings: both approved outcomes are typed zero-row stubs. dbt can
    # parse them, but objective status and both release gates remain negative.
    _project(hub)
    dbt_root = hub / "output" / "medallion" / "dbt"
    silver_dir = dbt_root / "models" / "silver" / "client"
    stub_paths = {
        "Client": silver_dir / "client.sql",
        "TradeParty": silver_dir / "trade_party.sql",
    }
    stub_bytes = {name: path.read_bytes() for name, path in stub_paths.items()}
    for path in stub_paths.values():
        sql = path.read_text(encoding="utf-8")
        assert "kairos_aspirational_stub" in sql
        assert "cast(null as" in sql
        assert "where 1 = 0" in sql

    schema = yaml.safe_load(
        (silver_dir / "_client__models.yml").read_text(encoding="utf-8")
    )
    schema_models = {model["name"]: model for model in schema["models"]}
    assert set(schema_models) == {"client", "trade_party"}
    assert all(
        str(schema_models[name]["meta"]["is_aspirational"]).lower() == "true"
        for name in schema_models
    )
    assert schema_models["client"]["columns"]
    assert any(column.get("tests") for column in schema_models["client"]["columns"])

    status = scan_hub_status(hub)
    silver_status = next(
        item for item in status.phase("silver").instances if item.name == "client"
    )
    assert silver_status.facts == {
        "bound_classes": [],
        "aspirational_classes": ["Client", "TradeParty"],
        "release_eligible": False,
    }
    validation_instances = status.phase("validate").instances
    data_valid = (
        validation_instances[0].facts.get("data_valid")
        if validation_instances
        else None
    )
    assert data_valid is not True

    blocked_gate = _lifecycle_gate(hub)
    assert blocked_gate.validation.passed is None
    assert blocked_gate.release_blocking_domains == ("client",)
    assert blocked_gate.release[0].aspirational_classes == (
        "Client",
        "TradeParty",
    )
    assert blocked_gate.is_blocking

    blocked_release = _check_release(hub)
    assert blocked_release.exit_code == 1
    assert "NOT release-eligible" in blocked_release.output
    assert "Client, TradeParty" in blocked_release.output

    with pytest.raises(ProjectionRunError, match="Client, TradeParty"):
        _project(hub, strict=True)

    # 7-9. The selected mapping fixture is the only authority change. Re-projection
    # replaces the same paths with bound models and both strict gates become clear.
    selection = yaml.safe_load(
        (FIXTURES / "bound-mapping-selection.yaml").read_text(encoding="utf-8")
    )
    assert selection == {
        "schema_version": 1,
        "mapping_files": ["selected-bindings.ttl"],
    }
    for name in selection["mapping_files"]:
        destination = mappings_dir / name
        shutil.copy2(FIXTURES / name, destination)
        Graph().parse(destination, format="turtle")
    assert [path.name for path in mappings_dir.glob("*.ttl")] == [
        "selected-bindings.ttl"
    ]

    _project(hub, strict=True)
    for name, path in stub_paths.items():
        sql = path.read_text(encoding="utf-8")
        assert path.read_bytes() != stub_bytes[name]
        assert "kairos_aspirational_stub" not in sql
        assert "where 1 = 0" not in sql
        assert "source(" in sql

    assert {path.name for path in silver_dir.glob("*.sql")} == {
        "client.sql",
        "trade_party.sql",
    }
    forbidden_proposals = {
        "direct_debit_mandate.sql",
        "invoice.sql",
        "invoice_line.sql",
        "party.sql",
        "payment_token.sql",
    }
    assert not forbidden_proposals.intersection(
        path.name for path in dbt_root.rglob("*.sql")
    )

    manifest = json.loads(
        (dbt_root / ".kairos-projection-manifest.json").read_text(encoding="utf-8")
    )
    assert {
        "models/silver/client/client.sql",
        "models/silver/client/trade_party.sql",
    } <= set(manifest["files"])

    _validate_hub(hub)
    final_status = scan_hub_status(hub)
    final_silver = next(
        item
        for item in final_status.phase("silver").instances
        if item.name == "client"
    )
    assert final_silver.facts["aspirational_classes"] == []
    assert final_silver.facts["bound_classes"] == ["Client", "TradeParty"]
    assert final_silver.facts["release_eligible"] is True
    assert (
        final_status.phase("validate").instances[0].facts["data_valid"]
        is True
    )

    final_gate = _lifecycle_gate(hub)
    assert final_gate.release_blocking_domains == ()
    assert final_gate.release[0].release_eligible
    assert final_gate.validation.passed is True
    assert not final_gate.is_blocking
    final_release = _check_release(hub)
    assert final_release.exit_code == 0, final_release.output
    assert "every composed gate is clear" in final_release.output

    # 10. Fixed provenance makes same-path re-projection byte-identical. Deleting
    # output and reproducing it proves no hand-edited generated file is required.
    first_snapshot = _snapshot(hub / "output")
    _project(hub, strict=True)
    assert _snapshot(hub / "output") == first_snapshot
    shutil.rmtree(hub / "output")
    _project(hub, strict=True)
    _validate_hub(hub)
    assert _snapshot(hub / "output") == first_snapshot

    projection_report = json.loads(
        (hub / "output" / "projection-report.json").read_text(encoding="utf-8")
    )
    assert projection_report["generated_at"] == FIXED_GENERATED_AT
    client_sql = stub_paths["Client"].read_text(encoding="utf-8")
    assert f"Generated at: {FIXED_GENERATED_AT}" in client_sql
    assert "Ontology: https://acme.example/ontology/client" in client_sql
    assert "Ontology version: 1.0.0" in client_sql
    schema_text = (silver_dir / "_client__models.yml").read_text(encoding="utf-8")
    assert "https://acme.example/bronze/adminpulse#tblRelation_ClientID" in schema_text
    assert (
        "https://acme.example/bronze/logisticspro#tblShipmentParty_PartyCode"
        in schema_text
    )
    assert "https://refmodel.example/ontology/party#partyCode" in schema_text

    bound_dbt = _validate_with_real_dbt(dbt_root)
    assert bound_dbt.manifest_path.name == "manifest.json"
    assert not (dbt_root / "target").exists()
    assert not (dbt_root / "dbt_packages").exists()

    assert _snapshot(HUB_ROOT / "model") == committed_authorities["model"]
    assert (
        _snapshot(HUB_ROOT / "integration" / "discovery")
        == committed_authorities["discovery"]
    )
