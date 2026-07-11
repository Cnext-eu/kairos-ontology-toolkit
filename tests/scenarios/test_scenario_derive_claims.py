# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for the Slice 3 ``derive-claims`` evidence-aggregation path.

These tests exercise the deterministic, AI-free ``derive-claims`` backend against
the synthetic **acme-hub** fixture.  ``derive-claims`` enriches an existing Claim
Registry by joining it with already-produced evidence streams (``analyse-sources``
affinity + ``model/mappings/*.ttl`` SKOS links) and attaching **multiple**
``evidence_sources`` per claim — every derived/new claim stays ``proposed``.

The permanent acme-hub deliberately has **no** ``model/claims/`` directory so the
projector's Slice 2 claim-authority gate never fires for the shared scenario
projection tests.  These tests therefore never write a claims file into the shared
hub: the registry + affinity evidence are built in ``tmp_path`` and only the real
``model/mappings/*.ttl`` files are read (read-only — ``derive-claims`` only reads
mappings, so pointing at the real directory is safe).
"""

from pathlib import Path

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
from kairos_ontology.core.derive_claims import (
    class_claim_id,
    load_skos_links,
    property_claim_id,
    run_derive_claims,
)

ACME_HUB = Path(__file__).resolve().parent / "acme-hub"
MAPPINGS_DIR = ACME_HUB / "model" / "mappings"


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
