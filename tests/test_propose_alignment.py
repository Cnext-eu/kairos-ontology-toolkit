# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for propose_alignment module."""

from __future__ import annotations

import json
from unittest import mock

import pytest
import yaml

from kairos_ontology.propose_alignment import (
    ColumnAlignment,
    DomainAlignment,
    TableAlignment,
    _build_reference_rollup,
    _clamp_confidence,
    _select_ref_classes_for_table,
    _should_retry_with_full_inventory,
    align_table,
    build_alignment_prompt,
    load_affinity_reports,
    run_propose_alignment,
    write_alignment_output,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def analysis_dir(tmp_path):
    """Create a directory with sample affinity reports."""
    analysis = tmp_path / "_analysis"
    analysis.mkdir()

    affinity = {
        "system": "adminpulse",
        "analysed_at": "2026-06-05T10:00:00Z",
        "model_used": "gpt-5.4-mini",
        "schema_version": 2,
        "tables": [
            {
                "table": "tblContracts",
                "total_columns": 5,
                "domain": "commercial",
                "domain_group": "party-commercial",
                "domain_uris": ["https://example.com/ont/commercial#"],
                "confidence": 0.9,
                "likely_entity": "SalesContract",
                "indicative_columns": ["ContractNo", "ValidFrom"],
            },
            {
                "table": "tblParties",
                "total_columns": 3,
                "domain": "party",
                "domain_group": "party-commercial",
                "domain_uris": ["https://example.com/ont/party#"],
                "confidence": 0.85,
                "likely_entity": "TradeParty",
                "indicative_columns": ["PartyName"],
            },
        ],
        "domain_summary": [
            {"domain": "commercial", "table_count": 1, "tables": ["tblContracts"]},
            {"domain": "party", "table_count": 1, "tables": ["tblParties"]},
        ],
    }

    with open(analysis / "adminpulse-affinity.yaml", "w") as f:
        yaml.dump(affinity, f)

    return analysis


@pytest.fixture
def sources_dir(tmp_path):
    """Create a directory with sample source vocabulary TTL."""
    sources = tmp_path / "sources"
    admin_dir = sources / "adminpulse"
    admin_dir.mkdir(parents=True)

    vocab_ttl = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<#tblContracts> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblContracts" .

<#tblContracts_ContractNo> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "ContractNo" ;
    kairos-bronze:dataType "nvarchar(50)" ;
    kairos-bronze:belongsToTable <#tblContracts> .

<#tblContracts_ValidFrom> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "ValidFrom" ;
    kairos-bronze:dataType "datetime" ;
    kairos-bronze:belongsToTable <#tblContracts> .

<#tblContracts_InternalCode> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "InternalCode" ;
    kairos-bronze:dataType "nvarchar(20)" ;
    kairos-bronze:belongsToTable <#tblContracts> .

<#tblParties> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblParties" .

<#tblParties_PartyName> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "PartyName" ;
    kairos-bronze:dataType "nvarchar(100)" ;
    kairos-bronze:belongsToTable <#tblParties> .
"""
    (admin_dir / "adminpulse.vocabulary.ttl").write_text(vocab_ttl, encoding="utf-8")
    return sources


@pytest.fixture
def sample_ref_classes():
    """Sample reference model class inventory."""
    return [
        {
            "name": "SalesContract",
            "label": "Sales Contract",
            "comment": "A commercial agreement between parties",
            "properties": [
                {"name": "contractIdentifier", "label": "Contract Identifier", "range": "string"},
                {"name": "effectiveDate", "label": "Effective Date", "range": "dateTime"},
                {"name": "contractType", "label": "Contract Type", "range": "string"},
            ],
        },
        {
            "name": "TradeTerms",
            "label": "Trade Terms",
            "comment": "Terms governing a transaction",
            "properties": [
                {"name": "incoterm", "label": "Incoterm", "range": "string"},
                {"name": "paymentTerms", "label": "Payment Terms", "range": "string"},
            ],
        },
    ]


# ---------------------------------------------------------------------------
# Tests: load_affinity_reports
# ---------------------------------------------------------------------------


class TestLoadAffinityReports:
    def test_loads_and_groups_by_domain(self, analysis_dir):
        result = load_affinity_reports(analysis_dir)
        assert "commercial" in result
        assert "party" in result
        assert len(result["commercial"]) == 1
        assert result["commercial"][0]["table"] == "tblContracts"
        assert result["commercial"][0]["system"] == "adminpulse"

    def test_empty_dir_returns_empty(self, tmp_path):
        result = load_affinity_reports(tmp_path)
        assert result == {}

    def test_skips_non_v2_reports(self, tmp_path):
        old = {"schema_version": 1, "system": "old", "affinities": []}
        with open(tmp_path / "old-affinity.yaml", "w") as f:
            yaml.dump(old, f)
        result = load_affinity_reports(tmp_path)
        assert result == {}

    def test_preserves_domain_uris(self, analysis_dir):
        result = load_affinity_reports(analysis_dir)
        assert result["commercial"][0]["domain_uris"] == [
            "https://example.com/ont/commercial#"
        ]


# ---------------------------------------------------------------------------
# Tests: build_alignment_prompt
# ---------------------------------------------------------------------------


class TestBuildAlignmentPrompt:
    def test_includes_table_and_columns(self, sample_ref_classes):
        columns = [
            {"name": "ContractNo", "data_type": "nvarchar(50)", "samples": ["C-001"]},
            {"name": "ValidFrom", "data_type": "datetime", "samples": []},
        ]
        prompt = build_alignment_prompt("tblContracts", columns, sample_ref_classes)
        assert "tblContracts" in prompt
        assert "ContractNo" in prompt
        assert "ValidFrom" in prompt

    def test_includes_ref_classes_and_properties(self, sample_ref_classes):
        columns = [{"name": "X", "data_type": "string"}]
        prompt = build_alignment_prompt("tbl", columns, sample_ref_classes)
        assert "SalesContract" in prompt
        assert "contractIdentifier" in prompt
        assert "TradeTerms" in prompt
        assert "incoterm" in prompt

    def test_includes_entity_hint(self, sample_ref_classes):
        columns = [{"name": "X", "data_type": "string"}]
        prompt = build_alignment_prompt(
            "tbl", columns, sample_ref_classes, likely_entity="SalesContract"
        )
        assert "SalesContract" in prompt
        assert "HINT" in prompt

    def test_no_hint_when_empty(self, sample_ref_classes):
        columns = [{"name": "X", "data_type": "string"}]
        prompt = build_alignment_prompt("tbl", columns, sample_ref_classes)
        assert "HINT" not in prompt


# ---------------------------------------------------------------------------
# Tests: align_table
# ---------------------------------------------------------------------------


class TestAlignTable:
    def _mock_client(self, response_dict):
        client = mock.MagicMock()
        client.chat.completions.create.return_value = mock.MagicMock(
            choices=[mock.MagicMock(
                message=mock.MagicMock(content=json.dumps(response_dict))
            )]
        )
        return client

    def test_valid_alignment(self, sample_ref_classes):
        response = {
            "ref_class": "SalesContract",
            "ref_class_confidence": 0.95,
            "column_alignments": [
                {
                    "column": "ContractNo",
                    "ref_class": "SalesContract",
                    "ref_property": "contractIdentifier",
                    "alignment": "semantic",
                    "confidence": 0.92,
                    "rationale": "Contract number maps to identifier",
                },
                {
                    "column": "InternalCode",
                    "ref_property": "internalCode",
                    "alignment": "custom",
                    "confidence": 0.0,
                    "rationale": "No ref model match",
                },
            ],
        }
        client = self._mock_client(response)
        columns = [
            {"name": "ContractNo", "data_type": "nvarchar(50)"},
            {"name": "InternalCode", "data_type": "nvarchar(20)"},
        ]
        result = align_table(client, "gpt-5.4-mini", "tblContracts", columns,
                             sample_ref_classes)

        assert result["ref_class"] == "SalesContract"
        assert result["ref_class_confidence"] == 0.95
        assert len(result["column_alignments"]) == 2
        assert result["column_alignments"][0]["alignment"] == "semantic"
        assert result["column_alignments"][1]["alignment"] == "custom"

    def test_invalid_ref_class_cleared(self, sample_ref_classes):
        response = {
            "ref_class": "NonExistent",
            "ref_class_confidence": 0.8,
            "column_alignments": [],
        }
        client = self._mock_client(response)
        columns = [{"name": "X", "data_type": "string"}]
        result = align_table(client, "gpt-5.4-mini", "tbl", columns, sample_ref_classes)
        assert result["ref_class"] == ""

    def test_invalid_alignment_type_defaults_to_custom(self, sample_ref_classes):
        response = {
            "ref_class": "SalesContract",
            "ref_class_confidence": 0.8,
            "column_alignments": [
                {"column": "X", "ref_property": "p", "alignment": "invalid", "confidence": 0.5},
            ],
        }
        client = self._mock_client(response)
        columns = [{"name": "X", "data_type": "string"}]
        result = align_table(client, "gpt-5.4-mini", "tbl", columns, sample_ref_classes)
        assert result["column_alignments"][0]["alignment"] == "custom"

    def test_unknown_column_filtered(self, sample_ref_classes):
        response = {
            "ref_class": "SalesContract",
            "ref_class_confidence": 0.8,
            "column_alignments": [
                {"column": "GHOST", "ref_property": "p", "alignment": "exact", "confidence": 0.9},
            ],
        }
        client = self._mock_client(response)
        columns = [{"name": "RealCol", "data_type": "string"}]
        result = align_table(client, "gpt-5.4-mini", "tbl", columns, sample_ref_classes)
        assert len(result["column_alignments"]) == 0

    def test_empty_ref_classes_returns_empty(self):
        client = mock.MagicMock()
        columns = [{"name": "X", "data_type": "string"}]
        result = align_table(client, "gpt-5.4-mini", "tbl", columns, [])
        assert result["ref_class"] == ""
        assert result["column_alignments"] == []

    def test_llm_failure_returns_empty(self, sample_ref_classes):
        client = mock.MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("API down")
        columns = [{"name": "X", "data_type": "string"}]
        result = align_table(client, "gpt-5.4-mini", "tbl", columns, sample_ref_classes)
        assert result["ref_class"] == ""
        assert result["column_alignments"] == []


class TestPromptClassShortlist:
    def test_shortlist_is_deterministic_even_if_input_order_changes(self):
        ref_classes = [
            {"name": "TradeTerms", "label": "Trade Terms", "comment": "", "properties": []},
            {"name": "SalesContract", "label": "Sales Contract", "comment": "", "properties": []},
            {"name": "Address", "label": "Address", "comment": "", "properties": []},
        ]
        columns = [{"name": "ContractNo", "data_type": "nvarchar(50)", "samples": ["C-1"]}]

        selected_a = _select_ref_classes_for_table(
            "tblContracts", columns, ref_classes, max_classes=2
        )
        selected_b = _select_ref_classes_for_table(
            "tblContracts", columns, list(reversed(ref_classes)), max_classes=2
        )
        assert [c["name"] for c in selected_a] == [c["name"] for c in selected_b]

    def test_shortlist_pins_likely_entity_when_present(self):
        ref_classes = [
            {"name": "TradeTerms", "label": "Trade Terms", "comment": "", "properties": []},
            {"name": "Address", "label": "Address", "comment": "", "properties": []},
            {"name": "SalesContract", "label": "Sales Contract", "comment": "", "properties": []},
        ]
        selected = _select_ref_classes_for_table(
            "tblX",
            [{"name": "X", "data_type": "string", "samples": []}],
            ref_classes,
            likely_entity="SalesContract",
            max_classes=1,
        )
        assert [c["name"] for c in selected] == ["SalesContract"]


class TestRetryPolicy:
    def test_retry_when_ref_class_missing(self):
        assert _should_retry_with_full_inventory(
            {"ref_class": "", "ref_class_confidence": 0.9, "column_alignments": []},
            total_columns=5,
        )

    def test_retry_when_mapped_ratio_too_low(self):
        assert _should_retry_with_full_inventory(
            {
                "ref_class": "SalesContract",
                "ref_class_confidence": 0.95,
                "column_alignments": [{"alignment": "custom"}],
            },
            total_columns=4,
            min_mapped_ratio=0.5,
        )


# ---------------------------------------------------------------------------
# Tests: _clamp_confidence
# ---------------------------------------------------------------------------


class TestClampConfidence:
    def test_normal_value(self):
        assert _clamp_confidence(0.5) == 0.5

    def test_over_one(self):
        assert _clamp_confidence(1.5) == 1.0

    def test_negative(self):
        assert _clamp_confidence(-0.3) == 0.0

    def test_string(self):
        assert _clamp_confidence("0.7") == 0.7

    def test_invalid(self):
        assert _clamp_confidence("not_a_number") == 0.0

    def test_none(self):
        assert _clamp_confidence(None) == 0.0


# ---------------------------------------------------------------------------
# Tests: write_alignment_output
# ---------------------------------------------------------------------------


class TestWriteAlignmentOutput:
    def test_writes_yaml(self, tmp_path):
        alignment = DomainAlignment(
            domain="commercial",
            domain_uris=["https://example.com/ont/commercial#"],
            generated_at="2026-06-05T10:00:00Z",
            model_used="gpt-5.4-mini",
            tables=[
                TableAlignment(
                    system="admin",
                    table="tblContracts",
                    ref_class="SalesContract",
                    ref_class_confidence=0.95,
                    columns=[
                        ColumnAlignment(
                            column="ContractNo",
                            data_type="nvarchar(50)",
                            ref_class="SalesContract",
                            ref_property="contractIdentifier",
                            alignment="semantic",
                            confidence=0.92,
                        ),
                    ],
                    custom_columns=[
                        {"column": "InternalCode", "data_type": "nvarchar(20)",
                         "suggested_property": "internalCode", "rationale": "No match"},
                    ],
                ),
            ],
        )

        out_path = write_alignment_output(alignment, tmp_path)
        assert out_path.name == "commercial-alignment.yaml"
        assert out_path.exists()

        with open(out_path) as f:
            data = yaml.safe_load(f)

        assert data["schema_version"] == 2
        assert data["domain"] == "commercial"
        assert len(data["tables"]) == 1
        assert data["tables"][0]["ref_class"] == "SalesContract"
        assert len(data["tables"][0]["columns"]) == 1
        assert data["tables"][0]["columns"][0]["alignment"] == "semantic"
        assert len(data["tables"][0]["custom_columns"]) == 1


# ---------------------------------------------------------------------------
# Tests: _build_reference_rollup
# ---------------------------------------------------------------------------


class TestBuildReferenceRollup:
    def test_rollup_with_matches(self, sample_ref_classes):
        alignment = DomainAlignment(
            domain="commercial",
            domain_uris=[],
            generated_at="",
            model_used="",
            tables=[
                TableAlignment(
                    system="admin",
                    table="tblContracts",
                    ref_class="SalesContract",
                    ref_class_confidence=0.95,
                    columns=[
                        ColumnAlignment(
                            column="ContractNo",
                            data_type="nvarchar(50)",
                            ref_class="SalesContract",
                            ref_property="contractIdentifier",
                            alignment="semantic",
                            confidence=0.92,
                        ),
                    ],
                ),
            ],
        )
        rollup = _build_reference_rollup(alignment, sample_ref_classes)
        assert len(rollup) == 2

        # SalesContract should have higher coverage
        sc = next(r for r in rollup if r["ref_class"] == "SalesContract")
        assert sc["matched_properties"] == 1
        assert sc["ref_properties_total"] == 3
        assert sc["coverage_pct"] == pytest.approx(33.3, abs=0.1)
        assert "admin.tblContracts" in sc["source_tables"]

        # TradeTerms should have 0 coverage
        tt = next(r for r in rollup if r["ref_class"] == "TradeTerms")
        assert tt["matched_properties"] == 0
        assert tt["coverage_pct"] == 0.0


# ---------------------------------------------------------------------------
# Tests: run_propose_alignment (integration with mocked LLM)
# ---------------------------------------------------------------------------


class TestRunProposeAlignment:
    def _mock_client(self, table_responses: dict[str, dict]):
        """Create a mock AI client that returns different responses per table."""
        def create_completion(**kwargs):
            prompt = kwargs["messages"][1]["content"]
            for table_name, response in table_responses.items():
                if table_name in prompt:
                    return mock.MagicMock(
                        choices=[mock.MagicMock(
                            message=mock.MagicMock(content=json.dumps(response))
                        )]
                    )
            return mock.MagicMock(
                choices=[mock.MagicMock(
                    message=mock.MagicMock(content=json.dumps({}))
                )]
            )

        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        return client

    def test_full_run(self, analysis_dir, sources_dir, tmp_path):
        responses = {
            "tblContracts": {
                "ref_class": "SalesContract",
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {"column": "ContractNo", "ref_class": "SalesContract",
                     "ref_property": "contractIdentifier", "alignment": "semantic",
                     "confidence": 0.92, "rationale": "Contract ID"},
                    {"column": "ValidFrom", "ref_class": "SalesContract",
                     "ref_property": "effectiveDate", "alignment": "semantic",
                     "confidence": 0.85, "rationale": "Start date"},
                    {"column": "InternalCode", "ref_property": "internalCode",
                     "alignment": "custom", "confidence": 0.0,
                     "rationale": "No match"},
                ],
            },
            "tblParties": {
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.88,
                "column_alignments": [
                    {"column": "PartyName", "ref_class": "TradeParty",
                     "ref_property": "partyName", "alignment": "exact",
                     "confidence": 0.95, "rationale": "Direct match"},
                ],
            },
        }
        client = self._mock_client(responses)
        output = tmp_path / "output"

        with mock.patch(
            "kairos_ontology.propose_alignment.get_ai_client", return_value=client
        ), mock.patch(
            "kairos_ontology.propose_alignment.extract_ref_model_inventory",
            return_value=[
                {"name": "SalesContract", "label": "Sales Contract", "comment": "",
                 "properties": [
                     {"name": "contractIdentifier", "label": "Contract ID", "range": "string"},
                     {"name": "effectiveDate", "label": "Effective Date", "range": "dateTime"},
                 ]},
            ],
        ):
            files = run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                output_dir=output,
            )

        assert len(files) == 2  # commercial + party
        names = {f.name for f in files}
        assert "commercial-alignment.yaml" in names
        assert "party-alignment.yaml" in names

        # Verify commercial alignment content
        with open(output / "commercial-alignment.yaml") as f:
            data = yaml.safe_load(f)
        assert data["schema_version"] == 2
        assert data["domain"] == "commercial"
        assert len(data["tables"]) == 1
        tbl = data["tables"][0]
        assert tbl["system"] == "adminpulse"
        assert tbl["table"] == "tblContracts"
        assert tbl["ref_class"] == "SalesContract"
        # 2 matched (semantic) + 0 custom in columns (custom goes to custom_columns)
        assert len(tbl["columns"]) == 2
        assert len(tbl["custom_columns"]) == 1

    def test_domain_filter(self, analysis_dir, sources_dir, tmp_path):
        client = mock.MagicMock()
        client.chat.completions.create.return_value = mock.MagicMock(
            choices=[mock.MagicMock(
                message=mock.MagicMock(content=json.dumps({
                    "ref_class": "", "ref_class_confidence": 0,
                    "column_alignments": [],
                }))
            )]
        )

        with mock.patch(
            "kairos_ontology.propose_alignment.get_ai_client", return_value=client
        ), mock.patch(
            "kairos_ontology.propose_alignment.extract_ref_model_inventory",
            return_value=[],
        ):
            files = run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                output_dir=tmp_path,
                domains_filter=["commercial"],
            )

        assert len(files) == 1
        assert files[0].name == "commercial-alignment.yaml"

    def test_no_affinity_reports_raises(self, tmp_path):
        with pytest.raises(ValueError, match="No affinity reports"):
            run_propose_alignment(
                analysis_dir=tmp_path,
                sources_dir=tmp_path,
                catalog_path=None,
                output_dir=tmp_path,
            )

    def test_invalid_domain_filter_raises(self, analysis_dir, sources_dir, tmp_path):
        with pytest.raises(ValueError, match="No domains matched"):
            run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                output_dir=tmp_path,
                domains_filter=["nonexistent"],
            )

    def test_retries_with_full_inventory_on_weak_shortlist(self, analysis_dir, sources_dir, tmp_path):
        calls: list[str] = []

        def create_completion(**kwargs):
            prompt = kwargs["messages"][1]["content"]
            calls.append(prompt)
            if "TradeTerms" in prompt:
                payload = {
                    "ref_class": "SalesContract",
                    "ref_class_confidence": 0.92,
                    "column_alignments": [
                        {
                            "column": "ContractNo",
                            "ref_class": "SalesContract",
                            "ref_property": "contractIdentifier",
                            "alignment": "semantic",
                            "confidence": 0.9,
                            "rationale": "id",
                        }
                    ],
                }
            else:
                payload = {
                    "ref_class": "",
                    "ref_class_confidence": 0.1,
                    "column_alignments": [],
                }
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
            )

        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        ref_classes = [
            {
                "name": "SalesContract",
                "label": "Sales Contract",
                "comment": "",
                "properties": [{"name": "contractIdentifier", "label": "Contract ID", "range": "string"}],
            },
            {
                "name": "TradeTerms",
                "label": "Trade Terms",
                "comment": "",
                "properties": [{"name": "incoterm", "label": "Incoterm", "range": "string"}],
            },
        ]

        with mock.patch(
            "kairos_ontology.propose_alignment.get_ai_client", return_value=client
        ), mock.patch(
            "kairos_ontology.propose_alignment.extract_ref_model_inventory",
            return_value=ref_classes,
        ):
            files = run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                output_dir=tmp_path,
                domains_filter=["commercial"],
                max_prompt_classes=1,
            )

        assert len(files) == 1
        # first call shortlist (no TradeTerms), second call full inventory (includes TradeTerms)
        assert len(calls) == 2
        assert "TradeTerms" not in calls[0]
        assert "TradeTerms" in calls[1]
