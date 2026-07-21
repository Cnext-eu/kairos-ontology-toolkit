# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for the Slice 3 ``derive-claims`` evidence-aggregation path.

These tests exercise the deterministic, AI-free ``derive-claims`` backend against
the synthetic **acme-hub** fixture.  ``derive-claims`` enriches an existing Claim
Registry by joining it with already-produced evidence streams (``analyse-sources``
affinity + ``model/mappings/*.ttl`` SKOS links + committed conformance outcomes)
and attaching **multiple** ``evidence_sources`` per claim — every derived/new
claim stays ``proposed``.

The permanent acme-hub deliberately has **no** ``model/claims/`` directory so the
projector's Slice 2 claim-authority gate never fires for the shared scenario
projection tests.  These tests therefore never write a claims file into the shared
hub: the registry + affinity evidence are built in ``tmp_path`` and only the real
``model/mappings/*.ttl`` files are read (read-only — ``derive-claims`` only reads
mappings, so pointing at the real directory is safe).
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    load_registry,
    write_registry,
)
from kairos_ontology.cli.main import cli
from kairos_ontology.core.conformance_artifact import (
    ARTIFACT_RELPATH,
    ConformanceArtifactError,
)
from kairos_ontology.core.derive_claims import (
    CONFORMANCE_EVIDENCE_TYPE,
    class_claim_id,
    load_skos_links,
    property_claim_id,
    run_derive_claims,
)

ACME_HUB = Path(__file__).resolve().parent / "acme-hub"
MAPPINGS_DIR = ACME_HUB / "model" / "mappings"
CONFORMANCE_PATH = ACME_HUB / ARTIFACT_RELPATH


def _seed_client_registry(*, class_status: str = "proposed", class_uri: str | None = None) -> ClaimRegistry:
    """Build a minimal ``client`` registry anchored on AdminPulse ``tblClient``."""
    class_id = class_claim_id("client", "CorporateClient")
    prop_id = property_claim_id("client", "CorporateClient", "clientName")
    return ClaimRegistry(
        domain="client",
        coverage=[
            CoverageSystem(
                system="adminpulse",
                tables=[
                    CoverageTable(
                        table="tblClient",
                        ref_class="CorporateClient",
                        anchor_state="matched",
                    )
                ],
            )
        ],
        claims=[
            Claim(
                id=class_id,
                type="class",
                status=class_status,
                disposition="claim",
                origin="imported",
                class_uri=class_uri,
                evidence_sources=[
                    EvidenceSource(
                        type="source_table", system="adminpulse", table="tblClient"
                    )
                ],
            ),
            Claim(
                id=prop_id,
                type="property",
                status="proposed",
                disposition="claim",
                origin="imported",
                evidence_sources=[
                    EvidenceSource(
                        type="source_column",
                        system="adminpulse",
                        table="tblClient",
                        column="Name",
                    )
                ],
            ),
        ],
    )


def _write_affinity(analysis_dir: Path) -> None:
    """Write a tmp schema_version-2 affinity file for AdminPulse ``tblClient``."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "adminpulse-affinity.yaml").write_text(
        "schema_version: 2\n"
        "system: adminpulse\n"
        "tables:\n"
        "  - table: tblClient\n"
        "    domain: client\n"
        "    likely_entity: Client\n"
        "    confidence: 0.9\n",
        encoding="utf-8",
    )


def test_load_skos_links_from_real_acme_mappings():
    """The real acme-hub SKOS mappings parse and decode into link records."""
    links = load_skos_links(MAPPINGS_DIR)
    assert links, "expected SKOS links from acme-hub mappings"

    # A class-kind link to a client entity from the adminpulse system.
    class_links = [
        link
        for link in links
        if link["kind"] == "class"
        and link["system"] == "adminpulse"
        and link["target"] in {"CorporateClient", "Client"}
        and not link["column"]
    ]
    assert class_links, "expected an adminpulse class-kind link to CorporateClient/Client"

    # A property-kind link to clientName carrying a concrete column.
    name_links = [
        link
        for link in links
        if link["kind"] == "property" and link["target"] == "clientName"
    ]
    assert name_links, "expected a property-kind link to clientName"
    assert all(link["column"] for link in name_links), "property links must carry a column"


def test_derive_enriches_with_multiple_evidence_sources(tmp_path):
    """End-to-end enrich attaches affinity + SKOS evidence; nothing auto-approved."""
    claims_dir = tmp_path / "model" / "claims"
    analysis_dir = tmp_path / "_analysis"
    write_registry(_seed_client_registry(), claims_dir / "client-claims.yaml")
    _write_affinity(analysis_dir)

    report = run_derive_claims(
        claims_dir,
        analysis_dir=analysis_dir,
        mappings_dir=MAPPINGS_DIR,
    )
    assert [s.domain for s in report.domain_stats] == ["client"]

    registry = load_registry(claims_dir / "client-claims.yaml")
    by_id = {c.id: c for c in registry.claims}

    class_claim = by_id[class_claim_id("client", "CorporateClient")]
    class_types = {ev.type for ev in class_claim.evidence_sources}
    assert "affinity" in class_types, "class claim should gain affinity evidence"
    assert "skos_mapping" in class_types, "class claim should gain SKOS evidence"

    prop_claim = by_id[property_claim_id("client", "CorporateClient", "clientName")]
    prop_types = {ev.type for ev in prop_claim.evidence_sources}
    assert "skos_mapping" in prop_types, "property claim should gain SKOS evidence"

    # C4 guard: every claim stays proposed (no silent auto-approval).
    assert all(c.status == "proposed" for c in registry.claims)
    assert all(
        CONFORMANCE_EVIDENCE_TYPE not in {
            evidence.type for evidence in claim.evidence_sources
        }
        for claim in registry.claims
    )
    assert report.total_conformance_proposals == 0


def test_conformance_fixture_proposes_all_applicable_outcomes(tmp_path):
    """All tiers participate; the five outcomes map deterministically or skip."""
    claims_dir = tmp_path / "model" / "claims"
    write_registry(_seed_client_registry(), claims_dir / "client-claims.yaml")

    report = run_derive_claims(
        claims_dir,
        conformance_path=CONFORMANCE_PATH,
    )

    registry = load_registry(claims_dir / "client-claims.yaml")
    by_id = {claim.id: claim for claim in registry.claims}
    expected_dispositions = {
        "Party": "claim",
        "Customer": "claim",
        "Invoice": "claim",
        "InvoiceLine": "specialize",
        "DirectDebitMandate": "gap",
        "PaymentToken": "claim",
    }
    for local_name, disposition in expected_dispositions.items():
        claim = by_id[class_claim_id("client", local_name)]
        assert claim.status == "proposed"
        assert claim.disposition == disposition
        assert CONFORMANCE_EVIDENCE_TYPE in {
            evidence.type for evidence in claim.evidence_sources
        }

    assert class_claim_id("client", "CashDrawer") not in by_id
    optional = by_id[class_claim_id("client", "PaymentToken")]
    assert '"tier":"optional"' in (optional.evidence_sources[0].note or "")
    renamed = by_id[class_claim_id("client", "Customer")]
    assert '"rename_to":"Client"' in (renamed.evidence_sources[0].note or "")
    deviates = by_id[class_claim_id("client", "DirectDebitMandate")]
    assert deviates.deviation is not None
    assert "pre-authorised card tokens" in (deviates.deviation.reason or "")

    stats = report.domain_stats[0]
    assert stats.conformance_concepts == 7
    assert stats.conformance_proposals == 6
    assert stats.conformance_not_applicable == 1


def test_conformance_fixture_rerun_is_stable(tmp_path):
    """The real committed artifact produces byte-identical cached reruns."""
    claims_dir = tmp_path / "model" / "claims"
    registry_path = claims_dir / "client-claims.yaml"
    write_registry(_seed_client_registry(), registry_path)

    run_derive_claims(claims_dir, conformance_path=CONFORMANCE_PATH)
    first = registry_path.read_text(encoding="utf-8")
    second_report = run_derive_claims(
        claims_dir,
        conformance_path=CONFORMANCE_PATH,
    )

    assert registry_path.read_text(encoding="utf-8") == first
    assert second_report.written == []


def test_conformance_fixture_preserves_prior_decision(tmp_path):
    """A real-artifact proposal refreshes evidence without overriding curation."""
    claims_dir = tmp_path / "model" / "claims"
    registry = _seed_client_registry()
    party_uri = "https://kairos.cnext.eu/ref/party#Party"
    registry.claims.append(
        Claim(
            id=class_claim_id("client", "Party"),
            type="class",
            status="approved",
            disposition="skip",
            origin="imported",
            class_uri=party_uri,
            owner="domain-steward",
            rationale="Reviewed as out of domain.",
            evidence_sources=[EvidenceSource(type="review", note="human decision")],
        )
    )
    write_registry(registry, claims_dir / "client-claims.yaml")

    run_derive_claims(claims_dir, conformance_path=CONFORMANCE_PATH)

    party = {
        claim.id: claim
        for claim in load_registry(claims_dir / "client-claims.yaml").claims
    }[class_claim_id("client", "Party")]
    assert party.status == "approved"
    assert party.disposition == "skip"
    assert party.owner == "domain-steward"
    assert party.rationale == "Reviewed as out of domain."
    assert CONFORMANCE_EVIDENCE_TYPE in {
        evidence.type for evidence in party.evidence_sources
    }


def test_malformed_default_conformance_fails_explicitly(tmp_path):
    """A present malformed artifact is never treated like an absent artifact."""
    claims_dir = tmp_path / "model" / "claims"
    write_registry(_seed_client_registry(), claims_dir / "client-claims.yaml")
    malformed_path = tmp_path / ARTIFACT_RELPATH
    malformed_path.parent.mkdir(parents=True)
    malformed_path.write_text("core_concepts: [\n", encoding="utf-8")

    with pytest.raises(ConformanceArtifactError, match="Could not parse"):
        run_derive_claims(claims_dir)


def test_derive_claims_cli_round_trip(tmp_path):
    """The skill-gated ``derive-claims`` CLI enriches a tmp hub for one domain."""
    claims_dir = tmp_path / "model" / "claims"
    analysis_dir = tmp_path / "_analysis"
    write_registry(_seed_client_registry(), claims_dir / "client-claims.yaml")
    _write_affinity(analysis_dir)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "derive-claims",
            "--claims-dir",
            str(claims_dir),
            "--analysis-dir",
            str(analysis_dir),
            "--mappings",
            str(MAPPINGS_DIR),
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert result.exit_code == 0, result.output
    assert "1 domain" in result.output


def test_derive_preserves_human_decision(tmp_path):
    """An approved claim keeps its status + class_uri while gaining fresh evidence."""
    claims_dir = tmp_path / "model" / "claims"
    analysis_dir = tmp_path / "_analysis"
    class_uri = "https://acme.example/ontology/client#CorporateClient"
    write_registry(
        _seed_client_registry(class_status="approved", class_uri=class_uri),
        claims_dir / "client-claims.yaml",
    )
    _write_affinity(analysis_dir)

    run_derive_claims(
        claims_dir,
        analysis_dir=analysis_dir,
        mappings_dir=MAPPINGS_DIR,
    )

    registry = load_registry(claims_dir / "client-claims.yaml")
    class_claim = {c.id: c for c in registry.claims}[
        class_claim_id("client", "CorporateClient")
    ]
    assert class_claim.status == "approved", "human decision must survive re-run"
    assert class_claim.class_uri == class_uri
    class_types = {ev.type for ev in class_claim.evidence_sources}
    assert {"affinity", "skos_mapping"} <= class_types, "evidence still refreshed"
