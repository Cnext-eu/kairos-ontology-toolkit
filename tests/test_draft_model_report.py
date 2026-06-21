# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for advisory draft domain-model evidence reports."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.claim_registry import Claim, ClaimRegistry, EvidenceSource, write_registry
from kairos_ontology.cli.main import cli
from kairos_ontology.draft_model_report import (
    build_draft_model_report,
    load_data_product_contract,
    write_draft_model_report,
)


def _write_affinity(analysis_dir: Path) -> None:
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "crm-affinity.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "system": "crm",
                "tables": [
                    {
                        "table": "account",
                        "domain": "party",
                        "likely_entity": "TradeParty",
                        "confidence": 0.91,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_claims(claims_dir: Path) -> None:
    registry = ClaimRegistry(
        domain="party",
        claims=[
            Claim(
                id="party-tradeparty",
                type="class",
                status="approved",
                disposition="claim",
                origin="imported",
                class_uri="https://example.com/ref/party#TradeParty",
                evidence_sources=[EvidenceSource(type="source_table", system="crm", table="account")],
            )
        ],
    )
    write_registry(registry, claims_dir / "party-claims.yaml")


def _write_tmdl(tmdl_dir: Path) -> None:
    tmdl_dir.mkdir(parents=True)
    (tmdl_dir / "sales-concept-mapping.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "model_name": "SalesModel",
                "tables": [
                    {
                        "tmdl_name": "d_Customer",
                        "type": "dimension",
                        "domain": "party",
                        "columns": ["CustomerKey", "CustomerName"],
                        "measures": [],
                        "reference_model_match": "TradeParty",
                        "action": "use",
                    },
                    {
                        "tmdl_name": "f_Sales",
                        "type": "fact",
                        "domain": "commercial",
                        "columns": ["CustomerKey", "Amount"],
                        "measures": [
                            {
                                "name": "Total Sales",
                                "expression": "SUM(f_Sales[Amount])",
                            }
                        ],
                        "reference_model_match": "Sales",
                        "action": "new_class",
                    },
                ],
                "relationships": [
                    {
                        "from": "f_Sales.CustomerKey",
                        "to": "d_Customer.CustomerKey",
                        "cardinality": "many-to-one",
                        "reference_model_match": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_glossary(glossary_dir: Path) -> None:
    glossary_dir.mkdir(parents=True)
    (glossary_dir / "company-glossary.ttl").write_text(
        """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://example.com/glossary#> .

ex:customer a skos:Concept ;
    skos:prefLabel "Customer" .
""".strip(),
        encoding="utf-8",
    )


def _write_product_contract(path: Path, *, projection_authority: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "artifact": "data-product-contract",
                "projection_authority": projection_authority,
                "product": "sales-reporting",
                "tables": [
                    {
                        "name": "f_Sales",
                        "domain": "commercial",
                        "columns": ["Amount", "CustomerKey"],
                        "measures": ["Total Sales"],
                    },
                    {
                        "name": "d_Customer",
                        "domain": "party",
                        "columns": ["CustomerName"],
                    },
                ],
                "filters": ["Customer"],
                "grain": "sales transaction",
            }
        ),
        encoding="utf-8",
    )


def test_build_report_creates_all_domain_evidence_and_global_erd(tmp_path):
    claims_dir = tmp_path / "model" / "claims"
    analysis_dir = tmp_path / "integration" / "sources" / "_analysis"
    tmdl_dir = tmp_path / "integration" / "sources" / "powerbi"
    glossary_dir = tmp_path / "businessdiscovery"
    _write_claims(claims_dir)
    _write_affinity(analysis_dir)
    _write_tmdl(tmdl_dir)
    _write_glossary(glossary_dir)

    report = build_draft_model_report(
        claims_dir=claims_dir,
        analysis_dir=analysis_dir,
        tmdl_dir=tmdl_dir,
        glossary_dir=glossary_dir,
    )

    assert report["advisory"] is True
    assert report["projection_authority"] is False
    assert {"party", "commercial"} <= set(report["domains"])
    assert report["summary"]["tmdl_relationships"] == 1
    assert report["summary"]["tmdl_measures"] == 1
    assert "flowchart LR" in report["cross_domain_erd"]
    assert "domain_party" in report["cross_domain_erd"]
    assert "many-to-one" in report["cross_domain_erd"]

    party_entities = report["domains"]["party"]["candidate_entities"]
    assert any(entity["evidence_status"] == "claim-approved" for entity in party_entities)


def test_data_product_contract_must_be_non_authoritative(tmp_path):
    contract = tmp_path / "model" / "planning" / "data-products" / "sales" / "contract.yaml"
    _write_product_contract(contract, projection_authority=True)

    try:
        load_data_product_contract(contract)
    except ValueError as exc:
        assert "projection_authority: false" in str(exc)
    else:
        raise AssertionError("authoritative data-product contracts must be rejected")


def test_build_data_product_report_filters_and_keeps_planning_guardrails(tmp_path):
    claims_dir = tmp_path / "model" / "claims"
    analysis_dir = tmp_path / "integration" / "sources" / "_analysis"
    tmdl_dir = tmp_path / "integration" / "sources" / "powerbi"
    contract = tmp_path / "model" / "planning" / "data-products" / "sales" / "contract.yaml"
    _write_claims(claims_dir)
    _write_affinity(analysis_dir)
    _write_tmdl(tmdl_dir)
    _write_product_contract(contract)

    report = build_draft_model_report(
        claims_dir=claims_dir,
        analysis_dir=analysis_dir,
        tmdl_dir=tmdl_dir,
        data_product_contract_path=contract,
    )

    assert report["artifact"] == "data-product-draft-model-report"
    assert report["projection_authority"] is False
    assert report["contract"]["projection_authority"] is False
    assert report["triage_basis"] == "derived-from-dd086-evidence-status"
    assert report["provenance"]["stale"] is False
    assert {"party", "commercial"} <= set(report["domains"])

    commercial_gold = report["domains"]["commercial"]["gold_candidates"]
    assert commercial_gold
    assert commercial_gold[0]["product_triage"] == "claim-needed"
    assert commercial_gold[0]["disposition_suggestion"] != "gold-only"
    party_entities = report["domains"]["party"]["candidate_entities"]
    assert any(entity["product_triage"] == "covered" for entity in party_entities)


def test_write_report_outputs_yaml_markdown_and_unfenced_mermaid(tmp_path):
    tmdl_dir = tmp_path / "powerbi"
    _write_tmdl(tmdl_dir)
    report = build_draft_model_report(tmdl_dir=tmdl_dir)

    artifacts = write_draft_model_report(report, tmp_path / "out")

    assert artifacts.summary_yaml.exists()
    assert artifacts.markdown.exists()
    assert artifacts.mermaid.exists()
    assert artifacts.domain_yamls
    assert artifacts.mermaid.read_text(encoding="utf-8").startswith("flowchart LR")
    assert "```" not in artifacts.mermaid.read_text(encoding="utf-8")


def test_write_data_product_report_outputs_product_artifact_names(tmp_path):
    tmdl_dir = tmp_path / "powerbi"
    contract = tmp_path / "planning" / "data-products" / "sales" / "contract.yaml"
    _write_tmdl(tmdl_dir)
    _write_product_contract(contract)
    report = build_draft_model_report(
        tmdl_dir=tmdl_dir,
        data_product_contract_path=contract,
    )

    artifacts = write_draft_model_report(report, contract.parent)

    assert artifacts.summary_yaml.name == "data-product-plan.yaml"
    assert artifacts.markdown.name == "data-product-report.md"
    assert artifacts.mermaid.name == "data-product-erd.mmd"
    plan = yaml.safe_load(artifacts.summary_yaml.read_text(encoding="utf-8"))
    assert plan["projection_authority"] is False
    assert plan["artifact"] == "data-product-draft-model-report"


def test_draft_model_report_cli_writes_artifacts(tmp_path):
    _write_tmdl(tmp_path / "integration" / "sources" / "powerbi")
    output = tmp_path / "model" / "planning" / "draft-model"

    result = CliRunner().invoke(
        cli,
        [
            "draft-model-report",
            "--tmdl-dir",
            str(tmp_path / "integration" / "sources" / "powerbi"),
            "--output",
            str(output),
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    assert (output / "draft-model-report.yaml").exists()
    assert (output / "draft-model-report.md").exists()
    assert (output / "draft-model-erd.mmd").exists()


def test_draft_model_report_cli_writes_data_product_artifacts(tmp_path):
    _write_tmdl(tmp_path / "integration" / "sources" / "powerbi")
    contract = tmp_path / "model" / "planning" / "data-products" / "sales" / "contract.yaml"
    _write_product_contract(contract)

    result = CliRunner().invoke(
        cli,
        [
            "draft-model-report",
            "--tmdl-dir",
            str(tmp_path / "integration" / "sources" / "powerbi"),
            "--contract",
            str(contract),
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    assert (contract.parent / "data-product-plan.yaml").exists()
    assert (contract.parent / "data-product-report.md").exists()
    assert (contract.parent / "data-product-erd.mmd").exists()
    assert "Data-product vertical-slice plan" in result.output
