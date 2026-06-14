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
    _build_class_meta_index,
    _build_property_label_index,
    _build_reference_rollup,
    _clamp_confidence,
    _compact_prompt_samples,
    _detect_address_part,
    _format_source_columns,
    _module_tag,
    _parses_as,
    _resolve_column_module,
    _review_column_alignment,
    _select_property_pool,
    _select_ref_classes_for_table,
    _should_retry_with_full_inventory,
    _transform_compat_note,
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

    def test_anchors_on_matching_entity(self, sample_ref_classes):
        # CR-2: when likely_entity matches a candidate class, STEP 1 anchors on it
        # (confirm rather than re-derive) instead of emitting a soft HINT.
        columns = [{"name": "X", "data_type": "string"}]
        prompt = build_alignment_prompt(
            "tbl", columns, sample_ref_classes, likely_entity="SalesContract"
        )
        assert "SalesContract" in prompt
        assert "Confirm this class" in prompt
        assert "HINT" not in prompt

    def test_hint_when_entity_not_a_class(self, sample_ref_classes):
        # When likely_entity is not among the candidate classes, fall back to a
        # soft HINT so the model can still use the signal.
        columns = [{"name": "X", "data_type": "string"}]
        prompt = build_alignment_prompt(
            "tbl", columns, sample_ref_classes, likely_entity="Spaceship"
        )
        assert "HINT" in prompt
        assert "Spaceship" in prompt

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

    def test_no_retry_when_only_mapped_ratio_is_low(self):
        assert not _should_retry_with_full_inventory(
            {
                "ref_class": "SalesContract",
                "ref_class_confidence": 0.95,
                "column_alignments": [{"alignment": "custom"}],
            },
            total_columns=4,
            min_mapped_ratio=0.5,
        )

    def test_retry_when_confidence_and_mapped_ratio_are_both_low(self):
        assert _should_retry_with_full_inventory(
            {
                "ref_class": "SalesContract",
                "ref_class_confidence": 0.40,
                "column_alignments": [{"alignment": "custom"}],
            },
            total_columns=4,
            min_confidence=0.75,
            min_mapped_ratio=0.5,
        )


class TestPromptSampleCompaction:
    def test_compact_prompt_samples_filters_uuid_and_long_hex(self):
        samples = [
            "550e8400-e29b-41d4-a716-446655440000",
            "4f3e2d1c0b9a887766554433221100ff",
            "Valid business text",
        ]
        out = _compact_prompt_samples(samples)
        assert out == ["Valid business text"]

    def test_compact_prompt_samples_clips_long_text(self):
        long_text = "A" * 120
        out = _compact_prompt_samples([long_text])
        assert len(out) == 1
        assert len(out[0]) <= 48
        assert out[0].endswith("…")

    def test_format_source_columns_uses_compacted_samples(self):
        columns = [
            {
                "name": "Comment",
                "data_type": "nvarchar(200)",
                "samples": [
                    "550e8400-e29b-41d4-a716-446655440000",
                    "Customer asked for delayed invoice processing with split billing",
                ],
            }
        ]
        prompt_cols = _format_source_columns(columns)
        assert "550e8400-e29b-41d4-a716-446655440000" not in prompt_cols
        assert "Customer asked for delayed invoice processing" in prompt_cols


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

    def test_review_flags_emitted_only_when_set(self, tmp_path):
        """DD-069: review/review_reason emitted only when a column is flagged."""
        alignment = DomainAlignment(
            domain="party",
            domain_uris=["https://example.com/ont/party#"],
            generated_at="2026-06-05T10:00:00Z",
            model_used="gpt-5.4-mini",
            tables=[
                TableAlignment(
                    system="admin",
                    table="tblParties",
                    ref_class="TradeParty",
                    ref_class_confidence=0.9,
                    columns=[
                        ColumnAlignment(
                            column="PartyName",
                            data_type="nvarchar(100)",
                            ref_class="TradeParty",
                            ref_property="partyName",
                            alignment="exact",
                            confidence=0.95,
                        ),
                        ColumnAlignment(
                            column="SHIPPER_STREET",
                            data_type="nvarchar(100)",
                            ref_class="TradeParty",
                            ref_property="partyName",
                            alignment="semantic",
                            confidence=0.4,
                            review=True,
                            review_reason="address-part column mapped to non-address property",
                        ),
                    ],
                ),
            ],
        )
        out_path = write_alignment_output(alignment, tmp_path)
        with open(out_path) as f:
            data = yaml.safe_load(f)
        cols = data["tables"][0]["columns"]
        clean, flagged = cols[0], cols[1]
        assert "review" not in clean and "review_reason" not in clean
        assert flagged["review"] is True
        assert "address-part" in flagged["review_reason"]


# ---------------------------------------------------------------------------
# Tests: DD-069 review pass (issues #167/#168)
# ---------------------------------------------------------------------------


class TestDetectAddressPart:
    @pytest.mark.parametrize(
        "name",
        ["SHIPPER_STREET", "billing_zip", "postal_code", "address_line_1",
         "house_number", "consignee_city"],
    )
    def test_detects_strong_address_parts(self, name):
        assert _detect_address_part(name) is True

    @pytest.mark.parametrize(
        "name",
        ["country", "city", "clearingHouse", "warehouse", "countryOfBirth",
         "PartyName", ""],
    )
    def test_ignores_ambiguous_or_non_address(self, name):
        assert _detect_address_part(name) is False


class TestReviewColumnAlignment:
    @pytest.fixture
    def label_index(self):
        ref_classes = [
            {"name": "TradeParty", "properties": [
                {"name": "partyName", "label": "Party Name", "range": "string"},
                {"name": "partyIdentifier", "label": "Party Identifier", "range": "string"},
                {"name": "isActive", "label": "Is Active", "range": "boolean"},
                {"name": "address", "label": "Address", "range": "Address"},
            ]},
        ]
        return _build_property_label_index(ref_classes)

    def test_address_part_to_non_address_scalar_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="SHIPPER_STREET", data_type="nvarchar(100)",
            ref_class="TradeParty", ref_property="partyName",
            confidence=0.5, label_index=label_index,
        )
        assert reason and "address-part" in reason

    def test_address_part_to_address_property_not_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="SHIPPER_STREET", data_type="nvarchar(100)",
            ref_class="TradeParty", ref_property="address",
            confidence=0.5, label_index=label_index,
        )
        assert reason is None

    def test_boolean_to_identity_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="FCPAYABLEIND", data_type="bit",
            ref_class="TradeParty", ref_property="partyIdentifier",
            confidence=0.5, label_index=label_index,
        )
        assert reason and "boolean" in reason

    def test_financial_to_identity_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="IBAN", data_type="varchar(34)",
            ref_class="TradeParty", ref_property="partyIdentifier",
            confidence=0.9, label_index=label_index,
        )
        assert reason and "financial" in reason

    def test_no_token_overlap_low_confidence_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="XYZ123", data_type="nvarchar(50)",
            ref_class="TradeParty", ref_property="partyName",
            confidence=0.3, label_index=label_index,
        )
        assert reason and "share no name token" in reason

    def test_numeric_id_to_identifier_not_flagged(self, label_index):
        """ClientID int → partyIdentifier must not be noise (token overlap)."""
        reason = _review_column_alignment(
            column_name="PartyIdentifier", data_type="int",
            ref_class="TradeParty", ref_property="partyIdentifier",
            confidence=0.4, label_index=label_index,
        )
        assert reason is None

    def test_good_name_match_not_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="PartyName", data_type="nvarchar(100)",
            ref_class="TradeParty", ref_property="partyName",
            confidence=0.95, label_index=label_index,
        )
        assert reason is None

    def test_empty_property_not_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="anything", data_type="int",
            ref_class="TradeParty", ref_property="",
            confidence=0.1, label_index=label_index,
        )
        assert reason is None


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
        # Issue #164: custom columns are written with a null disposition awaiting triage.
        assert tbl["custom_columns"][0]["disposition"] is None

    def test_review_flag_end_to_end(self, analysis_dir, tmp_path):
        """DD-069: an address-part column force-fit onto a party scalar is flagged."""
        sources = tmp_path / "sources" / "adminpulse"
        sources.mkdir(parents=True)
        vocab = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
<#tblParties> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblParties" .
<#tblParties_SHIPPER_STREET> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "SHIPPER_STREET" ;
    kairos-bronze:dataType "nvarchar(100)" ;
    kairos-bronze:belongsToTable <#tblParties> .
"""
        (sources / "adminpulse.vocabulary.ttl").write_text(vocab, encoding="utf-8")

        responses = {
            "tblParties": {
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.88,
                "column_alignments": [
                    {"column": "SHIPPER_STREET", "ref_class": "TradeParty",
                     "ref_property": "partyName", "alignment": "semantic",
                     "confidence": 0.5, "rationale": "Best available"},
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
                {"name": "TradeParty", "label": "Trade Party", "comment": "",
                 "properties": [
                     {"name": "partyName", "label": "Party Name", "range": "string"},
                 ]},
            ],
        ):
            run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=tmp_path / "sources",
                catalog_path=None,
                output_dir=output,
                domains_filter=["party"],
            )

        with open(output / "party-alignment.yaml") as f:
            data = yaml.safe_load(f)
        col = data["tables"][0]["columns"][0]
        assert col["column"] == "SHIPPER_STREET"
        assert col["review"] is True
        assert "address-part" in col["review_reason"]

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


# ---------------------------------------------------------------------------
# Tests: concurrency + caching (CR-1 / CR-5)
# ---------------------------------------------------------------------------


class TestAlignmentConcurrencyAndCaching:
    REF_CLASSES = [
        {"name": "SalesContract", "label": "Sales Contract", "comment": "",
         "properties": [
             {"name": "contractIdentifier", "label": "Contract ID", "range": "string"},
         ]},
    ]

    def _counting_client(self, counter: list[int]):
        """A mock client that returns a valid alignment and counts each call."""
        def create_completion(**kwargs):
            counter.append(1)
            prompt = kwargs["messages"][1]["content"]
            ref_class = "SalesContract" if "tblContracts" in prompt else "TradeParty"
            payload = {
                "ref_class": ref_class,
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {"column": "ContractNo", "ref_class": ref_class,
                     "ref_property": "contractIdentifier", "alignment": "semantic",
                     "confidence": 0.9, "rationale": "id"},
                ],
            }
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
            )
        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        return client

    def _run(self, client, analysis_dir, sources_dir, output_dir, **kw):
        with mock.patch(
            "kairos_ontology.propose_alignment.get_ai_client", return_value=client
        ), mock.patch(
            "kairos_ontology.propose_alignment.extract_ref_model_inventory",
            return_value=self.REF_CLASSES,
        ):
            return run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                output_dir=output_dir,
                **kw,
            )

    def test_domain_skip_on_unchanged_affinity(self, analysis_dir, sources_dir, tmp_path):
        out = tmp_path / "out"
        counter: list[int] = []
        client = self._counting_client(counter)

        self._run(client, analysis_dir, sources_dir, out)
        first = len(counter)
        assert first > 0

        # Second run, same output → affinity_sha256 unchanged → domains skipped.
        counter.clear()
        files = self._run(client, analysis_dir, sources_dir, out)
        assert counter == []  # zero LLM calls
        assert len(files) == 2  # files still returned

    def test_force_bypasses_skip(self, analysis_dir, sources_dir, tmp_path):
        out = tmp_path / "out"
        counter: list[int] = []
        client = self._counting_client(counter)

        self._run(client, analysis_dir, sources_dir, out)
        first = len(counter)
        counter.clear()
        self._run(client, analysis_dir, sources_dir, out, force=True)
        assert len(counter) == first  # re-billed everything

    def test_sidecar_cache_skips_llm_across_output_dirs(self, analysis_dir, sources_dir, tmp_path):
        # First run populates the per-table sidecar under analysis_dir/.cache.
        counter: list[int] = []
        client = self._counting_client(counter)
        self._run(client, analysis_dir, sources_dir, tmp_path / "out1")
        assert len(counter) > 0

        # Second run to a FRESH output dir: domain-level skip cannot fire (no prior
        # alignment file), but the sidecar cache hits → zero LLM calls.
        counter.clear()
        self._run(client, analysis_dir, sources_dir, tmp_path / "out2")
        assert counter == []

    def test_changed_column_invalidates_sidecar(self, analysis_dir, sources_dir, tmp_path):
        counter: list[int] = []
        client = self._counting_client(counter)
        self._run(client, analysis_dir, sources_dir, tmp_path / "out1")
        assert len(counter) > 0

        # Mutate a source column so the per-table input hash changes.
        vocab = sources_dir / "adminpulse" / "adminpulse.vocabulary.ttl"
        text = vocab.read_text(encoding="utf-8").replace("ContractNo", "ContractNumber")
        vocab.write_text(text, encoding="utf-8")

        counter.clear()
        self._run(client, analysis_dir, sources_dir, tmp_path / "out2")
        # The commercial table changed → at least one fresh call (party may differ too).
        assert len(counter) >= 1

    def test_parallel_matches_serial(self, analysis_dir, sources_dir, tmp_path):
        serial_out = tmp_path / "serial"
        parallel_out = tmp_path / "parallel"
        self._run(
            self._counting_client([]), analysis_dir, sources_dir, serial_out,
            max_workers=1, force=True,
        )
        self._run(
            self._counting_client([]), analysis_dir, sources_dir, parallel_out,
            max_workers=4, force=True,
        )
        for name in ("commercial-alignment.yaml", "party-alignment.yaml"):
            s = yaml.safe_load((serial_out / name).read_text(encoding="utf-8"))
            p = yaml.safe_load((parallel_out / name).read_text(encoding="utf-8"))
            # generated_at differs; compare the table payloads only.
            assert [t["table"] for t in s["tables"]] == [t["table"] for t in p["tables"]]
            assert s["tables"] == p["tables"]


# placeholder-marker-for-append


# ---------------------------------------------------------------------------
# Tests: cross-module alignment (DD-070, issue #166)
# ---------------------------------------------------------------------------


PARTY_URI = "https://example.com/ont/party#"
SIBLING_URI = "https://example.com/ont/reference-data#"


def _home_classes():
    return [
        {"name": "TradeParty", "label": "Trade Party", "comment": "",
         "properties": [{"name": "partyName", "label": "Party Name", "range": "string"}]},
    ]


def _widened_classes():
    """Home TradeParty + a sibling/shared-module Address class (tagged)."""
    return [
        {"name": "TradeParty", "label": "Trade Party", "comment": "",
         "properties": [{"name": "partyName", "label": "Party Name", "range": "string"}],
         "source_uri": PARTY_URI, "module": "party",
         "ref_class_id": "party:TradeParty", "belongs_to_domains": ["party"]},
        {"name": "Address", "label": "Address", "comment": "A postal address",
         "properties": [
             {"name": "street", "label": "Street", "range": "string"},
             {"name": "postalCode", "label": "Postal Code", "range": "string"},
         ],
         "source_uri": SIBLING_URI, "module": "reference-data",
         "ref_class_id": "reference-data:Address",
         "belongs_to_domains": ["party", "commercial"]},
    ]


class TestModuleTag:
    def test_home_class_no_tag(self):
        assert _module_tag({"name": "TradeParty"}) == ""

    def test_sibling_class_tag(self):
        assert _module_tag({"name": "Address", "module": "reference-data"}) == (
            "  [module: reference-data]"
        )


class TestClassMetaIndex:
    def test_indexes_by_name_with_module_meta(self):
        index = _build_class_meta_index(_widened_classes())
        assert "Address" in index
        meta = index["Address"][0]
        assert meta["module"] == "reference-data"
        assert meta["is_home"] is False
        assert meta["belongs_to_domains"] == ["party", "commercial"]
        # TradeParty present from the home uri (is_home not set here → False)
        assert "TradeParty" in index

    def test_same_name_across_modules_kept_separate(self):
        classes = [
            {"name": "Address", "module": "party", "source_uri": PARTY_URI,
             "is_home": True, "belongs_to_domains": ["party"]},
            {"name": "Address", "module": "reference-data", "source_uri": SIBLING_URI,
             "is_home": False, "belongs_to_domains": ["commercial"]},
        ]
        index = _build_class_meta_index(classes)
        assert len(index["Address"]) == 2
        modules = {m["module"] for m in index["Address"]}
        assert modules == {"party", "reference-data"}


class TestResolveColumnModule:
    def test_sibling_match_returns_meta(self):
        index = _build_class_meta_index(_widened_classes())
        meta = _resolve_column_module("Address", "reference-data", index)
        assert meta is not None
        assert meta["module"] == "reference-data"

    def test_home_match_returns_none(self):
        classes = [
            {"name": "TradeParty", "module": "party", "source_uri": PARTY_URI,
             "is_home": True, "belongs_to_domains": ["party"]},
        ]
        index = _build_class_meta_index(classes)
        assert _resolve_column_module("TradeParty", "party", index) is None

    def test_unknown_class_returns_none(self):
        index = _build_class_meta_index(_widened_classes())
        assert _resolve_column_module("Nonexistent", "", index) is None

    def test_prefers_home_when_module_ambiguous(self):
        classes = [
            {"name": "Address", "module": "party", "source_uri": PARTY_URI,
             "is_home": True, "belongs_to_domains": ["party"]},
            {"name": "Address", "module": "reference-data", "source_uri": SIBLING_URI,
             "is_home": False, "belongs_to_domains": ["commercial"]},
        ]
        index = _build_class_meta_index(classes)
        # No explicit ref_module → prefers the home class → not a cross-module tag.
        assert _resolve_column_module("Address", "", index) is None


class TestSelectPropertyPool:
    def test_includes_home_shortlist_and_surfaces_sibling(self):
        widened = _widened_classes()
        for c in widened:
            c["is_home"] = c["source_uri"] == PARTY_URI
        home_shortlist = [widened[0]]  # TradeParty
        columns = [{"name": "SHIPPER_STREET", "data_type": "nvarchar", "samples": []}]
        pool = _select_property_pool(
            "tblParties", columns, widened, home_shortlist,
            indicative_columns=["SHIPPER_STREET"],
        )
        names = {c["name"] for c in pool}
        assert "TradeParty" in names  # home always included
        assert "Address" in names  # sibling surfaced by token overlap with 'street'

    def test_excludes_home_classes_from_cross_scoring(self):
        widened = _widened_classes()
        for c in widened:
            c["is_home"] = c["source_uri"] == PARTY_URI
        home_shortlist = [widened[0]]
        columns = [{"name": "PARTY_NAME", "data_type": "nvarchar", "samples": []}]
        pool = _select_property_pool(
            "tblParties", columns, widened, home_shortlist,
        )
        # No token overlap with Address → only the home shortlist is returned.
        assert {c["name"] for c in pool} == {"TradeParty"}


class TestBuildAlignmentPromptCrossModule:
    def test_default_prompt_has_no_cross_module_artifacts(self):
        prompt = build_alignment_prompt(
            "tblParties",
            [{"name": "SHIPPER_STREET", "data_type": "nvarchar", "samples": []}],
            _home_classes(),
        )
        assert "CROSS-MODULE" not in prompt
        assert "ref_module" not in prompt
        assert "[module:" not in prompt

    def test_cross_module_prompt_adds_sections(self):
        widened = _widened_classes()
        prompt = build_alignment_prompt(
            "tblParties",
            [{"name": "SHIPPER_STREET", "data_type": "nvarchar", "samples": []}],
            widened,
            table_ref_classes=_home_classes(),
        )
        assert "CROSS-MODULE" in prompt
        assert "ref_module" in prompt
        assert "[module: reference-data]" in prompt
        # STEP 1 candidate list is home-only.
        assert "Must be one of: TradeParty" in prompt


class TestAlignTableCrossModule:
    def _client(self, payload):
        client = mock.MagicMock()
        client.chat.completions.create.return_value = mock.MagicMock(
            choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
        )
        return client

    def test_captures_ref_module_when_present(self):
        payload = {
            "ref_class": "TradeParty", "ref_class_confidence": 0.9,
            "column_alignments": [
                {"column": "SHIPPER_STREET", "ref_class": "Address",
                 "ref_module": "reference-data", "ref_property": "street",
                 "alignment": "semantic", "confidence": 0.8, "rationale": "street"},
            ],
        }
        client = self._client(payload)
        result = align_table(
            client, "gpt", "tblParties",
            [{"name": "SHIPPER_STREET", "data_type": "nvarchar"}],
            _widened_classes(),
            table_ref_classes=_home_classes(),
        )
        assert result["ref_class"] == "TradeParty"  # validated against home pool
        assert result["column_alignments"][0]["ref_module"] == "reference-data"

    def test_default_mode_omits_ref_module(self):
        payload = {
            "ref_class": "TradeParty", "ref_class_confidence": 0.9,
            "column_alignments": [
                {"column": "PartyName", "ref_class": "TradeParty",
                 "ref_property": "partyName", "alignment": "exact",
                 "confidence": 0.95, "rationale": "match"},
            ],
        }
        client = self._client(payload)
        result = align_table(
            client, "gpt", "tblParties",
            [{"name": "PartyName", "data_type": "nvarchar"}],
            _home_classes(),
        )
        assert "ref_module" not in result["column_alignments"][0]


class TestWriteAlignmentOutputCrossModule:
    def test_emits_cross_module_fields(self, tmp_path):
        ca = ColumnAlignment(
            column="SHIPPER_STREET", data_type="nvarchar", ref_class="Address",
            ref_property="street", alignment="semantic", confidence=0.8,
            ref_module="reference-data", ref_module_uri=SIBLING_URI,
            belongs_to_domains=["party", "commercial"],
        )
        ta = TableAlignment(system="adminpulse", table="tblParties",
                            ref_class="TradeParty", ref_class_confidence=0.9,
                            columns=[ca])
        alignment = DomainAlignment(
            domain="party", domain_uris=[PARTY_URI],
            generated_at="2026-01-01T00:00:00Z", model_used="gpt",
            tables=[ta], affinity_sha256="abc",
            alignment_params_sha256="deadbeef",
            cross_module_matches=[{
                "ref_class": "Address", "ref_module": "reference-data",
                "ref_module_uri": SIBLING_URI,
                "belongs_to_domains": ["party", "commercial"],
                "source_columns": ["adminpulse.tblParties.SHIPPER_STREET"],
            }],
        )
        out = write_alignment_output(alignment, tmp_path)
        data = yaml.safe_load(out.read_text(encoding="utf-8"))
        col = data["tables"][0]["columns"][0]
        assert col["ref_module"] == "reference-data"
        assert col["belongs_to_domains"] == ["party", "commercial"]
        assert data["alignment_params_sha256"] == "deadbeef"
        assert len(data["cross_module_matches"]) == 1

    def test_default_omits_cross_module_fields(self, tmp_path):
        ca = ColumnAlignment(
            column="PartyName", data_type="nvarchar", ref_class="TradeParty",
            ref_property="partyName", alignment="exact", confidence=0.95,
        )
        ta = TableAlignment(system="adminpulse", table="tblParties",
                            ref_class="TradeParty", ref_class_confidence=0.9,
                            columns=[ca])
        alignment = DomainAlignment(
            domain="party", domain_uris=[PARTY_URI],
            generated_at="2026-01-01T00:00:00Z", model_used="gpt",
            tables=[ta], affinity_sha256="abc",
        )
        out = write_alignment_output(alignment, tmp_path)
        data = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert "ref_module" not in data["tables"][0]["columns"][0]
        assert "alignment_params_sha256" not in data
        assert "cross_module_matches" not in data


@pytest.fixture
def party_sources(tmp_path):
    sources = tmp_path / "sources" / "adminpulse"
    sources.mkdir(parents=True)
    vocab = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
<#tblParties> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblParties" .
<#tblParties_SHIPPER_STREET> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "SHIPPER_STREET" ;
    kairos-bronze:dataType "nvarchar(100)" ;
    kairos-bronze:belongsToTable <#tblParties> .
"""
    (sources / "adminpulse.vocabulary.ttl").write_text(vocab, encoding="utf-8")
    return tmp_path / "sources"


class TestRunProposeAlignmentCrossModule:
    def _inventory_side_effect(self, domain_uris, catalog_path, *,
                               inventory_dir=None, module_map=None):
        if module_map is None:
            return _home_classes()
        return _widened_classes()

    def _client(self, calls=None):
        def create_completion(**kwargs):
            if calls is not None:
                calls.append(kwargs["messages"][1]["content"])
            payload = {
                "ref_class": "TradeParty", "ref_class_confidence": 0.9,
                "column_alignments": [
                    {"column": "SHIPPER_STREET", "ref_class": "Address",
                     "ref_module": "reference-data", "ref_property": "street",
                     "alignment": "semantic", "confidence": 0.8,
                     "rationale": "street part"},
                ],
            }
            return mock.MagicMock(
                choices=[mock.MagicMock(
                    message=mock.MagicMock(content=json.dumps(payload)))]
            )
        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        return client

    def _run(self, analysis_dir, party_sources, output, calls=None, **kw):
        with mock.patch(
            "kairos_ontology.propose_alignment.get_ai_client",
            return_value=self._client(calls),
        ), mock.patch(
            "kairos_ontology.propose_alignment.extract_ref_model_inventory",
            side_effect=self._inventory_side_effect,
        ), mock.patch(
            "kairos_ontology.analyse_sources.load_accelerator_uri_modules",
            return_value={
                PARTY_URI: {"module": "party", "domains": ["party"]},
                SIBLING_URI: {"module": "reference-data",
                              "domains": ["party", "commercial"]},
            },
        ):
            return run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=party_sources,
                catalog_path=None,
                output_dir=output,
                domains_filter=["party"],
                **kw,
            )

    def test_column_matches_sibling_module(self, analysis_dir, party_sources, tmp_path):
        out = tmp_path / "out"
        self._run(analysis_dir, party_sources, out,
                  cross_module=True, accelerator="logistics",
                  ref_models_dir=tmp_path)
        data = yaml.safe_load((out / "party-alignment.yaml").read_text("utf-8"))
        # Table still classifies to the HOME class.
        assert data["tables"][0]["ref_class"] == "TradeParty"
        col = data["tables"][0]["columns"][0]
        assert col["ref_class"] == "Address"
        assert col["ref_module"] == "reference-data"
        assert col["belongs_to_domains"] == ["party", "commercial"]
        # Separate cross-module section populated; params hash present.
        assert data["alignment_params_sha256"]
        matches = data["cross_module_matches"]
        assert len(matches) == 1
        assert matches[0]["ref_class"] == "Address"
        assert matches[0]["source_columns"] == [
            "adminpulse.tblParties.SHIPPER_STREET"
        ]

    def test_full_inventory_retry_disabled(self, analysis_dir, party_sources, tmp_path):
        calls: list[str] = []
        self._run(analysis_dir, party_sources, tmp_path / "out", calls=calls,
                  cross_module=True, accelerator="logistics",
                  ref_models_dir=tmp_path, max_prompt_classes=1)
        # Exactly one LLM call for the single party table — no full-inventory retry.
        assert len(calls) == 1

    def test_cross_module_not_skipped_after_home_only_run(
        self, analysis_dir, party_sources, tmp_path
    ):
        out = tmp_path / "out"
        # First: a default (home-only) run → no params hash recorded.
        self._run(analysis_dir, party_sources, out)
        first = yaml.safe_load((out / "party-alignment.yaml").read_text("utf-8"))
        assert "cross_module_matches" not in first
        # Then: a cross-module run with the same affinity must NOT be skipped.
        self._run(analysis_dir, party_sources, out,
                  cross_module=True, accelerator="logistics",
                  ref_models_dir=tmp_path)
        second = yaml.safe_load((out / "party-alignment.yaml").read_text("utf-8"))
        assert "cross_module_matches" in second

    def test_requires_accelerator(self, analysis_dir, party_sources, tmp_path):
        with pytest.raises(ValueError, match="requires an accelerator"):
            run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=party_sources,
                catalog_path=None,
                output_dir=tmp_path / "out",
                domains_filter=["party"],
                cross_module=True,
            )


# ---------------------------------------------------------------------------
# Tests: DD-075 sample-grounded mapping evidence
# ---------------------------------------------------------------------------


class TestParsesAs:
    def test_int(self):
        assert _parses_as("42", "int")
        assert _parses_as("-7", "int")
        assert not _parses_as("12.5", "int")
        assert not _parses_as("N/A", "int")

    def test_decimal(self):
        assert _parses_as("12.5", "decimal")
        assert _parses_as("3", "decimal")
        assert not _parses_as("abc", "decimal")

    def test_bool(self):
        assert _parses_as("true", "bool")
        assert _parses_as("0", "bool")
        assert not _parses_as("maybe", "bool")

    def test_empty_is_compatible(self):
        assert _parses_as("", "int")
        assert _parses_as("   ", "int")

    def test_non_checked_types_pass(self):
        # Dates/strings are not second-guessed from samples.
        assert _parses_as("not-a-date", "date")
        assert _parses_as("anything", "string")


class TestTransformCompatNote:
    def test_flags_non_numeric(self):
        note = _transform_compat_note(
            {"samples": ["12", "N/A", "34"]}, "integer"
        )
        assert note is not None
        assert "1/3" in note and "non-numeric" in note

    def test_clean_numeric_no_note(self):
        assert _transform_compat_note({"samples": ["1", "2", "3"]}, "integer") is None

    def test_no_samples_no_note(self):
        assert _transform_compat_note({"samples": []}, "integer") is None

    def test_string_target_ignored(self):
        assert _transform_compat_note({"samples": ["x", "y"]}, "string") is None


class TestSampleEvidenceEmission:
    def test_example_and_compat_emitted_only_when_set(self, tmp_path):
        alignment = DomainAlignment(
            domain="party",
            domain_uris=["https://example.com/ont/party#"],
            generated_at="2026-06-05T10:00:00Z",
            model_used="gpt-5.4-mini",
            tables=[
                TableAlignment(
                    system="admin", table="tblParties",
                    ref_class="TradeParty", ref_class_confidence=0.9,
                    columns=[
                        ColumnAlignment(
                            column="PartyName", data_type="nvarchar(100)",
                            ref_class="TradeParty", ref_property="partyName",
                            alignment="exact", confidence=0.95,
                            example_values=["Acme NV", "Globex"],
                        ),
                        ColumnAlignment(
                            column="Code", data_type="int",
                            ref_class="TradeParty", ref_property="partyName",
                            alignment="semantic", confidence=0.5,
                            transform_compat="1/3 sample values are non-numeric — "
                                              "CAST may NULL/fail; confirm",
                        ),
                        ColumnAlignment(
                            column="Bare", data_type="int",
                            ref_class="TradeParty", ref_property="partyName",
                            alignment="semantic", confidence=0.5,
                        ),
                    ],
                ),
            ],
        )
        out_path = write_alignment_output(alignment, tmp_path)
        data = yaml.safe_load(out_path.read_text("utf-8"))
        assert data["schema_version"] == 2  # NOT bumped
        cols = data["tables"][0]["columns"]
        named, coded, bare = cols
        assert named["example_values"] == ["Acme NV", "Globex"]
        assert "transform_compat" not in named
        assert "non-numeric" in coded["transform_compat"]
        assert "example_values" not in bare
        assert "transform_compat" not in bare


class TestSampleEvidenceIntegration:
    """End-to-end: example_values are produced by default and PII is masked."""

    def _vocab_with_samples(self, tmp_path):
        sources = tmp_path / "sources"
        admin = sources / "adminpulse"
        admin.mkdir(parents=True)
        vocab = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .

<#tblParties> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblParties" .

<#tblParties_PartyName> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "PartyName" ;
    kairos-bronze:dataType "nvarchar(100)" ;
    kairos-bronze:sampleValues "Acme NV | Globex Corp" ;
    kairos-bronze:belongsToTable <#tblParties> .

<#tblParties_Email> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Email" ;
    kairos-bronze:dataType "nvarchar(200)" ;
    kairos-bronze:sampleValues "jane.doe@acme.com | bob@globex.com" ;
    kairos-bronze:belongsToTable <#tblParties> .
"""
        (admin / "adminpulse.vocabulary.ttl").write_text(vocab, encoding="utf-8")
        return sources

    def _responses(self):
        return {
            "tblParties": {
                "ref_class": "TradeParty", "ref_class_confidence": 0.9,
                "column_alignments": [
                    {"column": "PartyName", "ref_class": "TradeParty",
                     "ref_property": "partyName", "alignment": "exact",
                     "confidence": 0.95, "rationale": "name"},
                    {"column": "Email", "ref_class": "TradeParty",
                     "ref_property": "contactEmail", "alignment": "semantic",
                     "confidence": 0.8, "rationale": "email"},
                ],
            },
        }

    def _run(self, analysis_dir, sources, output, **kw):
        client = TestRunProposeAlignment()._mock_client(self._responses())
        with mock.patch(
            "kairos_ontology.propose_alignment.get_ai_client", return_value=client
        ), mock.patch(
            "kairos_ontology.propose_alignment.extract_ref_model_inventory",
            return_value=[
                {"name": "TradeParty", "label": "Trade Party", "comment": "",
                 "properties": [
                     {"name": "partyName", "label": "Party Name", "range": "string"},
                     {"name": "contactEmail", "label": "Contact Email", "range": "string"},
                 ]},
            ],
        ):
            return run_propose_alignment(
                analysis_dir=analysis_dir, sources_dir=sources,
                catalog_path=None, output_dir=output,
                domains_filter=["party"], **kw,
            )

    def test_examples_on_by_default_pii_masked(self, analysis_dir, tmp_path):
        sources = self._vocab_with_samples(tmp_path)
        out = tmp_path / "out"
        self._run(analysis_dir, sources, out)
        data = yaml.safe_load((out / "party-alignment.yaml").read_text("utf-8"))
        cols = {c["column"]: c for c in data["tables"][0]["columns"]}
        # Non-PII column shows raw values by default.
        assert cols["PartyName"]["example_values"] == ["Acme NV", "Globex Corp"]
        # PII (email) column is masked — raw address must never appear.
        email_examples = cols["Email"]["example_values"]
        assert all("@" in v and "***" in v for v in email_examples)
        raw = (out / "party-alignment.yaml").read_text("utf-8")
        assert "jane.doe@acme.com" not in raw
        assert "bob@globex.com" not in raw

    def test_no_sample_values_suppresses(self, analysis_dir, tmp_path):
        sources = self._vocab_with_samples(tmp_path)
        out = tmp_path / "out"
        self._run(analysis_dir, sources, out, include_sample_values=False)
        data = yaml.safe_load((out / "party-alignment.yaml").read_text("utf-8"))
        for c in data["tables"][0]["columns"]:
            assert "example_values" not in c


