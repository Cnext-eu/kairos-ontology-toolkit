# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for the Slice 6 change-management / contract-versioning path.

Exercises ``source-delta-report`` end-to-end: (1) against the real acme-hub
AdminPulse bronze vocabulary + mappings with an approved registry built in
``tmp_path`` (so the shared acme-hub ``model/claims/`` stays absent), and (2) a
new/changed system with a baseline diff that must surface breaking deltas.
"""

from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.claim_registry import (
    Claim,
    ClaimRegistry,
    ContractMeta,
    write_registry,
)
from kairos_ontology.cli.main import cli

HUB_ROOT = Path(__file__).parent / "acme-hub"
SOURCES_DIR = HUB_ROOT / "integration" / "sources"
MAPPINGS_DIR = HUB_ROOT / "model" / "mappings"

CLIENT_NS = "https://acme.example/ontology/client#"

# AdminPulse table-level mapping targets (from adminpulse-to-client.ttl).
_APPROVED_CLASSES = (
    "CorporateClient",
    "SoleProprietorClient",
    "IndividualClient",
    "Client",
    "ClientPII",
    "ClientType",
    "Identifier",
)
_APPROVED_PROPS = (
    "clientId",
    "clientName",
    "vatNumber",
    "email",
    "isActive",
    "createdAt",
)


def _seed_client_registry() -> ClaimRegistry:
    claims: list[Claim] = []
    for i, cls in enumerate(_APPROVED_CLASSES):
        claims.append(
            Claim(id=f"client-class-{i}", type="class", status="approved",
                  class_uri=f"{CLIENT_NS}{cls}")
        )
    for i, prop in enumerate(_APPROVED_PROPS):
        claims.append(
            Claim(id=f"client-prop-{i}", type="property", status="approved",
                  property_uri=f"{CLIENT_NS}{prop}")
        )
    return ClaimRegistry(
        domain="client",
        contract=ContractMeta(silver_version="1.4.0", gold_version="1.0.0"),
        claims=claims,
    )


def test_source_delta_cli_adminpulse_maps_to_existing(tmp_path: Path):
    """AdminPulse tables map to approved classes → mapping-only, no breaking."""
    claims_dir = tmp_path / "model" / "claims"
    write_registry(_seed_client_registry(), claims_dir / "client-claims.yaml")
    out = tmp_path / "adminpulse-source-delta.md"

    result = CliRunner().invoke(
        cli,
        [
            "source-delta-report",
            "--system", "adminpulse",
            "--sources", str(SOURCES_DIR),
            "--mappings", str(MAPPINGS_DIR),
            "--claims-dir", str(claims_dir),
            "-o", str(out),
            "--fail-on-breaking",
        ],
    )
    assert result.exit_code == 0, result.output
    report = out.read_text(encoding="utf-8")

    # Every AdminPulse table maps to an approved class.
    assert "maps-to-existing-class" in report
    # Contract version is read from the seeded registry and surfaced.
    assert "1.4.0" in report
    # No breaking deltas (no baseline diff) → no major bump.
    assert "Breaking: **0**" in report


def test_source_delta_cli_baseline_breaking(tmp_path: Path):
    """A changed source with a baseline diff surfaces breaking deltas + fails CI."""
    sources = tmp_path / "integration" / "sources"
    sources.mkdir(parents=True)
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    claims_dir = tmp_path / "model" / "claims"

    # Approve an Order class so the mapped table is "maps-to-existing".
    write_registry(
        ClaimRegistry(
            domain="sales",
            contract=ContractMeta(silver_version="2.0.0"),
            claims=[Claim(id="o", type="class", status="approved",
                          class_uri="https://acme.example/ontology/sales#Order")],
        ),
        claims_dir / "sales-claims.yaml",
    )

    baseline_vocab = """\
@prefix bronze-erp: <https://acme.example/bronze/erp#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

bronze-erp:tblOrder a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblOrder" ;
    kairos-bronze:primaryKeyColumns "OrderID" .

bronze-erp:tblOrder_OrderID a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-erp:tblOrder ;
    kairos-bronze:columnName "OrderID" ;
    kairos-bronze:dataType "int" .

bronze-erp:tblOrder_Amount a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-erp:tblOrder ;
    kairos-bronze:columnName "Amount" ;
    kairos-bronze:dataType "int" .

bronze-erp:tblOrder_Legacy a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-erp:tblOrder ;
    kairos-bronze:columnName "Legacy" ;
    kairos-bronze:dataType "nvarchar(50)" .
"""
    # New version: PK changed (breaking), Amount type narrowed int→nvarchar
    # (breaking), Legacy removed (breaking), new Notes column (additive).
    new_vocab = """\
@prefix bronze-erp: <https://acme.example/bronze/erp#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

bronze-erp:tblOrder a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblOrder" ;
    kairos-bronze:primaryKeyColumns "OrderGUID" .

bronze-erp:tblOrder_OrderGUID a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-erp:tblOrder ;
    kairos-bronze:columnName "OrderGUID" ;
    kairos-bronze:dataType "nvarchar(36)" .

bronze-erp:tblOrder_OrderID a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-erp:tblOrder ;
    kairos-bronze:columnName "OrderID" ;
    kairos-bronze:dataType "int" .

bronze-erp:tblOrder_Amount a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-erp:tblOrder ;
    kairos-bronze:columnName "Amount" ;
    kairos-bronze:dataType "nvarchar(20)" .

bronze-erp:tblOrder_Notes a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-erp:tblOrder ;
    kairos-bronze:columnName "Notes" ;
    kairos-bronze:dataType "nvarchar(200)" .
"""
    (sources / "erp.vocabulary.ttl").write_text(new_vocab, encoding="utf-8")
    (baseline_dir / "erp.vocabulary.ttl").write_text(baseline_vocab, encoding="utf-8")
    out = tmp_path / "erp-source-delta.md"

    result = CliRunner().invoke(
        cli,
        [
            "source-delta-report",
            "--system", "erp",
            "--sources", str(sources),
            "--mappings", str(tmp_path / "no-mappings"),
            "--claims-dir", str(claims_dir),
            "--baseline", str(baseline_dir),
            "-o", str(out),
            "--fail-on-breaking",
        ],
    )
    # Breaking deltas present → --fail-on-breaking exits 2.
    assert result.exit_code == 2, result.output
    report = out.read_text(encoding="utf-8")
    assert "changed-key" in report
    assert "removed-column" in report
    assert "changed-type" in report
    # New Notes column is additive.
    assert "passthrough-candidate" in report
    # Major bump suggested (breaking present): 2.0.0 → 3.0.0.
    assert "3.0.0" in report
