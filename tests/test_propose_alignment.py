# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for propose_alignment module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
import yaml

from kairos_ontology.core.propose_alignment import (
    ColumnAlignment,
    DomainAlignment,
    TableAlignment,
    OUTCOME_FALLBACK_ONLY,
    OUTCOME_PROVIDER_FAILURE,
    OUTCOME_SEMANTIC_SUCCESS,
    _build_class_meta_index,
    _build_custom_column,
    _build_object_property_candidate,
    _build_object_property_passthrough,
    _build_property_label_index,
    _build_reconciled_passthrough,
    _build_reference_rollup,
    _cluster_object_property_candidates,
    _detect_address_relationship_candidates,
    _downgrade_catch_all_suggestions,
    _has_typed_role_evidence,
    _is_location_object_property,
    _is_technical_actor_column,
    _location_role_token,
    _looks_like_identifier_column,
    _object_relationship_downgrade_reason,
    _clamp_confidence,
    _compact_prompt_samples,
    _detect_address_part,
    _format_source_columns,
    _module_tag,
    _normalize_property_token,
    _parses_as,
    _relationship_cluster_id,
    _resolve_column_module,
    _resolve_object_property_target,
    _review_column_alignment,
    _select_property_pool,
    _select_ref_classes_for_table,
    _should_retry_with_full_inventory,
    _source_column_digest,
    _transform_compat_note,
    align_table,
    alignment_to_dict,
    build_alignment_prompt,
    build_domain_alignments,
    load_affinity_reports,
    run_propose_alignment,
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
        assert result["commercial"][0]["domain_uris"] == ["https://example.com/ont/commercial#"]


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

    def test_ws7_prompt_forbids_invented_property_names(self, sample_ref_classes):
        # WS7 (issue #182): the prompt must instruct null ref_property for unmatched
        # columns and explicitly forbid catch-all sinks — the root cause of garbage
        # suggestions like stageCode/customsID.
        columns = [{"name": "X", "data_type": "string"}]
        prompt = build_alignment_prompt("tbl", columns, sample_ref_classes)
        assert "ref_property to null" in prompt
        assert "stageCode" in prompt  # named as a forbidden catch-all example
        assert "null if alignment is custom" in prompt

    def test_ws7_prompt_allows_null_ref_class(self, sample_ref_classes):
        columns = [{"name": "X", "data_type": "string"}]
        prompt = build_alignment_prompt("tbl", columns, sample_ref_classes)
        assert "set ref_class to null" in prompt


# ---------------------------------------------------------------------------
# Tests: align_table
# ---------------------------------------------------------------------------


class TestAlignTable:
    def _mock_client(self, response_dict):
        client = mock.MagicMock()
        client.chat.completions.create.return_value = mock.MagicMock(
            choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(response_dict)))]
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
        result = align_table(client, "gpt-5.4-mini", "tblContracts", columns, sample_ref_classes)

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

    def test_anchor_status_matched(self, sample_ref_classes):
        response = {
            "ref_class": "SalesContract",
            "ref_class_confidence": 0.9,
            "column_alignments": [],
        }
        client = self._mock_client(response)
        result = align_table(
            client, "gpt-5.4-mini", "t", [{"name": "X", "data_type": "string"}], sample_ref_classes
        )
        assert result["ref_class_status"] == "matched"
        assert result["rejected_ref_class"] is None

    def test_anchor_status_rejected_when_no_fallback(self, sample_ref_classes):
        # WS6 (issue #182): a hallucinated class with no valid affinity fallback is
        # reported as rejected (unanchored), not silently blanked.
        response = {"ref_class": "Booking", "ref_class_confidence": 0.9, "column_alignments": []}
        client = self._mock_client(response)
        result = align_table(
            client, "gpt-5.4-mini", "t", [{"name": "X", "data_type": "string"}], sample_ref_classes
        )
        assert result["ref_class"] == ""
        assert result["ref_class_status"] == "rejected"
        assert result["rejected_ref_class"] == "Booking"

    def test_anchor_status_fallback_to_affinity_entity(self, sample_ref_classes):
        response = {"ref_class": "Booking", "ref_class_confidence": 0.9, "column_alignments": []}
        client = self._mock_client(response)
        result = align_table(
            client,
            "gpt-5.4-mini",
            "t",
            [{"name": "X", "data_type": "string"}],
            sample_ref_classes,
            likely_entity="SalesContract",
        )
        assert result["ref_class"] == "SalesContract"
        assert result["ref_class_status"] == "fallback"
        assert result["rejected_ref_class"] == "Booking"

    def test_anchor_status_unmatched_when_empty(self, sample_ref_classes):
        response = {"ref_class": "", "ref_class_confidence": 0.0, "column_alignments": []}
        client = self._mock_client(response)
        result = align_table(
            client, "gpt-5.4-mini", "t", [{"name": "X", "data_type": "string"}], sample_ref_classes
        )
        assert result["ref_class_status"] == "unmatched"

    def test_anchor_override_wins_over_model_class_pick(self, sample_ref_classes):
        # uri-anchor-contract: a confirmed anchor always wins, even when the
        # model proposes a different, otherwise-valid class.
        response = {"ref_class": "TradeTerms", "ref_class_confidence": 0.6, "column_alignments": []}
        client = self._mock_client(response)
        result = align_table(
            client,
            "gpt-5.4-mini",
            "t",
            [{"name": "X", "data_type": "string"}],
            sample_ref_classes,
            anchor_override="SalesContract",
        )
        assert result["ref_class"] == "SalesContract"
        assert result["ref_class_status"] == "confirmed"
        assert result["ref_class_confidence"] == 1.0
        assert result["rejected_ref_class"] is None

    def test_anchor_override_wins_even_when_model_returns_no_class(self, sample_ref_classes):
        response = {"ref_class": "", "ref_class_confidence": 0.0, "column_alignments": []}
        client = self._mock_client(response)
        result = align_table(
            client,
            "gpt-5.4-mini",
            "t",
            [{"name": "X", "data_type": "string"}],
            sample_ref_classes,
            anchor_override="SalesContract",
        )
        assert result["ref_class"] == "SalesContract"
        assert result["ref_class_status"] == "confirmed"

    def test_anchor_override_becomes_column_default_ref_class(self, sample_ref_classes):
        response = {
            "ref_class": "TradeTerms",
            "ref_class_confidence": 0.5,
            "column_alignments": [
                {
                    "column": "X",
                    "ref_property": "contractIdentifier",
                    "alignment": "semantic",
                    "confidence": 0.8,
                },
            ],
        }
        client = self._mock_client(response)
        result = align_table(
            client,
            "gpt-5.4-mini",
            "t",
            [{"name": "X", "data_type": "string"}],
            sample_ref_classes,
            anchor_override="SalesContract",
        )
        # The column had no explicit ref_class of its own, so it inherits the
        # *overridden* (confirmed) class, not the model's own pick.
        assert result["column_alignments"][0]["ref_class"] == "SalesContract"

    def test_no_anchor_override_keeps_existing_behavior(self, sample_ref_classes):
        response = {
            "ref_class": "SalesContract",
            "ref_class_confidence": 0.95,
            "column_alignments": [],
        }
        client = self._mock_client(response)
        result = align_table(
            client, "gpt-5.4-mini", "t", [{"name": "X", "data_type": "string"}], sample_ref_classes
        )
        assert result["ref_class_status"] == "matched"

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
        # Alignment-reliability: no LLM call was made (no ref classes to align
        # against) — this is fallback_only, distinct from an actual failure.
        assert result["generation_outcome"] == OUTCOME_FALLBACK_ONLY
        client.chat.completions.create.assert_not_called()

    def test_llm_failure_returns_empty(self, sample_ref_classes):
        client = mock.MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("API down")
        columns = [{"name": "X", "data_type": "string"}]
        result = align_table(client, "gpt-5.4-mini", "tbl", columns, sample_ref_classes)
        assert result["ref_class"] == ""
        assert result["column_alignments"] == []
        # Alignment-reliability: a real LLM call was attempted and failed — typed
        # as provider_failure (not the same as a genuine "no match" result), with
        # a safe (sanitized) error message attached.
        assert result["generation_outcome"] == OUTCOME_PROVIDER_FAILURE
        assert "API down" in result["generation_error"]

    def test_successful_call_is_semantic_success(self, sample_ref_classes):
        response = {
            "ref_class": "SalesContract",
            "ref_class_confidence": 0.9,
            "column_alignments": [],
        }
        client = self._mock_client(response)
        result = align_table(
            client, "gpt-5.4-mini", "t", [{"name": "X", "data_type": "string"}], sample_ref_classes
        )
        assert result["generation_outcome"] == OUTCOME_SEMANTIC_SUCCESS
        assert result.get("generation_error") is None


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
# Tests: alignment_to_dict (the pure transformation feeding the Claim Registry)
# ---------------------------------------------------------------------------


class TestAlignmentToDict:
    def test_builds_dict(self, tmp_path):
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
                        {
                            "column": "InternalCode",
                            "data_type": "nvarchar(20)",
                            "suggested_property": "internalCode",
                            "rationale": "No match",
                        },
                    ],
                ),
            ],
        )

        data = alignment_to_dict(alignment)

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
        data = alignment_to_dict(alignment)
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
        [
            "SHIPPER_STREET",
            "billing_zip",
            "postal_code",
            "address_line_1",
            "house_number",
            "consignee_city",
        ],
    )
    def test_detects_strong_address_parts(self, name):
        assert _detect_address_part(name) is True

    @pytest.mark.parametrize(
        "name",
        ["country", "city", "clearingHouse", "warehouse", "countryOfBirth", "PartyName", ""],
    )
    def test_ignores_ambiguous_or_non_address(self, name):
        assert _detect_address_part(name) is False


class TestReviewColumnAlignment:
    @pytest.fixture
    def label_index(self):
        ref_classes = [
            {
                "name": "TradeParty",
                "properties": [
                    {"name": "partyName", "label": "Party Name", "range": "string"},
                    {"name": "partyIdentifier", "label": "Party Identifier", "range": "string"},
                    {"name": "isActive", "label": "Is Active", "range": "boolean"},
                    {"name": "address", "label": "Address", "range": "Address"},
                ],
            },
        ]
        return _build_property_label_index(ref_classes)

    def test_address_part_to_non_address_scalar_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="SHIPPER_STREET",
            data_type="nvarchar(100)",
            ref_class="TradeParty",
            ref_property="partyName",
            confidence=0.5,
            label_index=label_index,
        )
        assert reason and "address-part" in reason

    def test_address_part_to_address_property_not_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="SHIPPER_STREET",
            data_type="nvarchar(100)",
            ref_class="TradeParty",
            ref_property="address",
            confidence=0.5,
            label_index=label_index,
        )
        assert reason is None

    def test_boolean_to_identity_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="FCPAYABLEIND",
            data_type="bit",
            ref_class="TradeParty",
            ref_property="partyIdentifier",
            confidence=0.5,
            label_index=label_index,
        )
        assert reason and "boolean" in reason

    def test_financial_to_identity_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="IBAN",
            data_type="varchar(34)",
            ref_class="TradeParty",
            ref_property="partyIdentifier",
            confidence=0.9,
            label_index=label_index,
        )
        assert reason and "financial" in reason

    def test_no_token_overlap_low_confidence_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="XYZ123",
            data_type="nvarchar(50)",
            ref_class="TradeParty",
            ref_property="partyName",
            confidence=0.3,
            label_index=label_index,
        )
        assert reason and "share no name token" in reason

    def test_numeric_id_to_identifier_not_flagged(self, label_index):
        """ClientID int → partyIdentifier must not be noise (token overlap)."""
        reason = _review_column_alignment(
            column_name="PartyIdentifier",
            data_type="int",
            ref_class="TradeParty",
            ref_property="partyIdentifier",
            confidence=0.4,
            label_index=label_index,
        )
        assert reason is None

    def test_good_name_match_not_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="PartyName",
            data_type="nvarchar(100)",
            ref_class="TradeParty",
            ref_property="partyName",
            confidence=0.95,
            label_index=label_index,
        )
        assert reason is None

    def test_empty_property_not_flagged(self, label_index):
        reason = _review_column_alignment(
            column_name="anything",
            data_type="int",
            ref_class="TradeParty",
            ref_property="",
            confidence=0.1,
            label_index=label_index,
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

    def test_hallucinated_property_not_counted(self, sample_ref_classes):
        # WS4 (issue #182): a property not on the class must not count as matched,
        # must not inflate coverage past 100%, and must be surfaced.
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
                        ColumnAlignment(
                            column="Bogus",
                            data_type="nvarchar(50)",
                            ref_class="SalesContract",
                            ref_property="notARealProperty",
                            alignment="semantic",
                            confidence=0.8,
                        ),
                    ],
                ),
            ],
        )
        rollup = _build_reference_rollup(alignment, sample_ref_classes)
        sc = next(r for r in rollup if r["ref_class"] == "SalesContract")
        assert sc["matched_properties"] == 1
        assert sc["coverage_pct"] <= 100.0
        assert sc["hallucinated_properties_count"] == 1
        assert "notARealProperty" in sc["hallucinated_properties"]

    def test_coverage_never_exceeds_100(self, sample_ref_classes):
        # Over-mapping a 3-property class with 5 distinct ref_property values must
        # still cap coverage at the 3 real ones (issue #182 121% bug).
        cols = [
            ColumnAlignment(
                column=f"C{i}",
                data_type="string",
                ref_class="SalesContract",
                ref_property=name,
                alignment="semantic",
                confidence=0.9,
            )
            for i, name in enumerate(
                [
                    "contractIdentifier",
                    "effectiveDate",
                    "contractType",
                    "ghost1",
                    "ghost2",
                ]
            )
        ]
        alignment = DomainAlignment(
            domain="commercial",
            domain_uris=[],
            generated_at="",
            model_used="",
            tables=[
                TableAlignment(
                    system="s",
                    table="t",
                    ref_class="SalesContract",
                    ref_class_confidence=0.9,
                    columns=cols,
                )
            ],
        )
        rollup = _build_reference_rollup(alignment, sample_ref_classes)
        sc = next(r for r in rollup if r["ref_class"] == "SalesContract")
        assert sc["matched_properties"] == 3
        assert sc["coverage_pct"] == 100.0
        assert sc["hallucinated_properties_count"] == 2

    def test_no_hallucination_fields_when_clean(self, sample_ref_classes):
        alignment = DomainAlignment(
            domain="commercial",
            domain_uris=[],
            generated_at="",
            model_used="",
            tables=[
                TableAlignment(
                    system="s",
                    table="t",
                    ref_class="SalesContract",
                    ref_class_confidence=0.9,
                    columns=[
                        ColumnAlignment(
                            column="C",
                            data_type="string",
                            ref_class="SalesContract",
                            ref_property="contractIdentifier",
                            alignment="semantic",
                            confidence=0.9,
                        )
                    ],
                )
            ],
        )
        rollup = _build_reference_rollup(alignment, sample_ref_classes)
        sc = next(r for r in rollup if r["ref_class"] == "SalesContract")
        assert "hallucinated_properties_count" not in sc
        assert "hallucinated_properties" not in sc


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
                        choices=[
                            mock.MagicMock(message=mock.MagicMock(content=json.dumps(response)))
                        ]
                    )
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps({})))]
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
                    {
                        "column": "ContractNo",
                        "ref_class": "SalesContract",
                        "ref_property": "contractIdentifier",
                        "alignment": "semantic",
                        "confidence": 0.92,
                        "rationale": "Contract ID",
                    },
                    {
                        "column": "ValidFrom",
                        "ref_class": "SalesContract",
                        "ref_property": "effectiveDate",
                        "alignment": "semantic",
                        "confidence": 0.85,
                        "rationale": "Start date",
                    },
                    {
                        "column": "InternalCode",
                        "ref_property": "internalCode",
                        "alignment": "custom",
                        "confidence": 0.0,
                        "rationale": "No match",
                    },
                ],
            },
            "tblParties": {
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.88,
                "column_alignments": [
                    {
                        "column": "PartyName",
                        "ref_class": "TradeParty",
                        "ref_property": "partyName",
                        "alignment": "exact",
                        "confidence": 0.95,
                        "rationale": "Direct match",
                    },
                ],
            },
        }
        client = self._mock_client(responses)

        with (
            mock.patch("kairos_ontology.core.propose_alignment.get_ai_client", return_value=client),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=[
                    {
                        "name": "SalesContract",
                        "label": "Sales Contract",
                        "comment": "",
                        "properties": [
                            {
                                "name": "contractIdentifier",
                                "label": "Contract ID",
                                "range": "string",
                            },
                            {
                                "name": "effectiveDate",
                                "label": "Effective Date",
                                "range": "dateTime",
                            },
                        ],
                    },
                ],
            ),
        ):
            alignments = build_domain_alignments(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
            )

        assert len(alignments) == 2  # commercial + party
        domains = {a.domain for a in alignments}
        assert domains == {"commercial", "party"}

        # Verify commercial alignment content (rich transformation surface)
        commercial = next(a for a in alignments if a.domain == "commercial")
        data = alignment_to_dict(commercial)
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
        # Issue #164: custom columns carry a null disposition awaiting triage.
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
                    {
                        "column": "SHIPPER_STREET",
                        "ref_class": "TradeParty",
                        "ref_property": "partyName",
                        "alignment": "semantic",
                        "confidence": 0.5,
                        "rationale": "Best available",
                    },
                ],
            },
        }
        client = self._mock_client(responses)
        with (
            mock.patch("kairos_ontology.core.propose_alignment.get_ai_client", return_value=client),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=[
                    {
                        "name": "TradeParty",
                        "label": "Trade Party",
                        "comment": "",
                        "properties": [
                            {"name": "partyName", "label": "Party Name", "range": "string"},
                        ],
                    },
                ],
            ),
        ):
            alignments = build_domain_alignments(
                analysis_dir=analysis_dir,
                sources_dir=tmp_path / "sources",
                catalog_path=None,
                domains_filter=["party"],
            )

        data = alignment_to_dict(alignments[0])
        col = data["tables"][0]["columns"][0]
        assert col["column"] == "SHIPPER_STREET"
        assert col["review"] is True
        assert "address-part" in col["review_reason"]

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

    def test_retries_with_full_inventory_on_weak_shortlist(
        self, analysis_dir, sources_dir, tmp_path
    ):
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
                "properties": [
                    {"name": "contractIdentifier", "label": "Contract ID", "range": "string"}
                ],
            },
            {
                "name": "TradeTerms",
                "label": "Trade Terms",
                "comment": "",
                "properties": [{"name": "incoterm", "label": "Incoterm", "range": "string"}],
            },
        ]

        with (
            mock.patch("kairos_ontology.core.propose_alignment.get_ai_client", return_value=client),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=ref_classes,
            ),
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
        {
            "name": "SalesContract",
            "label": "Sales Contract",
            "comment": "",
            "properties": [
                {"name": "contractIdentifier", "label": "Contract ID", "range": "string"},
            ],
        },
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
                    {
                        "column": "ContractNo",
                        "ref_class": ref_class,
                        "ref_property": "contractIdentifier",
                        "alignment": "semantic",
                        "confidence": 0.9,
                        "rationale": "id",
                    },
                ],
            }
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
            )

        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        return client

    def _run(self, client, analysis_dir, sources_dir, output_dir, **kw):
        with (
            mock.patch("kairos_ontology.core.propose_alignment.get_ai_client", return_value=client),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=self.REF_CLASSES,
            ),
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


class TestAlignmentReliability:
    """Alignment-reliability: typed generation outcomes, total/partial failure,
    fallback-only gating, and no-cache-on-failure for the run-level pipeline."""

    REF_CLASSES = [
        {
            "name": "SalesContract",
            "label": "Sales Contract",
            "comment": "",
            "properties": [
                {"name": "contractIdentifier", "label": "Contract ID", "range": "string"},
            ],
        },
    ]

    def _failing_client(self):
        client = mock.MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("provider outage")
        return client

    def _success_client(self):
        def create_completion(**kwargs):
            prompt = kwargs["messages"][1]["content"]
            ref_class = "SalesContract" if "tblContracts" in prompt else "TradeParty"
            payload = {
                "ref_class": ref_class,
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {
                        "column": "ContractNo",
                        "ref_class": ref_class,
                        "ref_property": "contractIdentifier",
                        "alignment": "semantic",
                        "confidence": 0.9,
                        "rationale": "id",
                    },
                ],
            }
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
            )

        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        return client

    def _partial_failure_client(self):
        """Succeeds for tblContracts (commercial), fails for tblParties (party)."""

        def create_completion(**kwargs):
            prompt = kwargs["messages"][1]["content"]
            if "tblParties" in prompt:
                raise RuntimeError("provider outage")
            payload = {
                "ref_class": "SalesContract",
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {
                        "column": "ContractNo",
                        "ref_class": "SalesContract",
                        "ref_property": "contractIdentifier",
                        "alignment": "semantic",
                        "confidence": 0.9,
                        "rationale": "id",
                    },
                ],
            }
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
            )

        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        return client

    def test_generation_stats_populated(self, analysis_dir, sources_dir, tmp_path):
        from kairos_ontology.core.propose_alignment import _propose_alignments

        stats: dict[str, int] = {}
        with (
            mock.patch(
                "kairos_ontology.core.propose_alignment.get_ai_client",
                return_value=self._success_client(),
            ),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=self.REF_CLASSES,
            ),
        ):
            _propose_alignments(
                analysis_dir,
                sources_dir,
                None,
                tmp_path / "out",
                generation_stats=stats,
            )
        assert stats == {"attempted": 2, "semantic_success": 2, "provider_failure": 0}


class TestUriAnchorContractIntegration:
    """uri-anchor-contract end-to-end: confirmed anchors override the model's own
    class pick, ambiguous confirmed anchors never silently pick the nearest
    class (zero property claims + a separate unresolved_anchors record), and
    a human 'resolved' decision on that record is honored on the next run."""

    REF_CLASSES = [
        {
            "name": "SalesContract",
            "label": "Sales Contract",
            "comment": "",
            "uri": "https://example.com/ont/commercial#SalesContract",
            "properties": [
                {"name": "contractIdentifier", "label": "Contract ID", "range": "string"},
            ],
        },
        {
            "name": "TradeTerms",
            "label": "Trade Terms",
            "comment": "",
            "uri": "https://example.com/ont/commercial#TradeTerms",
            "properties": [
                {"name": "incoterm", "label": "Incoterm", "range": "string"},
            ],
        },
    ]

    def _model_prefers_trade_terms_client(self, call_log: list[str] | None = None):
        def create_completion(**kwargs):
            if call_log is not None:
                call_log.append(kwargs["messages"][1]["content"])
            payload = {
                "ref_class": "TradeTerms",
                "ref_class_confidence": 0.8,
                "column_alignments": [
                    {
                        "column": "ContractNo",
                        "ref_property": "incoterm",
                        "alignment": "semantic",
                        "confidence": 0.7,
                        "rationale": "model's own guess",
                    },
                ],
            }
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
            )

        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        return client

    def _write_conformance(self, tmp_path, *concepts, name="core-concepts-conformance.yaml"):
        path = tmp_path / name
        path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "core_concepts": list(concepts),
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_confirmed_anchor_overrides_model_pick(
        self,
        analysis_dir,
        sources_dir,
        tmp_path,
    ):
        conformance = self._write_conformance(
            tmp_path,
            {
                "uri": "https://example.com/ont/commercial#SalesContract",
                "label": "SalesContract",
                "outcome": "conforms",
            },
        )
        client = self._model_prefers_trade_terms_client()
        with (
            mock.patch("kairos_ontology.core.propose_alignment.get_ai_client", return_value=client),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=self.REF_CLASSES,
            ),
        ):
            alignments = build_domain_alignments(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                domains_filter=["commercial"],
                conformance_artifact_path=conformance,
            )
        commercial = next(a for a in alignments if a.domain == "commercial")
        ta = next(t for t in commercial.tables if t.table == "tblContracts")
        assert ta.ref_class == "SalesContract"
        assert ta.ref_class_status == "confirmed"
        assert ta.likely_entity_uri == "https://example.com/ont/commercial#SalesContract"
        # The column the model aligned inherits the *confirmed* class, not the
        # model's own ("TradeTerms") class pick.
        contract_no = next(c for c in ta.columns if c.column == "ContractNo")
        assert contract_no.ref_class == "SalesContract"
        assert ta.anchor_candidate_uris == []
        assert commercial.unresolved_anchors == []

    def test_no_conformance_artifact_keeps_existing_behavior(
        self,
        analysis_dir,
        sources_dir,
        tmp_path,
    ):
        # Default (no confirmed evidence at all) — the model's own pick stands,
        # exactly as before this feature.
        client = self._model_prefers_trade_terms_client()
        with (
            mock.patch("kairos_ontology.core.propose_alignment.get_ai_client", return_value=client),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=self.REF_CLASSES,
            ),
        ):
            alignments = build_domain_alignments(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                domains_filter=["commercial"],
            )
        ta = next(t for t in alignments[0].tables if t.table == "tblContracts")
        assert ta.ref_class == "TradeTerms"
        assert ta.ref_class_status == "matched"
        assert ta.likely_entity_uri == ""


class TestProposeAlignmentCLIReliability:
    """Alignment-reliability wiring through the `propose-alignment` CLI command:
    --allow-fallback-output passthrough and AlignmentTotalFailureError → exit 1."""

    def _cli_setup(self, tmp_path):
        analysis = tmp_path / "_analysis"
        sources = tmp_path / "sources"
        analysis.mkdir()
        sources.mkdir()
        (analysis / "crm-affinity.yaml").write_text(
            yaml.safe_dump({"system": "crm", "schema_version": 2, "tables": []}),
            encoding="utf-8",
        )
        return analysis, sources

    def test_total_failure_exits_nonzero_and_prints_no_success(self, tmp_path):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli
        from kairos_ontology.core.propose_alignment import AlignmentTotalFailureError

        analysis, sources = self._cli_setup(tmp_path)
        with mock.patch(
            "kairos_ontology.core.propose_alignment.run_propose_alignment",
            side_effect=AlignmentTotalFailureError("all 2 attempted table(s) failed"),
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "propose-alignment",
                    "--analysis",
                    str(analysis),
                    "--sources",
                    str(sources),
                    "--output",
                    str(tmp_path / "out"),
                ],
            )
        assert result.exit_code == 1
        assert "✅" not in result.output
        assert "Proposal complete" not in result.output
        assert "all 2 attempted table(s) failed" in result.output

    def test_provider_failure_summary_line_shown(self, tmp_path):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        analysis, sources = self._cli_setup(tmp_path)
        with mock.patch(
            "kairos_ontology.core.propose_alignment.run_propose_alignment",
            return_value=[],
        ) as run_mock:

            def side_effect(*args, **kwargs):
                stats = kwargs.get("generation_stats")
                if stats is not None:
                    stats.update({"attempted": 3, "semantic_success": 2, "provider_failure": 1})
                return []

            run_mock.side_effect = side_effect
            result = CliRunner().invoke(
                cli,
                [
                    "propose-alignment",
                    "--analysis",
                    str(analysis),
                    "--sources",
                    str(sources),
                    "--output",
                    str(tmp_path / "out"),
                ],
            )
        assert result.exit_code == 0, result.output
        assert "1 of 3 attempted table(s) had a semantic generation failure" in result.output


# placeholder-marker-for-append


class TestTotalFailureNoWriteGuarantee:
    """AlignmentTotalFailureError promises that *nothing* was written by the run.

    Writes are staged and committed only once the run-wide semantic verdict is
    known, so the promise also holds for the two cases a per-domain gate cannot
    catch on its own: a domain that mixes ``provider_failure`` with
    ``fallback_only`` tables (neither group covers the whole domain), and a
    fallback-only domain explicitly opted in via ``--allow-fallback-output``.
    """

    REF_CLASSES = [
        {
            "name": "SalesContract",
            "label": "Sales Contract",
            "comment": "",
            "uri": "https://example.com/ont/commercial#SalesContract",
            "properties": [
                {"name": "contractIdentifier", "label": "Contract ID", "range": "string"},
            ],
        },
        {
            "name": "TradeTerms",
            "label": "Trade Terms",
            "comment": "",
            "uri": "https://example.com/ont/commercial#TradeTerms",
            "properties": [
                {"name": "incoterm", "label": "Incoterm", "range": "string"},
            ],
        },
    ]

    @pytest.fixture
    def mixed_analysis_dir(self, tmp_path):
        """One domain, two tables: one becomes fallback_only (ambiguous anchor),
        the other is attempted and fails at the provider."""
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
                    "total_columns": 1,
                    "domain": "commercial",
                    "domain_uris": ["https://example.com/ont/commercial#"],
                    "confidence": 0.9,
                    "likely_entity": "SalesContract",
                    "indicative_columns": ["ContractNo"],
                },
                {
                    "table": "tblOrders",
                    "total_columns": 1,
                    "domain": "commercial",
                    "domain_uris": ["https://example.com/ont/commercial#"],
                    "confidence": 0.8,
                    "likely_entity": "PurchaseOrder",
                    "indicative_columns": ["OrderNo"],
                },
            ],
        }
        (analysis / "adminpulse-affinity.yaml").write_text(
            yaml.safe_dump(affinity), encoding="utf-8"
        )
        return analysis

    @pytest.fixture
    def mixed_sources_dir(self, tmp_path):
        sources = tmp_path / "sources"
        admin_dir = sources / "adminpulse"
        admin_dir.mkdir(parents=True)
        (admin_dir / "adminpulse.vocabulary.ttl").write_text(
            """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .

<#tblContracts> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblContracts" .

<#tblContracts_ContractNo> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "ContractNo" ;
    kairos-bronze:dataType "nvarchar(50)" ;
    kairos-bronze:belongsToTable <#tblContracts> .

<#tblOrders> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblOrders" .

<#tblOrders_OrderNo> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "OrderNo" ;
    kairos-bronze:dataType "nvarchar(50)" ;
    kairos-bronze:belongsToTable <#tblOrders> .
""",
            encoding="utf-8",
        )
        return sources

    def _ambiguous_conformance(self, tmp_path):
        path = tmp_path / "core-concepts-conformance.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "core_concepts": [
                        {
                            "uri": "https://example.com/ont/commercial#SalesContract",
                            "label": "SalesContract",
                            "outcome": "conforms",
                        },
                        {
                            "uri": "https://example.com/ont/commercial#TradeTerms",
                            "label": "SalesContract",
                            "outcome": "conforms",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def _failing_client(self):
        client = mock.MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("provider outage")
        return client

    def test_cached_domain_skip_still_returned_in_order(
        self,
        analysis_dir,
        sources_dir,
        tmp_path,
    ):
        """A freshness-cached domain is reported once, in domain order, next to
        a newly committed one."""
        out = tmp_path / "out"

        def create_completion(**kwargs):
            prompt = kwargs["messages"][1]["content"]
            ref_class = "SalesContract" if "tblContracts" in prompt else "TradeTerms"
            payload = {
                "ref_class": ref_class,
                "ref_class_confidence": 0.9,
                "column_alignments": [],
            }
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
            )

        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        with (
            mock.patch(
                "kairos_ontology.core.propose_alignment.get_ai_client",
                return_value=client,
            ),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=self.REF_CLASSES,
            ),
        ):
            first = run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                output_dir=out,
            )
            second = run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                output_dir=out,
            )
        assert [f.name for f in second] == [f.name for f in first]
        assert [f.name for f in second] == sorted(f.name for f in second)


class TestModelPrecedence:
    """The caller/CLI-resolved model is authoritative; the per-role provider
    config (``KAIROS_AI_ALIGNMENT_MODEL``) is endpoint/auth/preflight metadata
    and must never override an explicitly pinned ``--model``/``--high-accuracy``.
    """

    REF_CLASSES = [
        {
            "name": "SalesContract",
            "label": "Sales Contract",
            "comment": "",
            "properties": [
                {"name": "contractIdentifier", "label": "Contract ID", "range": "string"},
            ],
        },
    ]

    def _recording_client(self, seen: list[str]):
        def create_completion(**kwargs):
            seen.append(kwargs["model"])
            payload = {
                "ref_class": "SalesContract",
                "ref_class_confidence": 0.9,
                "column_alignments": [],
            }
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
            )

        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        return client

    def _run(self, analysis_dir, sources_dir, model, env):
        import os

        seen: list[str] = []
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch(
                "kairos_ontology.core.propose_alignment.get_ai_client",
                return_value=self._recording_client(seen),
            ),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=self.REF_CLASSES,
            ),
        ):
            alignments = build_domain_alignments(
                analysis_dir=analysis_dir,
                sources_dir=sources_dir,
                catalog_path=None,
                model=model,
                domains_filter=["commercial"],
            )
        return seen, alignments

    def test_explicit_model_wins_over_role_env_override(self, analysis_dir, sources_dir):
        seen, alignments = self._run(
            analysis_dir,
            sources_dir,
            "gpt-explicit",
            {"GITHUB_TOKEN": "tok", "KAIROS_AI_ALIGNMENT_MODEL": "gpt-role-override"},
        )
        assert seen and set(seen) == {"gpt-explicit"}
        assert alignments[0].model_used == "gpt-explicit"

    def test_high_accuracy_model_wins_over_role_env_override(self, analysis_dir, sources_dir):
        from kairos_ontology.core.propose_alignment import HIGH_ACCURACY_MODEL

        seen, alignments = self._run(
            analysis_dir,
            sources_dir,
            HIGH_ACCURACY_MODEL,
            {"GITHUB_TOKEN": "tok", "KAIROS_AI_ALIGNMENT_MODEL": "gpt-role-override"},
        )
        assert set(seen) == {HIGH_ACCURACY_MODEL}
        assert alignments[0].model_used == HIGH_ACCURACY_MODEL

    def test_role_endpoint_does_not_change_the_model_either(self, analysis_dir, sources_dir):
        # A dedicated per-role endpoint may change provider/auth, never the model.
        seen, _ = self._run(
            analysis_dir,
            sources_dir,
            "gpt-explicit",
            {
                "GITHUB_TOKEN": "tok",
                "KAIROS_AI_ALIGNMENT_ENDPOINT": "https://strong.example.com/v1",
                "KAIROS_AI_ALIGNMENT_KEY": "align-key",
                "KAIROS_AI_ALIGNMENT_MODEL": "gpt-role-override",
            },
        )
        assert set(seen) == {"gpt-explicit"}

    def test_no_role_override_uses_caller_model_unchanged(self, analysis_dir, sources_dir):
        seen, _ = self._run(
            analysis_dir,
            sources_dir,
            "gpt-explicit",
            {"GITHUB_TOKEN": "tok"},
        )
        assert set(seen) == {"gpt-explicit"}

    def test_cli_precedence_explicit_model_beats_role_env(self, tmp_path):
        import os

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        analysis = tmp_path / "_analysis"
        sources = tmp_path / "sources"
        analysis.mkdir()
        sources.mkdir()
        (analysis / "crm-affinity.yaml").write_text(
            yaml.safe_dump({"system": "crm", "schema_version": 2, "tables": []}),
            encoding="utf-8",
        )
        captured: dict = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            return []

        env = {"GITHUB_TOKEN": "tok", "KAIROS_AI_ALIGNMENT_MODEL": "gpt-role-override"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch(
                "kairos_ontology.core.propose_alignment.run_propose_alignment",
                side_effect=fake_run,
            ),
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "propose-alignment",
                    "--analysis",
                    str(analysis),
                    "--sources",
                    str(sources),
                    "--output",
                    str(tmp_path / "out"),
                    "--model",
                    "gpt-explicit",
                ],
            )
        assert result.exit_code == 0, result.output
        assert captured["model"] == "gpt-explicit"

    def test_cli_precedence_high_accuracy_beats_role_env(self, tmp_path):
        import os

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli
        from kairos_ontology.core.propose_alignment import HIGH_ACCURACY_MODEL

        analysis = tmp_path / "_analysis"
        sources = tmp_path / "sources"
        analysis.mkdir()
        sources.mkdir()
        (analysis / "crm-affinity.yaml").write_text(
            yaml.safe_dump({"system": "crm", "schema_version": 2, "tables": []}),
            encoding="utf-8",
        )
        captured: dict = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            return []

        env = {"GITHUB_TOKEN": "tok", "KAIROS_AI_ALIGNMENT_MODEL": "gpt-role-override"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch(
                "kairos_ontology.core.propose_alignment.run_propose_alignment",
                side_effect=fake_run,
            ),
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "propose-alignment",
                    "--analysis",
                    str(analysis),
                    "--sources",
                    str(sources),
                    "--output",
                    str(tmp_path / "out"),
                    "--high-accuracy",
                ],
            )
        assert result.exit_code == 0, result.output
        assert captured["model"] == HIGH_ACCURACY_MODEL

    def test_cli_role_env_is_still_the_default_when_nothing_is_pinned(self, tmp_path):
        import os

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        analysis = tmp_path / "_analysis"
        sources = tmp_path / "sources"
        analysis.mkdir()
        sources.mkdir()
        (analysis / "crm-affinity.yaml").write_text(
            yaml.safe_dump({"system": "crm", "schema_version": 2, "tables": []}),
            encoding="utf-8",
        )
        captured: dict = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            return []

        env = {"GITHUB_TOKEN": "tok", "KAIROS_AI_ALIGNMENT_MODEL": "gpt-role-override"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch(
                "kairos_ontology.core.propose_alignment.run_propose_alignment",
                side_effect=fake_run,
            ),
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "propose-alignment",
                    "--analysis",
                    str(analysis),
                    "--sources",
                    str(sources),
                    "--output",
                    str(tmp_path / "out"),
                ],
            )
        assert result.exit_code == 0, result.output
        assert captured["model"] == "gpt-role-override"


# ---------------------------------------------------------------------------
# Tests: cross-module alignment (DD-070, issue #166)
# ---------------------------------------------------------------------------


PARTY_URI = "https://example.com/ont/party#"
SIBLING_URI = "https://example.com/ont/reference-data#"


def _home_classes():
    return [
        {
            "name": "TradeParty",
            "label": "Trade Party",
            "comment": "",
            "properties": [{"name": "partyName", "label": "Party Name", "range": "string"}],
        },
    ]


def _widened_classes():
    """Home TradeParty + a sibling/shared-module Address class (tagged)."""
    return [
        {
            "name": "TradeParty",
            "label": "Trade Party",
            "comment": "",
            "properties": [{"name": "partyName", "label": "Party Name", "range": "string"}],
            "source_uri": PARTY_URI,
            "module": "party",
            "ref_class_id": "party:TradeParty",
            "belongs_to_domains": ["party"],
        },
        {
            "name": "Address",
            "label": "Address",
            "comment": "A postal address",
            "properties": [
                {"name": "street", "label": "Street", "range": "string"},
                {"name": "postalCode", "label": "Postal Code", "range": "string"},
            ],
            "source_uri": SIBLING_URI,
            "module": "reference-data",
            "ref_class_id": "reference-data:Address",
            "belongs_to_domains": ["party", "commercial"],
        },
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
            {
                "name": "Address",
                "module": "party",
                "source_uri": PARTY_URI,
                "is_home": True,
                "belongs_to_domains": ["party"],
            },
            {
                "name": "Address",
                "module": "reference-data",
                "source_uri": SIBLING_URI,
                "is_home": False,
                "belongs_to_domains": ["commercial"],
            },
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
            {
                "name": "TradeParty",
                "module": "party",
                "source_uri": PARTY_URI,
                "is_home": True,
                "belongs_to_domains": ["party"],
            },
        ]
        index = _build_class_meta_index(classes)
        assert _resolve_column_module("TradeParty", "party", index) is None

    def test_unknown_class_returns_none(self):
        index = _build_class_meta_index(_widened_classes())
        assert _resolve_column_module("Nonexistent", "", index) is None

    def test_prefers_home_when_module_ambiguous(self):
        classes = [
            {
                "name": "Address",
                "module": "party",
                "source_uri": PARTY_URI,
                "is_home": True,
                "belongs_to_domains": ["party"],
            },
            {
                "name": "Address",
                "module": "reference-data",
                "source_uri": SIBLING_URI,
                "is_home": False,
                "belongs_to_domains": ["commercial"],
            },
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
            "tblParties",
            columns,
            widened,
            home_shortlist,
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
            "tblParties",
            columns,
            widened,
            home_shortlist,
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
        assert "It must be one of: TradeParty" in prompt


class TestAlignTableCrossModule:
    def _client(self, payload):
        client = mock.MagicMock()
        client.chat.completions.create.return_value = mock.MagicMock(
            choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
        )
        return client

    def test_captures_ref_module_when_present(self):
        payload = {
            "ref_class": "TradeParty",
            "ref_class_confidence": 0.9,
            "column_alignments": [
                {
                    "column": "SHIPPER_STREET",
                    "ref_class": "Address",
                    "ref_module": "reference-data",
                    "ref_property": "street",
                    "alignment": "semantic",
                    "confidence": 0.8,
                    "rationale": "street",
                },
            ],
        }
        client = self._client(payload)
        result = align_table(
            client,
            "gpt",
            "tblParties",
            [{"name": "SHIPPER_STREET", "data_type": "nvarchar"}],
            _widened_classes(),
            table_ref_classes=_home_classes(),
        )
        assert result["ref_class"] == "TradeParty"  # validated against home pool
        assert result["column_alignments"][0]["ref_module"] == "reference-data"

    def test_default_mode_omits_ref_module(self):
        payload = {
            "ref_class": "TradeParty",
            "ref_class_confidence": 0.9,
            "column_alignments": [
                {
                    "column": "PartyName",
                    "ref_class": "TradeParty",
                    "ref_property": "partyName",
                    "alignment": "exact",
                    "confidence": 0.95,
                    "rationale": "match",
                },
            ],
        }
        client = self._client(payload)
        result = align_table(
            client,
            "gpt",
            "tblParties",
            [{"name": "PartyName", "data_type": "nvarchar"}],
            _home_classes(),
        )
        assert "ref_module" not in result["column_alignments"][0]


class TestWriteAlignmentOutputCrossModule:
    def test_emits_cross_module_fields(self, tmp_path):
        ca = ColumnAlignment(
            column="SHIPPER_STREET",
            data_type="nvarchar",
            ref_class="Address",
            ref_property="street",
            alignment="semantic",
            confidence=0.8,
            ref_module="reference-data",
            ref_module_uri=SIBLING_URI,
            belongs_to_domains=["party", "commercial"],
        )
        ta = TableAlignment(
            system="adminpulse",
            table="tblParties",
            ref_class="TradeParty",
            ref_class_confidence=0.9,
            columns=[ca],
        )
        alignment = DomainAlignment(
            domain="party",
            domain_uris=[PARTY_URI],
            generated_at="2026-01-01T00:00:00Z",
            model_used="gpt",
            tables=[ta],
            affinity_sha256="abc",
            alignment_params_sha256="deadbeef",
            cross_module_matches=[
                {
                    "ref_class": "Address",
                    "ref_module": "reference-data",
                    "ref_module_uri": SIBLING_URI,
                    "belongs_to_domains": ["party", "commercial"],
                    "source_columns": ["adminpulse.tblParties.SHIPPER_STREET"],
                }
            ],
        )
        data = alignment_to_dict(alignment)
        col = data["tables"][0]["columns"][0]
        assert col["ref_module"] == "reference-data"
        assert col["belongs_to_domains"] == ["party", "commercial"]
        assert data["alignment_params_sha256"] == "deadbeef"
        assert len(data["cross_module_matches"]) == 1

    def test_default_omits_cross_module_fields(self, tmp_path):
        ca = ColumnAlignment(
            column="PartyName",
            data_type="nvarchar",
            ref_class="TradeParty",
            ref_property="partyName",
            alignment="exact",
            confidence=0.95,
        )
        ta = TableAlignment(
            system="adminpulse",
            table="tblParties",
            ref_class="TradeParty",
            ref_class_confidence=0.9,
            columns=[ca],
        )
        alignment = DomainAlignment(
            domain="party",
            domain_uris=[PARTY_URI],
            generated_at="2026-01-01T00:00:00Z",
            model_used="gpt",
            tables=[ta],
            affinity_sha256="abc",
        )
        data = alignment_to_dict(alignment)
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
    def _inventory_side_effect(
        self, domain_uris, catalog_path, *, inventory_dir=None, module_map=None
    ):
        if module_map is None:
            return _home_classes()
        return _widened_classes()

    def _client(self, calls=None):
        def create_completion(**kwargs):
            if calls is not None:
                calls.append(kwargs["messages"][1]["content"])
            payload = {
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {
                        "column": "SHIPPER_STREET",
                        "ref_class": "Address",
                        "ref_module": "reference-data",
                        "ref_property": "street",
                        "alignment": "semantic",
                        "confidence": 0.8,
                        "rationale": "street part",
                    },
                ],
            }
            return mock.MagicMock(
                choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(payload)))]
            )

        client = mock.MagicMock()
        client.chat.completions.create = create_completion
        return client

    def _run(self, analysis_dir, party_sources, output, calls=None, **kw):
        with (
            mock.patch(
                "kairos_ontology.core.propose_alignment.get_ai_client",
                return_value=self._client(calls),
            ),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                side_effect=self._inventory_side_effect,
            ),
            mock.patch(
                "kairos_ontology.core.analyse_sources.load_accelerator_uri_modules",
                return_value={
                    PARTY_URI: {"module": "party", "domains": ["party"]},
                    SIBLING_URI: {"module": "reference-data", "domains": ["party", "commercial"]},
                },
            ),
        ):
            return run_propose_alignment(
                analysis_dir=analysis_dir,
                sources_dir=party_sources,
                catalog_path=None,
                output_dir=output,
                domains_filter=["party"],
                **kw,
            )

    def _build(self, analysis_dir, party_sources, calls=None, **kw):
        with (
            mock.patch(
                "kairos_ontology.core.propose_alignment.get_ai_client",
                return_value=self._client(calls),
            ),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                side_effect=self._inventory_side_effect,
            ),
            mock.patch(
                "kairos_ontology.core.analyse_sources.load_accelerator_uri_modules",
                return_value={
                    PARTY_URI: {"module": "party", "domains": ["party"]},
                    SIBLING_URI: {"module": "reference-data", "domains": ["party", "commercial"]},
                },
            ),
        ):
            return build_domain_alignments(
                analysis_dir=analysis_dir,
                sources_dir=party_sources,
                catalog_path=None,
                domains_filter=["party"],
                **kw,
            )

    def test_column_matches_sibling_module(self, analysis_dir, party_sources, tmp_path):
        alignments = self._build(
            analysis_dir,
            party_sources,
            cross_module=True,
            accelerator="logistics",
            ref_models_dir=tmp_path,
        )
        data = alignment_to_dict(alignments[0])
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
        assert matches[0]["source_columns"] == ["adminpulse.tblParties.SHIPPER_STREET"]

    def test_full_inventory_retry_disabled(self, analysis_dir, party_sources, tmp_path):
        calls: list[str] = []
        self._build(
            analysis_dir,
            party_sources,
            calls=calls,
            cross_module=True,
            accelerator="logistics",
            ref_models_dir=tmp_path,
            max_prompt_classes=1,
        )
        # Exactly one LLM call for the single party table — no full-inventory retry.
        assert len(calls) == 1

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
        note = _transform_compat_note({"samples": ["12", "N/A", "34"]}, "integer")
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
                            example_values=["Acme NV", "Globex"],
                        ),
                        ColumnAlignment(
                            column="Code",
                            data_type="int",
                            ref_class="TradeParty",
                            ref_property="partyName",
                            alignment="semantic",
                            confidence=0.5,
                            transform_compat="1/3 sample values are non-numeric — "
                            "CAST may NULL/fail; confirm",
                        ),
                        ColumnAlignment(
                            column="Bare",
                            data_type="int",
                            ref_class="TradeParty",
                            ref_property="partyName",
                            alignment="semantic",
                            confidence=0.5,
                        ),
                    ],
                ),
            ],
        )
        data = alignment_to_dict(alignment)
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
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {
                        "column": "PartyName",
                        "ref_class": "TradeParty",
                        "ref_property": "partyName",
                        "alignment": "exact",
                        "confidence": 0.95,
                        "rationale": "name",
                    },
                    {
                        "column": "Email",
                        "ref_class": "TradeParty",
                        "ref_property": "contactEmail",
                        "alignment": "semantic",
                        "confidence": 0.8,
                        "rationale": "email",
                    },
                ],
            },
        }

    def _build(self, analysis_dir, sources, **kw):
        client = TestRunProposeAlignment()._mock_client(self._responses())
        with (
            mock.patch("kairos_ontology.core.propose_alignment.get_ai_client", return_value=client),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=[
                    {
                        "name": "TradeParty",
                        "label": "Trade Party",
                        "comment": "",
                        "properties": [
                            {"name": "partyName", "label": "Party Name", "range": "string"},
                            {"name": "contactEmail", "label": "Contact Email", "range": "string"},
                        ],
                    },
                ],
            ),
        ):
            return build_domain_alignments(
                analysis_dir=analysis_dir,
                sources_dir=sources,
                catalog_path=None,
                domains_filter=["party"],
                **kw,
            )

    def test_examples_on_by_default_pii_masked(self, analysis_dir, tmp_path):
        sources = self._vocab_with_samples(tmp_path)
        alignments = self._build(analysis_dir, sources)
        data = alignment_to_dict(alignments[0])
        cols = {c["column"]: c for c in data["tables"][0]["columns"]}
        # Non-PII column shows raw values by default.
        assert cols["PartyName"]["example_values"] == ["Acme NV", "Globex Corp"]
        # PII (email) column is masked — raw address must never appear.
        email_examples = cols["Email"]["example_values"]
        assert all("@" in v and "***" in v for v in email_examples)
        raw = yaml.safe_dump(data, allow_unicode=True)
        assert "jane.doe@acme.com" not in raw
        assert "bob@globex.com" not in raw

    def test_no_sample_values_suppresses(self, analysis_dir, tmp_path):
        sources = self._vocab_with_samples(tmp_path)
        alignments = self._build(analysis_dir, sources, include_sample_values=False)
        data = alignment_to_dict(alignments[0])
        for c in data["tables"][0]["columns"]:
            assert "example_values" not in c


# ---------------------------------------------------------------------------
# Issue #182 — WS-NORM canonical state + WS1 confidence-gated custom suggestions
# ---------------------------------------------------------------------------
class TestNormalizePropertyToken:
    def test_strips_non_alphanumeric_and_lowercases(self):
        assert _normalize_property_token("CF_String-33") == "cfstring33"
        assert _normalize_property_token("stageCode") == "stagecode"

    def test_none_and_empty(self):
        assert _normalize_property_token(None) == ""
        assert _normalize_property_token("") == ""


class TestNormCanonicalState:
    """WS-NORM: a mapped alignment with no ref_property collapses to custom."""

    def _mock_client(self, response_dict):
        client = mock.MagicMock()
        client.chat.completions.create.return_value = mock.MagicMock(
            choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(response_dict)))]
        )
        return client

    def test_semantic_without_ref_property_demoted_to_custom(self, sample_ref_classes):
        response = {
            "ref_class": "SalesContract",
            "ref_class_confidence": 0.8,
            "column_alignments": [
                {
                    "column": "X",
                    "ref_property": "",
                    "alignment": "semantic",
                    "confidence": 0.9,
                },
            ],
        }
        client = self._mock_client(response)
        columns = [{"name": "X", "data_type": "string"}]
        result = align_table(client, "gpt-5.4-mini", "tbl", columns, sample_ref_classes)
        assert result["column_alignments"][0]["alignment"] == "custom"

    def test_note_passthrough(self, sample_ref_classes):
        response = {
            "ref_class": "SalesContract",
            "ref_class_confidence": 0.8,
            "column_alignments": [
                {
                    "column": "X",
                    "ref_property": "",
                    "alignment": "custom",
                    "confidence": 0.0,
                    "note": "vendor-specific slot",
                },
            ],
        }
        client = self._mock_client(response)
        columns = [{"name": "X", "data_type": "string"}]
        result = align_table(client, "gpt-5.4-mini", "tbl", columns, sample_ref_classes)
        assert result["column_alignments"][0]["note"] == "vendor-specific slot"


class TestBuildCustomColumn:
    def test_high_confidence_keeps_suggestion(self):
        ca = {"column": "Foo", "ref_property": "fooBar", "confidence": 0.9}
        cc = _build_custom_column(ca, "nvarchar(50)", confidence_floor=0.5)
        assert cc["suggested_property"] == "fooBar"
        assert cc["confidence"] == 0.9
        assert cc["disposition"] is None

    def test_below_floor_nulls_suggestion(self):
        ca = {"column": "Foo", "ref_property": "stageCode", "confidence": 0.3}
        cc = _build_custom_column(ca, "nvarchar(50)", confidence_floor=0.5)
        assert cc["suggested_property"] is None

    def test_empty_ref_property_stays_null(self):
        ca = {"column": "Foo", "ref_property": "", "confidence": 0.99}
        cc = _build_custom_column(ca, "int", confidence_floor=0.5)
        assert cc["suggested_property"] is None

    def test_note_included_when_present(self):
        ca = {"column": "Foo", "ref_property": "", "confidence": 0.0, "note": "opaque slot"}
        cc = _build_custom_column(ca, "int", confidence_floor=0.5)
        assert cc["note"] == "opaque slot"

    def test_note_absent_when_blank(self):
        ca = {"column": "Foo", "ref_property": "", "confidence": 0.0, "note": "  "}
        cc = _build_custom_column(ca, "int", confidence_floor=0.5)
        assert "note" not in cc


class TestDowngradeCatchAllSuggestions:
    def test_catch_all_sink_nulled(self):
        cols = [
            {"column": "co2e_well_to_wheel", "suggested_property": "stageCode"},
            {"column": "tenant_id", "suggested_property": "stageCode"},
            {"column": "loaded_distance", "suggested_property": "stageCode"},
        ]
        downgraded = _downgrade_catch_all_suggestions(cols, min_columns=3)
        assert downgraded == 3
        assert all(c["suggested_property"] is None for c in cols)

    def test_below_threshold_preserved(self):
        cols = [
            {"column": "a", "suggested_property": "stageCode"},
            {"column": "b", "suggested_property": "stageCode"},
        ]
        downgraded = _downgrade_catch_all_suggestions(cols, min_columns=3)
        assert downgraded == 0
        assert all(c["suggested_property"] == "stageCode" for c in cols)

    def test_similar_named_column_not_counted_as_sink(self):
        # A genuinely repeated real attribute (column name ~ property) is preserved.
        cols = [
            {"column": "stage_code", "suggested_property": "stageCode"},
            {"column": "stageCode", "suggested_property": "stageCode"},
            {"column": "StageCode", "suggested_property": "stageCode"},
        ]
        downgraded = _downgrade_catch_all_suggestions(cols, min_columns=3)
        assert downgraded == 0
        assert all(c["suggested_property"] == "stageCode" for c in cols)

    def test_null_suggestions_ignored(self):
        cols = [
            {"column": "a", "suggested_property": None},
            {"column": "b", "suggested_property": None},
            {"column": "c", "suggested_property": None},
        ]
        assert _downgrade_catch_all_suggestions(cols, min_columns=3) == 0


class TestSourceColumnDigest:
    """F6 — deterministic source column digest (truncation integrity)."""

    def test_digest_is_deterministic_and_order_independent(self):
        a = _source_column_digest([{"name": "b"}, {"name": "a"}, {"name": "c"}])
        b = _source_column_digest([{"name": "a"}, {"name": "b"}, {"name": "c"}])
        assert a == b
        assert a[0] == 3
        assert len(a[1]) == 64

    def test_digest_changes_when_column_dropped(self):
        full = _source_column_digest([{"name": "a"}, {"name": "b"}, {"name": "c"}])
        dropped = _source_column_digest([{"name": "a"}, {"name": "b"}])
        assert full != dropped

    def test_empty_yields_zero(self):
        assert _source_column_digest([]) == (0, "")
        assert _source_column_digest([{"name": ""}]) == (0, "")


class TestReconciledPassthrough:
    """F6 — unaccounted source columns become explicit passthrough candidates."""

    def test_marks_reconciled_omission(self):
        cc = _build_reconciled_passthrough({"name": "extra_col", "data_type": "varchar"})
        assert cc["column"] == "extra_col"
        assert cc["reconciled_omission"] is True
        assert cc["disposition"] is None
        assert cc["data_type"] == "varchar"
        assert cc["suggested_property"] is None

    def test_missing_data_type_defaults_unknown(self):
        cc = _build_reconciled_passthrough({"name": "x"})
        assert cc["data_type"] == "unknown"
        assert "recommended_disposition" in cc


class TestObjectPropertyTarget:
    """F3 — object-property target resolution (scalar location cluster fix)."""

    def _range_idx(self, mapping):
        # {(None, prop): range}
        return {(None, p): r for p, r in mapping.items()}

    def test_datatype_property_is_not_object(self):
        idx = self._range_idx({"legalName": "string"})
        assert _resolve_object_property_target("legalName", "Party", idx, {}) is None

    def test_class_range_resolves_to_governed_target(self):
        idx = self._range_idx({"hasLocation": "Location"})
        classes = {"Location": "https://ex.org/ont/loc#Location"}
        res = _resolve_object_property_target("hasLocation", "Shipment", idx, classes)
        assert res is not None
        assert res["target_resolved"] is True
        assert res["target_class_uri"] == "https://ex.org/ont/loc#Location"
        assert res["cardinality"] == "n:1"

    def test_class_range_without_governed_target_is_unresolved(self):
        idx = self._range_idx({"hasPlaceOfReceipt": "Location"})
        res = _resolve_object_property_target("hasPlaceOfReceipt", "Shipment", idx, {})
        assert res is not None
        assert res["target_resolved"] is False
        assert res["target_class_uri"] is None
        assert res["target_name"] == "Location"

    def test_name_hint_fires_without_range(self):
        # No range metadata, but a known object-property name → unresolved target.
        res = _resolve_object_property_target("hasPlaceOfDelivery", "Shipment", {}, {})
        assert res is not None
        assert res["target_resolved"] is False

    def test_uri_range_reduced_to_localname(self):
        idx = self._range_idx({"hasLocation": "https://ex.org/ont/loc#Location"})
        classes = {"Location": "https://ex.org/ont/loc#Location"}
        res = _resolve_object_property_target("hasLocation", "Shipment", idx, classes)
        assert res["target_resolved"] is True

    def test_unknown_scalar_property_no_fire(self):
        assert _resolve_object_property_target("cityName", "Party", {}, {}) is None


class TestObjectPropertyBuilders:
    """F3 — passthrough + relationship-candidate builders."""

    def test_passthrough_marks_object_property(self):
        target = {
            "target_name": "Location",
            "target_class_uri": None,
            "target_resolved": False,
            "cardinality": "n:1",
        }
        cc = _build_object_property_passthrough(
            "place_of_receipt", "varchar", "hasPlaceOfReceipt", target
        )
        assert cc["object_property_passthrough"] is True
        assert cc["object_property"] == "hasPlaceOfReceipt"
        assert cc["disposition"] is None
        assert cc["suggested_property"] is None

    def test_candidate_carries_target_and_cardinality(self):
        target = {
            "target_name": "Location",
            "target_class_uri": None,
            "target_resolved": False,
            "cardinality": "n:1",
        }
        cand = _build_object_property_candidate(
            "tblShipment", "place_of_receipt", "hasPlaceOfReceipt", target
        )
        assert cand["type"] == "object_property_relationship_candidate"
        assert cand["suggested_relationship"] == "hasPlaceOfReceipt"
        assert cand["target_concept"] == "Location"
        assert cand["target_resolved"] is False
        assert cand["cardinality"] == "n:1"
        assert cand["source_columns"] == ["place_of_receipt"]
        assert cand["requires_human_confirmation"] is True


# ---------------------------------------------------------------------------
# proposal-quality — generic object-relationship safeguards
# ---------------------------------------------------------------------------


class TestTechnicalActorSafeguard:
    """Finding #9 — created_by_*/updated_by_* default to audit/passthrough."""

    @pytest.mark.parametrize(
        "column",
        [
            "created_by",
            "createdBy",
            "created_by_user",
            "updated_by_id",
            "modified_by",
            "deleted_by",
            "approved_by",
            "reviewed_by",
            "authorized_by",
            "changed_by",
        ],
    )
    def test_technical_actor_names_detected(self, column):
        assert _is_technical_actor_column(column) is True

    @pytest.mark.parametrize(
        "column",
        [
            "customer_name",
            "billing_city",
            "shipment_reference",
            "party_id",
        ],
    )
    def test_ordinary_columns_not_flagged(self, column):
        assert _is_technical_actor_column(column) is False

    def test_downgrade_reason_is_technical_actor_and_wins_over_others(self):
        # Even a technical-actor column that also looks like a location
        # property name must be flagged as technical_actor first.
        reason = _object_relationship_downgrade_reason(
            column="updated_by",
            data_type="varchar",
            ref_property="hasPlaceOfReceipt",
            target_resolved=True,
        )
        assert reason == "technical_actor"

    def test_technical_actor_never_gets_relationship_candidate(self):
        # A technical-actor object-property column downgrades to passthrough
        # ONLY — never a relationship candidate (finding #9: audit evidence,
        # not an in-domain relationship).
        target = {
            "target_name": "Party",
            "target_class_uri": "https://ex.org#Party",
            "target_resolved": True,
            "cardinality": "n:1",
        }
        reason = _object_relationship_downgrade_reason(
            column="updated_by",
            data_type="varchar",
            ref_property="hasResponsibleParty",
            target_resolved=True,
        )
        assert reason == "technical_actor"
        passthrough = _build_object_property_passthrough(
            "updated_by", "varchar", "hasResponsibleParty", target, reason=reason
        )
        assert passthrough["object_property_passthrough"] is True
        assert "audit" in passthrough["rationale"].lower()


class TestIdentifierEvidenceSafeguard:
    """Finding #9 — object relationships require target/entity identifier evidence."""

    def test_id_suffix_name_is_identifier(self):
        assert _looks_like_identifier_column("customer_id", "varchar") is True

    def test_reference_token_is_identifier(self):
        assert _looks_like_identifier_column("party_reference", "varchar") is True

    def test_integer_data_type_is_identifier(self):
        assert _looks_like_identifier_column("customer", "int") is True

    def test_descriptive_scalar_is_not_identifier(self):
        assert _looks_like_identifier_column("customer_name", "varchar") is False

    def test_point_does_not_false_positive_on_int_token(self):
        # 'point' contains the substring 'int' but must not tokenize as one.
        assert _looks_like_identifier_column("delivery_point", "varchar") is False

    def test_downgrade_reason_missing_identifier_evidence(self):
        reason = _object_relationship_downgrade_reason(
            column="customer_name",
            data_type="varchar",
            ref_property="hasCustomer",
            target_resolved=True,
        )
        assert reason == "missing_identifier_evidence"

    def test_identifier_evidence_present_keeps_mapping(self):
        reason = _object_relationship_downgrade_reason(
            column="customer_id",
            data_type="int",
            ref_property="hasCustomer",
            target_resolved=True,
        )
        assert reason is None


class TestTypedLocationEvidenceSafeguard:
    """Finding #9 — specialized location properties need explicit role evidence."""

    def test_role_token_derivation(self):
        assert _location_role_token("hasPlaceOfReceipt") == "receipt"
        assert _location_role_token("hasPlaceOfDelivery") == "delivery"
        assert _location_role_token("hasOrigin") == "origin"
        assert _location_role_token("hasDestination") == "destination"

    def test_generic_location_properties_have_no_role(self):
        assert _location_role_token("hasLocation") is None
        assert _location_role_token("hasAddress") is None

    def test_is_location_object_property(self):
        assert _is_location_object_property("hasPlaceOfReceipt") is True
        assert _is_location_object_property("hasCustomer") is False

    def test_matching_column_has_typed_role_evidence(self):
        assert _has_typed_role_evidence("PlaceOfReceipt", "receipt") is True
        assert _has_typed_role_evidence("receipt_location", "receipt") is True

    def test_bare_location_column_lacks_typed_role_evidence(self):
        assert _has_typed_role_evidence("location", "receipt") is False

    def test_downgrade_reason_missing_typed_role_evidence(self):
        # A generic "location" column force-fit onto a specific port property
        # must be downgraded — no explicit evidence for that specific role.
        reason = _object_relationship_downgrade_reason(
            column="location",
            data_type="varchar",
            ref_property="hasPlaceOfDischarge",
            target_resolved=True,
        )
        assert reason == "missing_typed_role_evidence"

    def test_typed_evidence_present_keeps_mapping(self):
        reason = _object_relationship_downgrade_reason(
            column="discharge_location",
            data_type="varchar",
            ref_property="hasPlaceOfDischarge",
            target_resolved=True,
        )
        assert reason is None

    def test_generic_location_property_exempt_from_typed_role_check(self):
        # hasLocation/hasAddress carry no specific role → identifier-evidence
        # style checks don't apply to them either (location branch, role=None).
        reason = _object_relationship_downgrade_reason(
            column="site",
            data_type="varchar",
            ref_property="hasLocation",
            target_resolved=True,
        )
        assert reason is None


# ---------------------------------------------------------------------------
# proposal-quality — generalized relationship-candidate clustering
# ---------------------------------------------------------------------------


class TestRelationshipClusterId:
    def test_stable_and_deterministic(self):
        a = _relationship_cluster_id("booking", "shipment", "receipt", "Location", "n:1")
        b = _relationship_cluster_id("booking", "shipment", "receipt", "Location", "n:1")
        assert a == b

    def test_differs_by_domain(self):
        a = _relationship_cluster_id("booking", "t", "default", "Address", "1:n")
        b = _relationship_cluster_id("customs", "t", "default", "Address", "1:n")
        assert a != b

    def test_address_candidates_carry_cluster_id(self):
        out = _detect_address_relationship_candidates(
            "companies",
            [{"name": n} for n in ("billing_street", "billing_city", "billing_postal_code")],
            domain="party",
        )
        assert len(out) == 1
        assert "cluster_id" in out[0]
        assert out[0]["cluster_id"] == _relationship_cluster_id(
            "party",
            "companies",
            "billing",
            "Address",
            "1:n",
        )


class TestClusterObjectPropertyCandidates:
    """proposal-quality finding #8 — one cluster per relationship, all
    contributing columns carried together, stable cluster_id."""

    def _candidate(self, table, column, ref_property, target_concept="Location"):
        target = {
            "target_name": target_concept,
            "target_class_uri": None,
            "target_resolved": False,
            "cardinality": "n:1",
        }
        return _build_object_property_candidate(table, column, ref_property, target)

    def test_multiple_columns_same_relationship_collapse_into_one_cluster(self):
        candidates = [
            self._candidate("shipment", "receipt_location", "hasPlaceOfReceipt"),
            self._candidate("shipment", "receipt_terminal", "hasPlaceOfReceipt"),
        ]
        merged = _cluster_object_property_candidates(candidates, domain="logistics")
        assert len(merged) == 1
        assert merged[0]["source_columns"] == ["receipt_location", "receipt_terminal"]
        assert "cluster_id" in merged[0]

    def test_different_relationships_stay_separate(self):
        candidates = [
            self._candidate("shipment", "receipt_location", "hasPlaceOfReceipt"),
            self._candidate("shipment", "delivery_location", "hasPlaceOfDelivery"),
        ]
        merged = _cluster_object_property_candidates(candidates, domain="logistics")
        assert len(merged) == 2
        rels = {c["suggested_relationship"] for c in merged}
        assert rels == {"hasPlaceOfReceipt", "hasPlaceOfDelivery"}

    def test_single_column_cluster_unchanged_besides_cluster_id(self):
        candidates = [self._candidate("shipment", "receipt_location", "hasPlaceOfReceipt")]
        merged = _cluster_object_property_candidates(candidates, domain="logistics")
        assert merged[0]["source_columns"] == ["receipt_location"]
        assert merged[0]["target_resolved"] is False

    def test_cluster_id_stable_when_membership_changes(self):
        # Same relationship, different contributing columns → same cluster_id
        # (stable dimensions only: table, relationship, target, cardinality).
        first = _cluster_object_property_candidates(
            [self._candidate("shipment", "receipt_location", "hasPlaceOfReceipt")],
            domain="logistics",
        )
        second = _cluster_object_property_candidates(
            [
                self._candidate("shipment", "receipt_location", "hasPlaceOfReceipt"),
                self._candidate("shipment", "receipt_terminal", "hasPlaceOfReceipt"),
            ],
            domain="logistics",
        )
        assert first[0]["cluster_id"] == second[0]["cluster_id"]

    def test_empty_input_returns_empty(self):
        assert _cluster_object_property_candidates([], domain="logistics") == []


# ---------------------------------------------------------------------------
# A5: Guard test — the wrong flag name must appear nowhere in the codebase.
# ---------------------------------------------------------------------------


def test_allow_fallback_registry_appears_nowhere():
    """The old --allow-fallback-registry flag was renamed to --allow-fallback-output.

    The wrong name must never reappear in source code, CLI definitions, or skill
    instructions.  Documentation and this test legitimately reference the old name.
    """
    import subprocess

    result = subprocess.run(
        [
            "git",
            "grep",
            "-rn",
            "allow-fallback-registry",
            "--",
            "src/",
            ".github/skills/",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    # git grep returns 1 when no matches found
    assert result.returncode == 1, (
        f"--allow-fallback-registry found in source/skills:\n{result.stdout}"
    )


class TestSampleBudget:
    """DD-166: 20 values per column is right for a code list, not for 1,304 columns."""

    def test_low_cardinality_column_gets_the_full_budget(self):
        from kairos_ontology.core.propose_alignment import _samples_for_column

        col = {"name": "status", "samples": [f"S{i}" for i in range(20)], "distinct_count": 6}
        assert len(_samples_for_column(col)) == 20

    def test_high_cardinality_column_is_trimmed_to_a_type_hint(self):
        from kairos_ontology.core.propose_alignment import (
            MAX_SAMPLES_HIGH_CARDINALITY,
            _samples_for_column,
        )

        col = {"name": "order_id", "samples": [f"ORD{i}" for i in range(20)],
               "distinct_count": 50_000}
        assert len(_samples_for_column(col)) == MAX_SAMPLES_HIGH_CARDINALITY

    def test_unknown_cardinality_is_treated_as_high(self):
        """Absent distinct_count is not evidence of a small code list."""
        from kairos_ontology.core.propose_alignment import (
            MAX_SAMPLES_HIGH_CARDINALITY,
            _samples_for_column,
        )

        col = {"name": "note", "samples": [f"n{i}" for i in range(20)]}
        assert len(_samples_for_column(col)) == MAX_SAMPLES_HIGH_CARDINALITY

    def test_a_very_wide_table_stays_within_the_per_table_budget(self):
        """The widest real table rendered ~162 KB of samples before this."""
        from kairos_ontology.core.propose_alignment import (
            MAX_TABLE_SAMPLE_CHARS,
            _format_source_columns,
        )

        columns = [
            {"name": f"col_{i}", "data_type": "varchar",
             "samples": [f"value-{i}-{j}" for j in range(20)], "distinct_count": 5}
            for i in range(1000)
        ]
        rendered = _format_source_columns(columns)
        sample_text = sum(
            len(line.split("| samples: ", 1)[1]) for line in rendered.splitlines()
            if "| samples: " in line
        )
        assert sample_text <= MAX_TABLE_SAMPLE_CHARS

    def test_budget_drops_samples_not_columns(self):
        """Dropping samples is acceptable; dropping a column silently is not.

        Note the pre-existing MAX_COLUMNS_PER_PROMPT cap: only the first 80 columns
        reach the prompt at all, independent of this budget. Every column *within* that
        window must still be listed even after the sample budget is exhausted.
        """
        from kairos_ontology.core.propose_alignment import (
            MAX_COLUMNS_PER_PROMPT,
            _format_source_columns,
        )

        columns = [
            {"name": f"col_{i}", "data_type": "varchar",
             "samples": ["x" * 40 for _ in range(20)], "distinct_count": 5}
            for i in range(300)
        ]
        rendered = _format_source_columns(columns)
        assert len(rendered.splitlines()) == MAX_COLUMNS_PER_PROMPT
        assert all(f"col_{i} " in rendered for i in range(MAX_COLUMNS_PER_PROMPT))
        # The tail of that window keeps its name and type after the budget is spent.
        assert f"col_{MAX_COLUMNS_PER_PROMPT - 1} (varchar)" in rendered


class TestWideTableSplitting:
    """A column that is never shown to the model is not assessed, only invisible."""

    def _classes(self):
        return [{"name": "Party", "uri": "https://x/#Party", "properties": []}]

    def _columns(self, n):
        return [{"name": f"col_{i}", "data_type": "varchar", "samples": []} for i in range(n)]

    def _client(self, monkeypatch, capture):
        from unittest.mock import MagicMock

        from kairos_ontology.core import propose_alignment as pa

        def fake_once(client, model, table_name, columns, ref_classes, likely_entity="",
                      *, table_ref_classes=None, anchor_override=None):
            capture.append({"columns": [c["name"] for c in columns],
                            "anchor_override": anchor_override})
            return {
                "ref_class": "Party",
                "ref_class_confidence": 0.9,
                "ref_class_status": "ok",
                "rejected_ref_class": None,
                "column_alignments": [{"column": c["name"]} for c in columns],
                "generation_outcome": pa.OUTCOME_SEMANTIC_SUCCESS,
                "generation_error": None,
            }

        monkeypatch.setattr(pa, "_align_table_once", fake_once)
        return MagicMock()

    def test_narrow_table_is_a_single_call(self, monkeypatch):
        from kairos_ontology.core.propose_alignment import align_table

        calls = []
        client = self._client(monkeypatch, calls)
        align_table(client, "m", "t", self._columns(10), self._classes())
        assert len(calls) == 1

    def test_wide_table_splits_and_every_column_is_assessed(self, monkeypatch):
        from kairos_ontology.core.propose_alignment import MAX_COLUMNS_PER_PROMPT, align_table

        calls = []
        client = self._client(monkeypatch, calls)
        total = MAX_COLUMNS_PER_PROMPT * 2 + 25
        result = align_table(client, "m", "t", self._columns(total), self._classes())

        assert len(calls) == 3
        aligned = [a["column"] for a in result["column_alignments"]]
        assert len(aligned) == total
        assert aligned == [f"col_{i}" for i in range(total)]

    def test_later_chunks_are_pinned_to_the_first_chunks_class(self, monkeypatch):
        """A chunk of trailing columns cannot recognise the table on its own."""
        from kairos_ontology.core.propose_alignment import MAX_COLUMNS_PER_PROMPT, align_table

        calls = []
        client = self._client(monkeypatch, calls)
        align_table(client, "m", "t", self._columns(MAX_COLUMNS_PER_PROMPT + 5), self._classes())

        assert calls[0]["anchor_override"] is None
        assert calls[1]["anchor_override"] == "Party"

    def test_a_failing_chunk_fails_the_table(self, monkeypatch):
        """Reporting a partial column set as complete is the worse outcome."""
        from unittest.mock import MagicMock

        from kairos_ontology.core import propose_alignment as pa

        seen = {"n": 0}

        def fake_once(*args, **kwargs):
            seen["n"] += 1
            outcome = (
                pa.OUTCOME_SEMANTIC_SUCCESS if seen["n"] == 1 else pa.OUTCOME_PROVIDER_FAILURE
            )
            return {
                "ref_class": "Party", "ref_class_confidence": 0.9, "ref_class_status": "ok",
                "rejected_ref_class": None, "column_alignments": [],
                "generation_outcome": outcome, "generation_error": "boom",
            }

        monkeypatch.setattr(pa, "_align_table_once", fake_once)
        result = pa.align_table(
            MagicMock(), "m", "t", self._columns(pa.MAX_COLUMNS_PER_PROMPT + 5), self._classes()
        )
        assert result["generation_outcome"] == pa.OUTCOME_PROVIDER_FAILURE
