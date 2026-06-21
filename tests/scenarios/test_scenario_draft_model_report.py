# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for reporting-informed draft model reports."""

from pathlib import Path

import yaml

from kairos_ontology.claim_registry import Claim, ClaimRegistry, EvidenceSource, write_registry
from kairos_ontology.draft_model_report import build_draft_model_report, write_draft_model_report


def test_scenario_draft_report_keeps_visual_model_advisory(tmp_path: Path):
    """A hub-like reporting dry run emits evidence + ERD without claim authority."""
    claims_dir = tmp_path / "model" / "claims"
    analysis_dir = tmp_path / "integration" / "sources" / "_analysis"
    tmdl_dir = tmp_path / "integration" / "sources" / "powerbi"
    claims_dir.mkdir(parents=True)
    analysis_dir.mkdir(parents=True)
    tmdl_dir.mkdir(parents=True)

    write_registry(
        ClaimRegistry(
            domain="client",
            claims=[
                Claim(
                    id="client-corporateclient",
                    type="class",
                    status="approved",
                    disposition="claim",
                    origin="imported",
                    class_uri="https://example.com/ref/client#CorporateClient",
                    evidence_sources=[
                        EvidenceSource(
                            type="source_table",
                            system="adminpulse",
                            table="tblClient",
                        )
                    ],
                )
            ],
        ),
        claims_dir / "client-claims.yaml",
    )
    (analysis_dir / "adminpulse-affinity.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "system": "adminpulse",
                "tables": [
                    {
                        "table": "tblClient",
                        "domain": "client",
                        "likely_entity": "CorporateClient",
                        "confidence": 0.94,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmdl_dir / "sales-concept-mapping.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "model_name": "SalesModel",
                "tables": [
                    {
                        "tmdl_name": "d_Client",
                        "type": "dimension",
                        "domain": "client",
                        "columns": ["ClientNo", "Name"],
                        "measures": [],
                        "reference_model_match": "CorporateClient",
                        "action": "use",
                    },
                    {
                        "tmdl_name": "f_Invoice",
                        "type": "fact",
                        "domain": "invoice",
                        "columns": ["ClientNo", "Amount"],
                        "measures": [{"name": "Invoice Amount", "expression": "SUM(f_Invoice[Amount])"}],
                        "reference_model_match": "Invoice",
                        "action": "new_class",
                    },
                ],
                "relationships": [
                    {
                        "from": "f_Invoice.ClientNo",
                        "to": "d_Client.ClientNo",
                        "cardinality": "many-to-one",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_draft_model_report(
        claims_dir=claims_dir,
        analysis_dir=analysis_dir,
        tmdl_dir=tmdl_dir,
    )
    artifacts = write_draft_model_report(report, tmp_path / "model" / "planning" / "draft-model")

    assert report["projection_authority"] is False
    assert {"client", "invoice"} <= set(report["domains"])
    assert artifacts.mermaid.exists()
    assert "many-to-one" in artifacts.mermaid.read_text(encoding="utf-8")
    assert not (tmp_path / "model" / "ontologies").exists(), "report must not scaffold TTL"
