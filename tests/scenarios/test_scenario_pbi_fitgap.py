# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for the Slice 5 Power BI / source fit-gap path.

Exercises ``pbi-source-fit-gap`` and ``tmdl-to-gold-ext`` end-to-end against an
acme-hub-style ``invoice`` domain. As with the other evidence-led scenario tests,
the registry + TMDL fixtures are built in ``tmp_path`` so the shared acme-hub
``model/claims/`` stays absent (the Slice 2 projector authority gate must not
fire for the shared projection tests).
"""

from pathlib import Path

from click.testing import CliRunner
from rdflib import Graph, Namespace

from kairos_ontology.claim_registry import (
    Claim,
    ClaimRegistry,
    EvidenceSource,
    write_registry,
)
from kairos_ontology.cli.main import cli

INVOICE_NS = "https://acme.example/ontology/invoice#"
EXT = Namespace("https://kairos.cnext.eu/ext#")

# A small TMDL semantic model mirroring an Acme finance report: a fact table
# backed by BillingPro, a measure over it, a hierarchy, and a legacy table.
_TMDL = """table FactInvoice
\tcolumn InvoiceId
\t\tdataType: string
\tcolumn TotalAmount
\t\tdataType: decimal
\tmeasure 'Total Revenue' = SUM(FactInvoice[TotalAmount])
\t\tformatString: #,##0.00
\thierarchy Calendar
\t\tlevel Year
\t\t\tcolumn: InvoiceYear
\t\tlevel Month
\t\t\tcolumn: InvoiceMonth

table LegacyScratch
\tcolumn Note
\t\tdataType: string
"""


def _seed_invoice_registry() -> ClaimRegistry:
    """Approved, BillingPro-backed Invoice claim linked to the PBI FactInvoice."""
    return ClaimRegistry(
        domain="invoice",
        claims=[
            Claim(
                id="invoice-invoice",
                type="class",
                status="approved",
                disposition="claim",
                origin="imported",
                class_uri=f"{INVOICE_NS}Invoice",
                evidence_sources=[
                    EvidenceSource(
                        type="tmdl_concept_mapping",
                        model="AcmeFinance",
                        table="FactInvoice",
                        note="action=use",
                    ),
                    EvidenceSource(
                        type="source_table", system="billingpro", table="invoices"
                    ),
                ],
            ),
        ],
    )


def _write_model(tmp_path: Path) -> Path:
    tmdl = tmp_path / "AcmeFinance.tmdl"
    tmdl.write_text(_TMDL, encoding="utf-8")
    return tmdl


def test_pbi_fit_gap_cli_classifies_invoice(tmp_path: Path):
    """fit-gap CLI marks the BillingPro-backed fact fit and legacy table defer."""
    claims_dir = tmp_path / "model" / "claims"
    write_registry(_seed_invoice_registry(), claims_dir / "invoice-claims.yaml")
    tmdl = _write_model(tmp_path)
    out = tmp_path / "fit-gap.md"

    result = CliRunner().invoke(
        cli,
        [
            "pbi-source-fit-gap",
            str(tmdl),
            "--domain", "invoice",
            "--claims-dir", str(claims_dir),
            "-o", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    report = out.read_text(encoding="utf-8")

    # Fact fields and the measure are fit (approved + BillingPro-backed).
    assert "`FactInvoice[InvoiceId]` | fit" in report
    assert "`FactInvoice[Total Revenue]` | fit" in report
    # Legacy table has no claim → defer (visible, unused report artifact).
    assert "`LegacyScratch[Note]` | defer" in report
    # The evidence-not-authority guardrail is present.
    assert "evidence, not authority" in report


def test_tmdl_to_gold_ext_seeds_candidate(tmp_path: Path):
    """gold-ext seed CLI emits a candidate TTL with measure + hierarchy annotations."""
    claims_dir = tmp_path / "model" / "claims"
    write_registry(_seed_invoice_registry(), claims_dir / "invoice-claims.yaml")
    tmdl = _write_model(tmp_path)
    out = tmp_path / "invoice-gold-ext.candidate.ttl"

    result = CliRunner().invoke(
        cli,
        [
            "tmdl-to-gold-ext",
            str(tmdl),
            "--domain", "invoice",
            "--claims-dir", str(claims_dir),
            "-o", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    ttl = out.read_text(encoding="utf-8")
    assert ttl.startswith("# CANDIDATE gold-extension seed")

    graph = Graph()
    graph.parse(data=ttl, format="turtle")
    DOMAIN = Namespace(INVOICE_NS)  # derived from the registry class_uri
    # Measure seeded as a candidate measureExpression annotation.
    exprs = [str(e) for e in graph.objects(DOMAIN.totalRevenue, EXT.measureExpression)]
    assert exprs == ["SUM(FactInvoice[TotalAmount])"]
    # Hierarchy levels seeded as hierarchyName annotations.
    names = [str(n) for n in graph.objects(DOMAIN.invoiceYear, EXT.hierarchyName)]
    assert names == ["Calendar"]
